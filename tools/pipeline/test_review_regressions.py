"""Regression tests for the findings in the independent review of the F2 to F6 remediation.

Run: python -m unittest tools.pipeline.test_review_regressions -v

N1 redirect downgrade, N2 admission slot wedge, N3 verification environment, N4 nested redaction,
N5 daily cost cap, and the leading-character rule for identifiers. Each test targets one finding.
"""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import websocket

from . import worker as worker_module
from .bridge import Bridge, IMPLEMENT_TOOLS
from .budget import BudgetExceeded, WorkerBudget
from .metadata import validate_branch, validate_developer_id, validate_repository
from .audit import redact_secret_values
from .protocol import MSG_JOB_ACK, MSG_JOB_ASSIGN
from .worker import OutboundWorker, sanitize_worker_result


class _Recorder(BaseHTTPRequestHandler):
    hits = []
    redirect_to = None

    def do_GET(self):
        type(self).hits.append(self.path)
        if type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


def _serve(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class RedirectDowngradeTest(unittest.TestCase):
    """N1: a Gateway redirect must not move the Worker to another address."""

    def setUp(self):
        self.target = type("Target", (_Recorder,), {"hits": [], "redirect_to": None})
        self.target_server = _serve(self.target)
        target_url = f"ws://127.0.0.1:{self.target_server.server_address[1]}/attacker"
        self.gateway = type("Gateway", (_Recorder,), {"hits": [], "redirect_to": target_url})
        self.gateway_server = _serve(self.gateway)
        self.gateway_url = f"ws://127.0.0.1:{self.gateway_server.server_address[1]}"

    def tearDown(self):
        self.gateway_server.shutdown()
        self.gateway_server.server_close()
        self.target_server.shutdown()
        self.target_server.server_close()

    def test_without_the_limit_a_redirect_reaches_the_other_address(self):
        with self.assertRaises(Exception):
            websocket.create_connection(self.gateway_url + "/ws/worker", timeout=5)
        self.assertTrue(self.target.hits, "control: the default library behaviour follows the redirect")

    def test_worker_connection_refuses_to_follow_a_redirect(self):
        with self.assertRaises(Exception):
            worker = OutboundWorker(worker_id="worker-test", gateway_url=self.gateway_url, allow_insecure_lan=True)
            worker.connect_ws()
        self.assertEqual(self.target.hits, [], "the redirect target must receive no request")

    def test_connect_passes_redirect_limit_zero(self):
        worker = OutboundWorker(worker_id="worker-test", gateway_url="wss://gw.example", private_key=None)
        with mock.patch.object(websocket, "create_connection", side_effect=ConnectionError("stop")) as spy:
            with self.assertRaises(Exception):
                worker.connect_ws()

        self.assertEqual(spy.call_args.kwargs.get("redirect_limit"), 0)


class _ScriptedSocket:
    """A fake Gateway socket: returns scripted messages, and can fail on a chosen message type."""

    def __init__(self, inbound, fail_on=None):
        self.inbound = list(inbound)
        self.fail_on = fail_on
        self.sent = []

    def send(self, raw):
        message = json.loads(raw)
        if message.get("message_type") == self.fail_on:
            raise ConnectionError("simulated socket failure")
        self.sent.append(message)

    def recv(self):
        return json.dumps(self.inbound.pop(0))


def _assign(job):
    return {"message_type": MSG_JOB_ASSIGN, "payload": job}


class AdmissionSlotTest(unittest.TestCase):
    """N2: a single Gateway message must never leave the Worker permanently refusing jobs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.bridge = Bridge(repo_root=self.repo, runner=lambda *a, **k: (0, "{}", ""))
        self.budget = WorkerBudget(self.bridge.records_dir.parent, jobs_per_window=100, jobs_per_day=100)

    def tearDown(self):
        self._tmp.cleanup()

    def _worker(self, socket):
        worker = OutboundWorker(worker_id="worker-test", gateway_url="wss://gw.example", bridge=self.bridge,
                                budget=self.budget, private_key=None)
        worker._ws = socket
        worker._is_connected = True
        return worker

    def _slot_is_free(self):
        try:
            self.budget.admit()
        except BudgetExceeded:
            return False
        self.budget.finish()
        return True

    def test_job_without_a_task_releases_the_slot(self):
        job = {"job_id": "job-x", "developer_id": "alice", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]}}
        worker = self._worker(_ScriptedSocket([_assign(job), {"message_type": "JOB_FAILURE_ACK"}]))

        self.assertIsNone(worker.poll_and_execute_one_job())
        self.assertTrue(self._slot_is_free(), "a refused job must not hold the slot")

    def test_socket_failure_on_the_ack_releases_the_slot(self):
        job = {"job_id": "job-y", "developer_id": "alice", "task": "Write docs.", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]}}
        worker = self._worker(_ScriptedSocket([_assign(job), {"message_type": "JOB_FAILURE_ACK"}], fail_on=MSG_JOB_ACK))

        with self.assertRaises(ConnectionError):
            worker.poll_and_execute_one_job()
        self.assertTrue(self._slot_is_free(), "a socket failure must not wedge the Worker")

    def test_task_type_outside_the_allowed_set_is_refused_before_admission(self):
        job = {"job_id": "job-z", "developer_id": "alice", "task": "x", "task_type": "bugfix"}
        worker = self._worker(_ScriptedSocket([_assign(job), {"message_type": "JOB_FAILURE_ACK"}]))

        self.assertIsNone(worker.poll_and_execute_one_job())
        self.assertTrue(self._slot_is_free())


class VerificationEnvironmentTest(unittest.TestCase):
    """N3: verification commands must not see the Worker's secrets."""

    def test_verification_command_does_not_inherit_worker_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "README.md").write_text("r\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "i"], cwd=repo, check=True)
            dump = Path(tmp) / "verify_env.txt"
            command = [sys.executable, "-c", "import os,sys; open(sys.argv[1],'w').write(repr(sorted(os.environ)))", str(dump)]

            def runner(prompt, cwd, tools, permission_mode):
                (Path(cwd) / "docs" / "agent-bridge").mkdir(parents=True, exist_ok=True)
                (Path(cwd) / "docs" / "agent-bridge" / "x.md").write_text("x\n", encoding="utf-8")
                return 0, '{"subtype": "success", "is_error": false, "result": "ok"}', ""

            bridge = Bridge(repo_root=repo, runner=runner, verify_commands={"docs": [command]})
            secrets = {"SYNORA_TEST_SECRET_004": "TEST_SECRET_004_VALUE", "SYNORA_WORKER_PRIVATE_KEY_B64": "TEST_KEY"}
            with mock.patch.dict("os.environ", secrets):
                job_id = bridge.create("Write docs.", "docs")["job_id"]
                bridge.execute(job_id)

            seen = dump.read_text(encoding="utf-8")
            self.assertNotIn("SYNORA_TEST_SECRET_004", seen)
            self.assertNotIn("SYNORA_WORKER_PRIVATE_KEY_B64", seen)
            self.assertIn("'PATH'", seen)


class NestedRedactionTest(unittest.TestCase):
    """N4: secrets in nested result fields are redacted, not only top-level ones."""

    def test_nested_verification_output_and_review_findings_are_redacted(self):
        token = "ghp_" + "a" * 36
        result = {
            "claude_result": "ok",
            "verification": {"commands": [{"output_tail": f"leaked {token}"}]},
            "review": {"findings": [{"detail": f"also {token}"}]},
            "task": f"write {token}",
        }
        cleaned = sanitize_worker_result(result)

        self.assertNotIn(token, json.dumps(cleaned))
        self.assertIn("[REDACTED_SECRET]", cleaned["verification"]["commands"][0]["output_tail"])
        self.assertIn("[REDACTED_SECRET]", cleaned["review"]["findings"][0]["detail"])

    def test_deep_nesting_is_bounded(self):
        value = {"x": "y"}
        for _ in range(60):
            value = {"n": value}
        self.assertIn("REDACTED_DEPTH_LIMIT", json.dumps(sanitize_worker_result(value)))


class DailyCapTest(unittest.TestCase):
    """N5: a Gateway cannot exceed the daily job count even when the hourly limit is generous."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = [5000.0]

    def tearDown(self):
        self._tmp.cleanup()

    def test_daily_limit_refuses_and_then_recovers(self):
        budget = WorkerBudget(Path(self._tmp.name), jobs_per_window=100, jobs_per_day=2, clock=lambda: self.clock[0])
        for _ in range(2):
            budget.admit()
            budget.finish()
        with self.assertRaises(BudgetExceeded) as caught:
            budget.admit()
        self.assertIn("Daily", str(caught.exception))

        self.clock[0] += 86401
        budget.admit()
        budget.finish()


class IdentifierLeadingCharacterTest(unittest.TestCase):
    """L1: no identifier may start with a dash or dot, so none can read as a Git option."""

    def test_leading_dash_or_dot_is_refused_everywhere(self):
        for bad in ("-alice", "-x", "feature/-b", ".hidden", "./x"):
            with self.subTest(value=bad):
                for check in (validate_developer_id, validate_branch):
                    with self.assertRaises(ValueError):
                        check(bad)
        for bad in ("-x/y", "./x", "x/-y", ".x/y"):
            with self.subTest(repository=bad), self.assertRaises(ValueError):
                validate_repository(bad)

    def test_ordinary_identifiers_still_work(self):
        self.assertEqual(validate_developer_id("alice-01"), "alice-01")
        self.assertEqual(validate_branch("feature/fe-a"), "feature/fe-a")
        self.assertEqual(validate_repository("NEC-08240/Synora"), "NEC-08240/Synora")


class ReReviewFixesTest(unittest.TestCase):
    """Fixes for the re-verification findings: git environment, spend cap, release path, redaction paths."""

    def test_git_calls_do_not_inherit_worker_secrets(self):
        from . import bridge as bridge_module
        real_run = subprocess.run
        seen = []

        def spy(*args, **kwargs):
            seen.append(kwargs.get("env"))
            return real_run(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"SYNORA_WORKER_PRIVATE_KEY_B64": "CANARY_KEY"}):
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            with mock.patch.object(bridge_module.subprocess, "run", side_effect=spy):
                Bridge(repo_root=repo)._git(["rev-parse", "--git-dir"], repo)

        self.assertTrue(seen and seen[0] is not None, "git must receive an explicit environment")
        self.assertNotIn("SYNORA_WORKER_PRIVATE_KEY_B64", seen[0])

    def test_claude_invocation_carries_a_spend_cap(self):
        from . import bridge as bridge_module
        captured = {}

        def spy(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

        with mock.patch.object(bridge_module.subprocess, "run", side_effect=spy):
            bridge_module.run_claude("p", ".", "Read", "dontAsk", "claude")

        self.assertIn("--max-budget-usd", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--max-budget-usd") + 1], bridge_module.CLAUDE_MAX_BUDGET_USD)

    def test_budget_slot_is_released_even_while_the_lock_is_held_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = WorkerBudget(Path(tmp), jobs_per_window=5, jobs_per_day=5)
            budget.admit()
            budget._lock.acquire()
            try:
                budget.finish()
            finally:
                budget._lock.release()
            self.assertFalse(budget._running)

    def test_pem_private_key_body_is_redacted(self):
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----" + chr(10) + "SYNORA_TEST_KEY_BODY_LINE" + chr(10) + "-----END OPENSSH PRIVATE KEY-----"
        cleaned = redact_secret_values(pem)
        self.assertNotIn("SYNORA_TEST_KEY_BODY_LINE", cleaned)
        self.assertNotIn("BEGIN OPENSSH", cleaned)

    def test_secret_used_as_a_dict_key_is_redacted(self):
        token = "ghp_" + "k" * 36
        cleaned = sanitize_worker_result({token: "value"})
        self.assertNotIn(token, json.dumps(cleaned))

    def test_failure_text_sent_to_the_gateway_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(repo_root=Path(tmp), runner=lambda *a, **k: (0, "{}", ""))
            budget = WorkerBudget(bridge.records_dir.parent, jobs_per_window=100, jobs_per_day=100)
            socket = _ScriptedSocket([
                _assign({"job_id": "job-q", "developer_id": "alice", "task": "Write docs.", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]}}),
                {"message_type": "JOB_FAILURE_ACK"},
            ])
            worker = OutboundWorker(worker_id="worker-test", gateway_url="wss://gw.example", bridge=bridge, budget=budget, private_key=None)
            worker._ws = socket
            worker._is_connected = True
            secret = "sk-ant-api03-" + "Q" * 40
            with mock.patch.object(bridge, "create", side_effect=RuntimeError("boom " + secret)):
                with self.assertRaises(RuntimeError):
                    worker.poll_and_execute_one_job()

        failures = [m for m in socket.sent if m.get("message_type") == "JOB_FAILURE"]
        self.assertTrue(failures)
        self.assertNotIn(secret, json.dumps(failures))


if __name__ == "__main__":
    unittest.main()
