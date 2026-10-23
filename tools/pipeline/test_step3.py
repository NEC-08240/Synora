"""Unit and integration tests for Synora Phase C Step 3: Team Identity + Dual-Network Foundation."""

import json
import os
import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from tools.pipeline.audit import AuditLogger, scrub_sensitive
from tools.pipeline.auth import (
    AuthenticationError,
    ChallengeExpired,
    ChallengeStore,
    DeveloperSuspended,
    ReplayDetected,
    create_session_token,
    generate_keypair,
    sign_message,
    verify_developer_signature,
    verify_session_token,
)
from tools.pipeline.authorization import AuthorizationError, AuthorizationPolicy
from tools.pipeline.bridge import Bridge
from tools.pipeline.contribution_gate import ContributionGate, ContributionGateError, extract_files_from_diff
from tools.pipeline.gateway import Gateway
from tools.pipeline.protocol import (
    MSG_AUTHENTICATE,
    MSG_HEARTBEAT,
    MSG_JOB_ACK,
    MSG_JOB_ASSIGN,
    MSG_JOB_CANCEL,
    MSG_JOB_FAILURE,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_WORKER_DISCONNECT,
    MSG_WORKER_REGISTER,
    ProtocolEnvelope,
    ProtocolError,
    ProtocolMessage,
)
from tools.pipeline.queue import JobQueue
from tools.pipeline.records import RecordStore
from tools.pipeline.team_registry import DeveloperEntry, DeveloperNotFound, RegistryError, TeamRegistry
from tools.pipeline.worker import ClaudeWorker, OutboundWorker


class TestTeamRegistry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pub_a, self.priv_a = generate_keypair()
        self.pub_b, self.priv_b = generate_keypair()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_enrollment_and_retrieval(self):
        entry = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_a,
            assigned_modules=("frontend/", "docs/"),
            allowed_branches=("feature/*", "bugfix/*"),
        )
        registry = TeamRegistry([entry])
        retrieved = registry.get("dev-001")
        self.assertEqual(retrieved.developer_name, "Developer One")
        self.assertEqual(retrieved.github_username, "dev1")
        self.assertTrue(retrieved.is_active())
        self.assertFalse(retrieved.is_owner())
        self.assertTrue(retrieved.can_touch_branch("feature/login"))
        self.assertFalse(retrieved.can_touch_branch("main"))
        self.assertTrue(retrieved.can_touch_file("frontend/components/App.tsx"))
        self.assertFalse(retrieved.can_touch_file("backend/server.py"))

    def test_duplicate_developer_rejected(self):
        entry1 = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_a,
        )
        entry2 = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer Two",
            github_username="dev2",
            role="developer",
            status="active",
            public_key_b64=self.pub_b,
        )
        registry = TeamRegistry([entry1])
        with self.assertRaises(RegistryError):
            registry.register(entry2)

    def test_invalid_role_rejected(self):
        with self.assertRaises(RegistryError):
            DeveloperEntry(
                developer_id="dev-001",
                developer_name="Bad Role Dev",
                github_username="badrole",
                role="superadmin",
                status="active",
                public_key_b64=self.pub_a,
            )

    def test_invalid_status_rejected(self):
        with self.assertRaises(RegistryError):
            DeveloperEntry(
                developer_id="dev-001",
                developer_name="Bad Status Dev",
                github_username="badstatus",
                role="developer",
                status="banned",
                public_key_b64=self.pub_a,
            )

    def test_invalid_public_key_rejected(self):
        with self.assertRaises(RegistryError):
            DeveloperEntry(
                developer_id="dev-001",
                developer_name="Bad Key Dev",
                github_username="badkey",
                role="developer",
                status="active",
                public_key_b64="not-base64!",
            )
        # 31 bytes instead of 32
        with self.assertRaises(RegistryError):
            DeveloperEntry(
                developer_id="dev-001",
                developer_name="Short Key Dev",
                github_username="shortkey",
                role="developer",
                status="active",
                public_key_b64="AAAA" * 7 + "AA==",
            )

    def test_suspend_and_activate_developer(self):
        entry = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_a,
        )
        registry = TeamRegistry([entry])
        self.assertTrue(registry.is_active("dev-001"))

        registry.suspend("dev-001")
        self.assertFalse(registry.is_active("dev-001"))
        self.assertEqual(registry.get("dev-001").status, "suspended")

        registry.activate("dev-001")
        self.assertTrue(registry.is_active("dev-001"))
        self.assertEqual(registry.get("dev-001").status, "active")

    def test_persistence_save_and_load(self):
        entry = DeveloperEntry(
            developer_id="johan",
            developer_name="Johan Joseph",
            github_username="johanjoseph",
            role="project_owner",
            status="active",
            public_key_b64=self.pub_a,
        )
        registry = TeamRegistry([entry])
        save_path = Path(self.tmpdir) / "registry.json"
        registry.save(save_path)

        loaded = TeamRegistry.load(save_path)
        johan = loaded.get("johan")
        self.assertEqual(johan.developer_name, "Johan Joseph")
        self.assertTrue(johan.is_owner())


class TestAuthentication(unittest.TestCase):
    def setUp(self):
        self.pub_a, self.priv_a = generate_keypair()
        self.pub_b, self.priv_b = generate_keypair()
        self.dev = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_a,
        )
        self.registry = TeamRegistry([self.dev])
        self.challenges = ChallengeStore(default_ttl_seconds=60)
        self.secret = b"k" * 32

    def test_valid_signature_verification(self):
        challenge = self.challenges.create("dev-001")
        sig = sign_message(self.priv_a, challenge["message"])
        consumed_msg = self.challenges.consume("dev-001", challenge["nonce"])
        self.assertTrue(verify_developer_signature(self.dev, consumed_msg, sig))

    def test_invalid_signature_rejected(self):
        challenge = self.challenges.create("dev-001")
        sig_wrong_key = sign_message(self.priv_b, challenge["message"])
        consumed_msg = self.challenges.consume("dev-001", challenge["nonce"])
        with self.assertRaises(AuthenticationError):
            verify_developer_signature(self.dev, consumed_msg, sig_wrong_key)

    def test_replayed_challenge_rejected(self):
        challenge = self.challenges.create("dev-001")
        self.challenges.consume("dev-001", challenge["nonce"])
        with self.assertRaises(ReplayDetected):
            self.challenges.consume("dev-001", challenge["nonce"])

    def test_expired_challenge_rejected(self):
        challenge = self.challenges.create("dev-001", ttl_seconds=-1)
        with self.assertRaises(ChallengeExpired):
            self.challenges.consume("dev-001", challenge["nonce"])

    def test_suspended_developer_rejected(self):
        self.registry.suspend("dev-001")
        with self.assertRaises(DeveloperSuspended):
            verify_developer_signature(self.registry.get("dev-001"), "test", "dummy")

    def test_session_token_no_ip_binding(self):
        token = create_session_token(self.dev, self.secret, ttl_seconds=120)
        verified_dev = verify_session_token(token, self.secret, self.registry)
        self.assertEqual(verified_dev.developer_id, "dev-001")

    def test_tampered_session_token_rejected(self):
        token = create_session_token(self.dev, self.secret, ttl_seconds=120)
        tampered = token[:-4] + "ffff"
        with self.assertRaises(AuthenticationError):
            verify_session_token(tampered, self.secret, self.registry)


class TestAuthorization(unittest.TestCase):
    def setUp(self):
        self.pub_a, _ = generate_keypair()
        self.pub_owner, _ = generate_keypair()
        self.dev = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_a,
            assigned_modules=("frontend/",),
            allowed_branches=("feature/*",),
        )
        self.owner = DeveloperEntry(
            developer_id="johan",
            developer_name="Johan Joseph",
            github_username="johanjoseph",
            role="project_owner",
            status="active",
            public_key_b64=self.pub_owner,
            assigned_modules=("**",),
            allowed_branches=("*",),
        )

    def test_developer_accesses_own_job(self):
        own_job = {"job_id": "job-123", "developer_id": "dev-001"}
        AuthorizationPolicy.check_job_access(self.dev, own_job, action="read")

    def test_cross_developer_access_rejected(self):
        other_job = {"job_id": "job-456", "developer_id": "dev-002"}
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_job_access(self.dev, other_job, action="read")

    def test_project_owner_bypasses_job_isolation(self):
        other_job = {"job_id": "job-456", "developer_id": "dev-002"}
        AuthorizationPolicy.check_job_access(self.owner, other_job, action="inspect")

    def test_branch_authorization(self):
        AuthorizationPolicy.check_submit_task(self.dev, "feature/dashboard", "code")
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(self.dev, "main", "code")
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(self.dev, "release/v1", "code")

    def test_module_scope_authorization(self):
        AuthorizationPolicy.check_submit_task(
            self.dev, "feature/ui", "code", changed_files=["frontend/src/index.tsx"]
        )
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(
                self.dev, "feature/ui", "code", changed_files=["backend/api.py"]
            )

    def test_developer_admin_action_rejected(self):
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_admin_action(self.dev, "manage_team")
        AuthorizationPolicy.check_admin_action(self.owner, "manage_team")


class TestContributionGate(unittest.TestCase):
    def setUp(self):
        pub, _ = generate_keypair()
        self.dev = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=pub,
            assigned_modules=("frontend/", "docs/"),
            allowed_branches=("feature/*",),
        )

    def test_initial_task_valid(self):
        res = ContributionGate.validate(
            developer=self.dev,
            task="Add new navigation bar",
            task_type="code",
            branch="feature/nav",
            base_commit="abc1234",
            is_repair=False,
        )
        self.assertEqual(res["status"], "ACCEPTED")

    def test_initial_task_empty_description_rejected(self):
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=False,
            )

    def test_repair_task_empty_diff_rejected(self):
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="Fix broken test",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=True,
                developer_diff="",
                local_evidence={"exit_code": 1, "failure_output": "AssertionError"},
            )

    def test_repair_task_one_line_bugfix_accepted(self):
        # Correction #2: A 1-line bug fix is valid!
        one_line_diff = (
            "--- a/frontend/utils.ts\n"
            "+++ b/frontend/utils.ts\n"
            "@@ -10,1 +10,1 @@\n"
            "-const timeout = 1000;\n"
            "+const timeout = 5000;\n"
        )
        res = ContributionGate.validate(
            developer=self.dev,
            task="Fix test timeout",
            task_type="code",
            branch="feature/nav",
            base_commit="abc1234",
            is_repair=True,
            developer_diff=one_line_diff,
            local_evidence={"exit_code": 1, "failure_output": "TimeoutError after 1000ms"},
        )
        self.assertEqual(res["status"], "ACCEPTED")
        self.assertIn("frontend/utils.ts", res["changed_files"])

    def test_repair_task_missing_failure_evidence_rejected(self):
        diff = (
            "--- a/frontend/utils.ts\n"
            "+++ b/frontend/utils.ts\n"
            "@@ -10,1 +10,1 @@\n"
            "-a\n+b\n"
        )
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="Fix bug",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=True,
                developer_diff=diff,
                local_evidence=None,
            )
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="Fix bug",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=True,
                developer_diff=diff,
                local_evidence={"exit_code": 0, "failure_output": "All 5 tests passed"},
            )

    def test_repair_task_out_of_scope_diff_rejected(self):
        diff = (
            "--- a/backend/secret.py\n"
            "+++ b/backend/secret.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-x\n+y\n"
        )
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="Edit backend",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=True,
                developer_diff=diff,
                local_evidence={"exit_code": 1, "failure_output": "fail"},
            )

    def test_path_traversal_in_diff_rejected(self):
        diff = (
            "--- a/frontend/../../../etc/passwd\n"
            "+++ b/frontend/../../../etc/passwd\n"
            "@@ -1,1 +1,1 @@\n"
            "-root\n+evil\n"
        )
        with self.assertRaises(ContributionGateError):
            ContributionGate.validate(
                developer=self.dev,
                task="Escape",
                task_type="code",
                branch="feature/nav",
                base_commit="abc1234",
                is_repair=True,
                developer_diff=diff,
                local_evidence={"exit_code": 1, "failure_output": "fail"},
            )


class TestJobOwnership(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = RecordStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_developer_id_persisted(self):
        jid = str(uuid.uuid4())
        record = {
            "job_id": jid,
            "developer_id": "dev-001",
            "repository": "NEC-08240/Synora",
            "branch": "feature/my-branch",
            "task": "test",
            "status": "QUEUED",
        }
        self.store.write_new(record)
        read = self.store.read(jid)
        self.assertEqual(read["developer_id"], "dev-001")
        self.assertEqual(read["repository"], "NEC-08240/Synora")
        self.assertEqual(read["branch"], "feature/my-branch")

    def test_developer_id_is_immutable(self):
        jid = str(uuid.uuid4())
        record = {
            "job_id": jid,
            "developer_id": "dev-001",
            "repository": "NEC-08240/Synora",
            "branch": "feature/my-branch",
            "task": "test",
            "status": "QUEUED",
        }
        self.store.write_new(record)
        with self.assertRaises(ValueError):
            self.store.update(jid, lambda r: {"developer_id": "dev-hacker"})


class TestPersistentQueue(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test_queue.db")
        self.queue = JobQueue(db_path=self.db_path, max_depth=10)

    def tearDown(self):
        self.queue.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_enqueue_and_claim(self):
        job = {
            "job_id": "job-001",
            "developer_id": "dev-001",
            "task": "Implement component",
            "task_type": "code",
            "branch": "feature/comp",
        }
        self.queue.enqueue(job)
        claimed = self.queue.claim_next("worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["job_id"], "job-001")
        self.assertIn(claimed["status"], ("ASSIGNED", "RUNNING"))

        second = self.queue.claim_next("worker-2")
        self.assertIsNone(second)

    def test_persistence_across_instances(self):
        job = {
            "job_id": "job-persist",
            "developer_id": "dev-001",
            "task": "Persist test",
            "task_type": "docs",
            "branch": "feature/docs",
        }
        self.queue.enqueue(job)
        self.queue.close()

        new_queue = JobQueue(db_path=self.db_path)
        try:
            persisted = new_queue.get_job("job-persist")
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["developer_id"], "dev-001")
            self.assertEqual(persisted["status"], "QUEUED")
        finally:
            new_queue.close()

    def test_fair_scheduling_across_developers(self):
        for i in range(3):
            self.queue.enqueue({
                "job_id": f"dev1-job-{i}",
                "developer_id": "dev-001",
                "task": f"Task {i}",
                "task_type": "code",
                "branch": "feature/test",
            })
        self.queue.enqueue({
            "job_id": "dev2-job-0",
            "developer_id": "dev-002",
            "task": "Dev2 Task",
            "task_type": "code",
            "branch": "feature/test",
        })

        c1 = self.queue.claim_next("worker-1")
        self.assertIsNotNone(c1)
        c2 = self.queue.claim_next("worker-2")
        self.assertIsNotNone(c2)
        claimed_devs = {c1["developer_id"], c2["developer_id"]}
        self.assertIn("dev-001", claimed_devs)
        self.assertIn("dev-002", claimed_devs)

    def test_queue_depth_bounding(self):
        for i in range(10):
            self.queue.enqueue({
                "job_id": f"job-limit-{i}",
                "developer_id": "dev-001",
                "task": f"Task {i}",
                "task_type": "docs",
                "branch": "feature/test",
            })
        with self.assertRaises(ValueError):
            self.queue.enqueue({
                "job_id": "job-overflow",
                "developer_id": "dev-001",
                "task": "Overflow Task",
                "task_type": "docs",
                "branch": "feature/test",
            })

    def test_worker_heartbeat_and_stale_reap(self):
        self.queue.heartbeat_worker("worker-slow")
        job = {
            "job_id": "job-slow",
            "developer_id": "dev-001",
            "task": "Slow Task",
            "task_type": "code",
            "branch": "feature/test",
        }
        self.queue.enqueue(job)
        self.queue.claim_next("worker-slow")

        reaped = self.queue.reap_stale_workers(timeout_seconds=0.0)
        self.assertIn("worker-slow", reaped)
        reset_job = self.queue.get_job("job-slow")
        self.assertEqual(reset_job["status"], "QUEUED")


class TestProtocol(unittest.TestCase):
    def test_valid_envelope_roundtrip(self):
        msg = ProtocolMessage(
            message_type=MSG_AUTHENTICATE,
            sender_id="dev-001",
            payload={"developer_id": "dev-001", "nonce": "12345", "signature": "base64sig"},
        )
        serialized = msg.serialize()
        parsed = ProtocolMessage.parse(serialized)
        self.assertEqual(parsed.message_type, MSG_AUTHENTICATE)
        self.assertEqual(parsed.sender_id, "dev-001")
        self.assertEqual(parsed.payload["nonce"], "12345")

    def test_unknown_message_type_rejected(self):
        with self.assertRaises(ProtocolError):
            ProtocolMessage(
                message_type="EXPLODE_SERVER",
                sender_id="dev-001",
                payload={},
            )

    def test_missing_required_fields_rejected(self):
        with self.assertRaises(ProtocolError):
            ProtocolMessage(
                message_type=MSG_AUTHENTICATE,
                sender_id="dev-001",
                payload={"nonce": "12345"},
            )

    def test_malformed_json_rejected(self):
        with self.assertRaises(ProtocolError):
            ProtocolMessage.parse("invalid json string")


class TestAuditLogger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "audit.jsonl"
        self.audit = AuditLogger(log_path=self.log_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scrub_sensitive_information(self):
        sensitive_data = {
            "developer_id": "dev-001",
            "private_key": "SUPER_SECRET_KEY",
            "token": "SECRET_TOKEN",
            "signature": "SECRET_SIG",
            "password": "SECRET_PASS",
            "nested": {
                "authorization": "Bearer 1234",
                "safe_field": "public_info",
            },
        }
        scrubbed = scrub_sensitive(sensitive_data)
        self.assertEqual(scrubbed["developer_id"], "dev-001")
        self.assertEqual(scrubbed["private_key"], "[REDACTED]")
        self.assertEqual(scrubbed["token"], "[REDACTED]")
        self.assertEqual(scrubbed["signature"], "[REDACTED]")
        self.assertEqual(scrubbed["password"], "[REDACTED]")
        self.assertEqual(scrubbed["nested"]["authorization"], "[REDACTED]")
        self.assertEqual(scrubbed["nested"]["safe_field"], "public_info")

    def test_audit_event_written_and_queried(self):
        self.audit.record("TEST_EVENT", "dev-001", {"info": "hello", "secret": "123"})
        events = self.audit.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "TEST_EVENT")
        self.assertEqual(events[0]["details"]["secret"], "[REDACTED]")

        self.assertTrue(self.log_path.exists())
        content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("TEST_EVENT", content)
        self.assertNotIn("123", content)


class TestEndToEndGatewayAndWorker(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "gateway.db")
        self.audit_path = Path(self.tmpdir) / "audit.jsonl"
        self.queue = JobQueue(db_path=self.db_path)
        self.audit = AuditLogger(log_path=self.audit_path)

        self.pub_dev, self.priv_dev = generate_keypair()
        self.dev = DeveloperEntry(
            developer_id="dev-001",
            developer_name="Developer One",
            github_username="dev1",
            role="developer",
            status="active",
            public_key_b64=self.pub_dev,
            assigned_modules=("docs/",),
            allowed_branches=("feature/*",),
        )
        self.registry = TeamRegistry([self.dev])
        self.gateway = Gateway(registry=self.registry, queue=self.queue, audit=self.audit)

    def tearDown(self):
        self.queue.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_simulated_workflow(self):
        # 1. Challenge Request
        challenge = self.gateway.request_challenge("dev-001")
        self.assertIn("nonce", challenge)

        # 2. Sign Challenge and Authenticate
        sig = sign_message(self.priv_dev, challenge["message"])
        token = self.gateway.authenticate("dev-001", challenge["nonce"], sig)
        self.assertIsInstance(token, str)

        # 3. Submit Task via Gateway
        job_payload = {
            "task": "Document Phase C Step 3 foundation",
            "task_type": "docs",
            "branch": "feature/step3-docs",
            "base_commit": "abc1234",
            "is_repair": False,
        }
        submit_res = self.gateway.submit_job(token, job_payload)
        self.assertTrue(submit_res["success"])
        job_id = submit_res["job_id"]

        # 4. Worker Polls and Claims Job
        worker_id = "johan-local-worker-1"
        self.gateway.register_worker(worker_id, "worker-token", {"tasks": ["docs", "code"]})
        claimed_job = self.gateway.worker_poll_job(worker_id)
        self.assertIsNotNone(claimed_job)
        self.assertEqual(claimed_job["job_id"], job_id)
        self.assertEqual(claimed_job["developer_id"], "dev-001")

        # 5. Worker Submits Result
        mock_result = {
            "status": "SUCCEEDED",
            "changed_files": ["docs/agent-bridge/test.md"],
            "diff": "+ verified",
            "claude_result": "Successfully created documentation.",
            "verification": {"status": "PASSED"},
            "review": {"verdict": "PASS"},
        }
        self.gateway.worker_submit_result(worker_id, job_id, mock_result)

        # 6. Developer Polls Status and Result
        status_res = self.gateway.get_status(token, job_id)
        self.assertEqual(status_res["status"], "SUCCEEDED")

        result_res = self.gateway.get_result(token, job_id)
        self.assertEqual(result_res["status"], "SUCCEEDED")
        self.assertEqual(result_res["claude_result"], "Successfully created documentation.")
        self.assertEqual(result_res["developer_id"], "dev-001")

        # 7. Audit log contains all steps without leaked secrets
        events = [e["event_type"] for e in self.audit.events()]
        self.assertIn("AUTH_CHALLENGE_ISSUED", events)
        self.assertIn("AUTH_SUCCESS", events)
        self.assertIn("GATE_PASS", events)
        self.assertIn("JOB_ENQUEUED", events)
        self.assertIn("JOB_CLAIMED", events)
        self.assertIn("JOB_COMPLETED", events)


if __name__ == "__main__":
    unittest.main()
