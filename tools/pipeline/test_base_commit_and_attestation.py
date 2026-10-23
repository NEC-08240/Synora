"""Tests for base_commit handling and the Worker's client-verifiable result attestation.

Run: python -m unittest tools.pipeline.test_base_commit_and_attestation -v
Git, worktrees and the Worker run for real; only the Claude process is replaced by FakeClaude.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from .bridge import Bridge
from .result_envelope import AttestationError, verify_result_response
from .test_bridge import FakeClaude
from .worker import ClaudeWorker


class FakeGateway:
    """Hands the Worker one job and keeps what the Worker sends back."""

    def __init__(self, job):
        self.jobs = [job]
        self.envelopes = []
        self.failures = []

    def worker_poll_job(self, worker_id):
        return self.jobs.pop(0) if self.jobs else None

    def worker_submit_signed_result(self, envelope):
        self.envelopes.append(envelope)
        return {"success": True}

    def worker_submit_failure(self, worker_id, job_id, error):
        self.failures.append(error)
        return {"success": True}


def _job(base_commit=None, job_id="gw-job-1", developer_id="alice"):
    job = {"job_id": job_id, "developer_id": developer_id, "task": "Write the test section.", "task_type": "docs", "branch": "feature/x"}
    if base_commit is not None:
        job["base_commit"] = base_commit
    return job


class RepoCase(unittest.TestCase):
    """A repo with three commits on main, so older commits exist, plus one commit on a side branch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._git("init", "-q", "-b", "main")
        (self.repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        self.first = self._commit("README.md", "one\n")
        self.second = self._commit("second.txt", "two\n")
        self._git("checkout", "-q", "-b", "side")
        self.side = self._commit("side.txt", "side\n")
        self._git("checkout", "-q", "main")
        self.head = self._commit("third.txt", "three\n")
        self.key = ed25519.Ed25519PrivateKey.generate()

    def tearDown(self):
        self._tmp.cleanup()

    def _git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

    def _commit(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", name)
        return self._git("rev-parse", "HEAD")

    def _run(self, job):
        claude = FakeClaude(write="docs/agent-bridge/test.md")
        gateway = FakeGateway(job)
        worker = ClaudeWorker("worker-test", bridge=Bridge(repo_root=self.repo, runner=claude), gateway=gateway, private_key=self.key)
        worker.process_one_job()
        return gateway, claude


class BaseCommitTest(RepoCase):
    def test_a_requested_older_commit_is_the_commit_the_worktree_starts_from(self):
        gateway, claude = self._run(_job(self.first))

        result = gateway.envelopes[0]["result"]
        self.assertEqual(result["base_commit"], self.first)
        seen = claude.calls[0]["seen_files"]
        self.assertIn("README.md", seen)
        self.assertNotIn("second.txt", seen)
        self.assertNotIn("third.txt", seen)

    def test_an_abbreviated_hash_resolves_to_the_full_commit(self):
        gateway, _ = self._run(_job(self.second[:9]))

        self.assertEqual(gateway.envelopes[0]["result"]["base_commit"], self.second)

    def test_without_a_base_commit_the_worktree_starts_from_head(self):
        gateway, claude = self._run(_job())

        self.assertEqual(gateway.envelopes[0]["result"]["base_commit"], self.head)
        self.assertIn("third.txt", claude.calls[0]["seen_files"])

    def test_a_valid_looking_but_unknown_commit_is_refused_before_any_work(self):
        gateway, claude = self._run(_job("abc1234"))

        self.assertEqual(claude.calls, [])
        self.assertEqual(gateway.envelopes, [])
        self.assertEqual(len(gateway.failures), 1)
        self.assertIn("Refused", gateway.failures[0])
        self.assertIn("base_commit", gateway.failures[0])

    def test_a_commit_that_is_not_in_the_current_history_is_refused(self):
        gateway, claude = self._run(_job(self.side))

        self.assertEqual(claude.calls, [])
        self.assertIn("current history", gateway.failures[0])

    def test_values_git_could_read_as_options_or_refs_are_refused(self):
        for hostile in ("--output=/tmp/x", "main", "HEAD", "../../etc", "abc123", "g" * 40, "a" * 41, "abc1234; rm -rf /", 12345):
            with self.subTest(base_commit=hostile):
                gateway, claude = self._run(_job(hostile))
                self.assertEqual(claude.calls, [])
                self.assertEqual(len(gateway.failures), 1)

    def test_no_worktree_is_created_for_a_refused_job(self):
        bridge = Bridge(repo_root=self.repo, runner=FakeClaude())
        with self.assertRaises(ValueError):
            bridge.create("Write the test section.", "docs", base_commit="abc1234")

        self.assertFalse(bridge.worktrees_dir.exists() and any(bridge.worktrees_dir.iterdir()))


class AttestationTest(RepoCase):
    def _response(self, envelope):
        """What the Gateway returns: the stored result, round-tripped through JSON as the database does."""
        return {"job_id": "a-different-local-id", "status": "SUCCEEDED", "result": json.loads(json.dumps(envelope["result"]))}

    def _signed(self):
        gateway, _ = self._run(_job(self.second))
        return gateway.envelopes[0]

    def test_a_genuine_result_verifies_and_the_verified_content_is_returned(self):
        envelope = self._signed()

        verified = verify_result_response(self._response(envelope), self.key.public_key(), "gw-job-1", "alice")

        self.assertEqual(verified["changed_files"], ["docs/agent-bridge/test.md"])
        self.assertEqual(verified["base_commit"], self.second)

    def test_changing_any_signed_content_is_detected(self):
        response = self._response(self._signed())
        response["result"]["changed_files"] = ["backend/server.js"]

        with self.assertRaises(AttestationError):
            verify_result_response(response, self.key.public_key(), "gw-job-1", "alice")

    def test_a_result_signed_by_a_different_key_is_rejected(self):
        response = self._response(self._signed())

        with self.assertRaises(AttestationError):
            verify_result_response(response, ed25519.Ed25519PrivateKey.generate().public_key(), "gw-job-1", "alice")

    def test_a_result_cannot_be_presented_for_another_job_or_developer(self):
        response = self._response(self._signed())

        with self.assertRaises(AttestationError):
            verify_result_response(response, self.key.public_key(), "gw-job-2", "alice")
        with self.assertRaises(AttestationError):
            verify_result_response(response, self.key.public_key(), "gw-job-1", "bob")

    def test_a_result_without_an_attestation_is_rejected(self):
        response = self._response(self._signed())
        del response["result"]["attestation"]

        with self.assertRaises(AttestationError):
            verify_result_response(response, self.key.public_key(), "gw-job-1", "alice")

    def test_an_attestation_copied_onto_different_content_is_rejected(self):
        first = self._response(self._signed())
        other, _ = self._run(_job(self.first, job_id="gw-job-9"))
        forged = self._response(other.envelopes[0])
        forged["result"]["attestation"] = first["result"]["attestation"]

        with self.assertRaises(AttestationError):
            verify_result_response(forged, self.key.public_key(), "gw-job-9", "alice")

    def test_malformed_responses_fail_closed(self):
        key = self.key.public_key()
        for response in ({}, {"result": None}, {"result": "text"}, {"result": {"attestation": "x"}}, {"result": {"attestation": {}}}, None):
            with self.subTest(response=response):
                with self.assertRaises(AttestationError):
                    verify_result_response(response, key, "gw-job-1", "alice")

    def test_the_gateways_own_envelope_check_still_passes_with_the_attestation_inside(self):
        from .result_envelope import ResultEnvelope

        envelope = self._signed()

        ResultEnvelope.verify(envelope, self.key.public_key(), expected_job_id="gw-job-1", expected_developer_id="alice", expected_worker_id="worker-test")


if __name__ == "__main__":
    unittest.main()
