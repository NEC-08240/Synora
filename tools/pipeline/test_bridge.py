"""Tests for the Synora agent bridge. Run: python -m unittest tools.pipeline.test_bridge -v

Only the Claude process is replaced by FakeClaude. Git, worktrees, verification commands,
and the job lifecycle all run for real.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from . import bridge as bridge_module
from . import server as server_module
from .bridge import IMPLEMENT_TOOLS, REVIEW_TOOLS, Bridge

PY = sys.executable
PASSING_COMMAND = [PY, "-c", "pass"]
FAILING_COMMAND = [PY, "-c", "import sys; sys.exit(3)"]
PASS_VERDICT = '{"verdict": "PASS", "findings": []}'


class FakeClaude:
    """Stands in for the Claude process. Records each call so tests can check tools and permissions."""

    def __init__(self, write=None, text="ok", verdict=PASS_VERDICT, review_write=None, returncode=0, subtype="success"):
        self.write = write
        self.text = text
        self.verdict = verdict
        self.review_write = review_write
        self.returncode = returncode
        self.subtype = subtype
        self.calls = []

    def __call__(self, prompt, cwd, tools, permission_mode):
        seen = sorted(
            p.relative_to(cwd).as_posix() for p in Path(cwd).rglob("*")
            if p.is_file() and ".git" not in p.relative_to(cwd).parts
        )
        self.calls.append({"tools": tools, "permission_mode": permission_mode, "seen_files": seen})
        result = self.text
        if tools == REVIEW_TOOLS:
            if self.review_write:
                _write(Path(cwd), self.review_write)
            result = self.verdict
        elif self.write:
            _write(Path(cwd), self.write)
        payload = {"subtype": self.subtype, "is_error": self.subtype != "success", "result": result}
        return self.returncode, json.dumps(payload), ""


def _write(root, relative_path, text="# written\n"):
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._git("init", "-q")
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        self._git("add", "README.md", ".gitignore")
        self._git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def _bridge(self, claude, verify=None):
        return Bridge(repo_root=self.repo, runner=claude, verify_commands=verify or {})

    def _run(self, bridge, task, task_type="docs", working_dir=".", target_job_id=None):
        job_id = bridge.create(task, task_type, working_dir, target_job_id)["job_id"]
        bridge.execute(job_id)
        return bridge.get(job_id)

    # ---- docs tasks -------------------------------------------------------

    def test_docs_change_succeeds_and_is_recorded(self):
        claude = FakeClaude(write="docs/agent-bridge/test.md")
        record = self._run(self._bridge(claude), "Write the test section.")

        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["changed_files"], ["docs/agent-bridge/test.md"])
        self.assertIn("# written", record["diff"])
        self.assertEqual(record["verification"]["status"], "SCOPE_ONLY")
        self.assertEqual(record["review"]["verdict"], "PASS")
        self.assertEqual(record["claude_result"], "ok")

    def test_docs_change_outside_allowed_folder_fails(self):
        record = self._run(self._bridge(FakeClaude(write="src/main.c")), "Write code.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("Scope violation", record["error"])

    def test_docs_without_file_change_fails(self):
        record = self._run(self._bridge(FakeClaude()), "Say hello.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("no file changes", record["error"])

    def test_claude_failure_fails_the_job(self):
        claude = FakeClaude(write="docs/agent-bridge/x.md", returncode=1, subtype="error_max_turns")
        record = self._run(self._bridge(claude), "Write it.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("Claude execution failed", record["error"])

    # ---- code tasks -------------------------------------------------------

    def test_code_without_configured_verification_fails(self):
        record = self._run(self._bridge(FakeClaude(write="frontend/app.js")), "Add a button.", "code")

        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["verification"]["status"], "NOT_CONFIGURED")
        self.assertIn("No verification commands", record["error"])

    def test_code_with_passing_verification_and_review_succeeds(self):
        claude = FakeClaude(write="frontend/app.js")
        verify = {"code": [PASSING_COMMAND]}
        record = self._run(self._bridge(claude, verify), "Add a button.", "code")

        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["verification"]["status"], "PASSED")
        self.assertEqual(record["verification"]["commands"][0]["exit_code"], 0)
        self.assertEqual(record["review"]["verdict"], "PASS")

    def test_failing_verification_fails_and_skips_review(self):
        claude = FakeClaude(write="frontend/app.js")
        record = self._run(self._bridge(claude, {"code": [FAILING_COMMAND]}), "Add a button.", "code")

        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["verification"]["status"], "FAILED")
        self.assertEqual(record["verification"]["commands"][0]["exit_code"], 3)
        self.assertIsNone(record["review"])
        self.assertEqual(len(claude.calls), 1)  # implementer only; the reviewer never ran

    # ---- reviewer ---------------------------------------------------------

    def test_reviewer_requesting_changes_gives_changes_required(self):
        verdict = '{"verdict": "CHANGES_REQUIRED", "findings": [{"severity": "WARNING", "file": "docs/agent-bridge/x.md", "detail": "typo"}]}'
        record = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md", verdict=verdict)), "Write it.")

        self.assertEqual(record["status"], "CHANGES_REQUIRED")
        self.assertEqual(record["review"]["verdict"], "CHANGES_REQUIRED")
        self.assertEqual(record["review"]["findings"][0]["detail"], "typo")

    def test_reviewer_without_valid_verdict_fails(self):
        record = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md", verdict="looks fine")), "Write it.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("no valid verdict", record["error"])

    def test_reviewer_that_changes_the_worktree_fails(self):
        claude = FakeClaude(write="docs/agent-bridge/x.md", review_write="docs/agent-bridge/extra.md")
        record = self._run(self._bridge(claude), "Write it.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("Reviewer changed the worktree", record["error"])

    def test_implementer_and_reviewer_get_different_tools(self):
        claude = FakeClaude(write="docs/agent-bridge/x.md")
        self._run(self._bridge(claude), "Write it.")

        self.assertEqual((claude.calls[0]["tools"], claude.calls[0]["permission_mode"]), (IMPLEMENT_TOOLS, "acceptEdits"))
        self.assertEqual((claude.calls[1]["tools"], claude.calls[1]["permission_mode"]), (REVIEW_TOOLS, "dontAsk"))

    # ---- review tasks -----------------------------------------------------

    def test_review_task_reviews_a_finished_job_without_writing(self):
        bridge = self._bridge(FakeClaude(write="docs/agent-bridge/x.md"))
        target = self._run(bridge, "Write it.")
        claude = FakeClaude()
        review = self._run(self._bridge(claude), "Review the change.", "review", target_job_id=target["job_id"])

        self.assertEqual(review["status"], "SUCCEEDED")
        self.assertEqual(review["review"]["verdict"], "PASS")
        self.assertEqual(review["changed_files"], [])
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(claude.calls[0]["tools"], REVIEW_TOOLS)
        self.assertEqual(claude.calls[0]["permission_mode"], "dontAsk")

    def test_review_task_sees_the_candidate_change(self):
        target = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md")), "Write it.")
        claude = FakeClaude()
        self._run(self._bridge(claude), "Review it.", "review", target_job_id=target["job_id"])

        self.assertIn("docs/agent-bridge/x.md", claude.calls[0]["seen_files"])
        self.assertEqual(self._git("status", "--porcelain").strip(), "")

    def test_review_of_a_truncated_diff_fails_closed(self):
        target = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md")), "Write it.")
        with mock.patch.object(bridge_module, "MAX_DIFF_CHARS", 5):
            truncated = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/y.md")), "Write it.")
            review = self._run(self._bridge(FakeClaude()), "Review it.", "review", target_job_id=truncated["job_id"])

        self.assertTrue(truncated["diff_truncated"])
        self.assertEqual(review["status"], "FAILED")
        self.assertIn("too large to review", review["error"])
        self.assertFalse(target["diff_truncated"])

    def test_review_task_needs_a_finished_target(self):
        bridge = self._bridge(FakeClaude())
        with self.assertRaises(ValueError):
            bridge.create("Review.", "review")
        with self.assertRaises(ValueError):
            bridge.create("Review.", "review", target_job_id="00000000-0000-4000-8000-000000000000")
        queued = bridge.create("Write it.", "docs")
        with self.assertRaises(ValueError):
            bridge.create("Review.", "review", target_job_id=queued["job_id"])

    def test_target_is_rejected_for_non_review_tasks(self):
        bridge = self._bridge(FakeClaude())
        with self.assertRaises(ValueError):
            bridge.create("Write it.", "docs", target_job_id="00000000-0000-4000-8000-000000000000")

    # ---- validation -------------------------------------------------------

    def test_invalid_task_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self._bridge(FakeClaude()).create("task", "bugfix")

    def test_bad_job_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self._bridge(FakeClaude()).get("../../etc/passwd")

    def test_working_dir_escape_is_rejected(self):
        bridge = self._bridge(FakeClaude())
        for escape in ("..", "../outside", str(self.repo)):
            with self.subTest(working_dir=escape), self.assertRaises(ValueError):
                bridge.create("task", "docs", escape)

    def test_empty_and_oversized_tasks_are_rejected(self):
        bridge = self._bridge(FakeClaude())
        with self.assertRaises(ValueError):
            bridge.create("   ", "docs")
        with self.assertRaises(ValueError):
            bridge.create("x" * (bridge_module.MAX_TASK_CHARS + 1), "docs")

    # ---- records, state, cleanup -----------------------------------------

    def test_record_contains_no_environment_values(self):
        os.environ["SYNORA_BRIDGE_TEST_SECRET"] = "s3cr3t-value-xyz"
        try:
            bridge = self._bridge(FakeClaude(write="docs/agent-bridge/test.md"))
            record = self._run(bridge, "Write it.")
            stored = bridge._record_path(record["job_id"]).read_text(encoding="utf-8")
        finally:
            del os.environ["SYNORA_BRIDGE_TEST_SECRET"]

        self.assertNotIn("s3cr3t-value-xyz", stored)

    def test_worktree_is_removed_and_repo_stays_clean(self):
        bridge = self._bridge(FakeClaude(write="docs/agent-bridge/test.md"))
        record = self._run(bridge, "Write it.")

        self.assertFalse((bridge.worktrees_dir / record["job_id"]).exists())
        self.assertEqual(self._git("status", "--porcelain").strip(), "")
        self.assertEqual(record["cleanup_error"], "")

    def test_cleanup_failure_is_recorded_not_ignored(self):
        real_git = bridge_module._git

        def failing_remove(args, cwd):
            if args[:2] == ["worktree", "remove"]:
                raise RuntimeError("remove blocked")
            return real_git(args, cwd)

        with mock.patch.object(bridge_module, "_git", side_effect=failing_remove):
            record = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/test.md")), "Write it.")

        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertIn("remove blocked", record["cleanup_error"])

    def test_illegal_status_change_is_rejected(self):
        bridge = self._bridge(FakeClaude())
        job_id = bridge.create("Write it.")["job_id"]
        with self.assertRaises(RuntimeError):
            bridge._transition(job_id, "VERIFYING")

    def test_jobs_left_running_are_failed_on_restart(self):
        bridge = self._bridge(FakeClaude())
        job_id = bridge.create("Write it.")["job_id"]
        bridge._transition(job_id, "RUNNING")
        bridge.mark_interrupted()

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("Server restarted", record["error"])

    def test_parallel_jobs_stay_isolated(self):
        bridge = self._bridge(FakeClaude())
        first = bridge.create("Write one.")["job_id"]
        second = bridge.create("Write two.")["job_id"]
        runners = {
            first: FakeClaude(write="docs/agent-bridge/one.md"),
            second: FakeClaude(write="docs/agent-bridge/two.md"),
        }
        workers = []
        for job_id, claude in runners.items():
            worker_bridge = self._bridge(claude)
            workers.append(threading.Thread(target=worker_bridge.execute, args=(job_id,)))
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertEqual(bridge.get(first)["changed_files"], ["docs/agent-bridge/one.md"])
        self.assertEqual(bridge.get(second)["changed_files"], ["docs/agent-bridge/two.md"])
        self.assertEqual(bridge.get(first)["status"], "SUCCEEDED")
        self.assertEqual(bridge.get(second)["status"], "SUCCEEDED")


    # ---- hardening ----------------------------------------------------------

    def test_poc_era_record_can_be_read_and_reviewed(self):
        legacy_id = str(uuid.uuid4())
        legacy_patch = (
            "diff --git a/docs/agent-bridge/legacy.md b/docs/agent-bridge/legacy.md\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/docs/agent-bridge/legacy.md\n"
            "@@ -0,0 +1 @@\n"
            "+legacy line\n"
        )
        legacy = {
            "job_id": legacy_id, "task": "Write it.", "task_type": "docs", "working_dir": ".",
            "status": "SUCCEEDED", "created_at": "2026-10-22T10:00:00+00:00",
            "updated_at": "2026-10-22T10:01:00+00:00", "started_at": None, "finished_at": None,
            "claude_result": "ok", "changed_files": ["docs/agent-bridge/legacy.md"],
            "diff": legacy_patch, "error": "",
        }
        bridge = self._bridge(FakeClaude())
        bridge._save(legacy)
        self.assertEqual(bridge.get(legacy_id)["status"], "SUCCEEDED")

        claude = FakeClaude()
        review = self._run(self._bridge(claude), "Review it.", "review", target_job_id=legacy_id)

        self.assertEqual(review["status"], "SUCCEEDED")
        self.assertIn("docs/agent-bridge/legacy.md", claude.calls[0]["seen_files"])

    def test_status_tool_handles_poc_era_record(self):
        legacy_id = str(uuid.uuid4())
        bridge = self._bridge(FakeClaude())
        bridge._save({"job_id": legacy_id, "task": "t", "task_type": "docs", "status": "SUCCEEDED"})
        original = server_module.bridge
        server_module.bridge = bridge
        try:
            reply = json.loads(server_module.get_status(legacy_id))
        finally:
            server_module.bridge = original

        self.assertEqual(reply["status"], "SUCCEEDED")
        self.assertIsNone(reply["cleanup_error"])

    def test_missing_git_fails_the_job_instead_of_leaving_it_running(self):
        real_git = bridge_module._git

        def broken_status(args, cwd):
            if args[:1] == ["status"]:
                raise FileNotFoundError("git not found")
            return real_git(args, cwd)

        with mock.patch.object(bridge_module, "_git", side_effect=broken_status):
            record = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md")), "Write it.")

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("git not found", record["error"])

    def test_review_runs_against_the_targets_base_commit(self):
        target = self._run(self._bridge(FakeClaude(write="docs/agent-bridge/x.md")), "Write it.")
        self._git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "--allow-empty", "-m", "later")
        claude = FakeClaude()
        review = self._run(self._bridge(claude), "Review it.", "review", target_job_id=target["job_id"])

        self.assertEqual(review["status"], "SUCCEEDED")
        self.assertEqual(review["base_commit"], target["base_commit"])
        self.assertNotEqual(review["base_commit"], self._git("rev-parse", "HEAD").strip())
        self.assertIn("docs/agent-bridge/x.md", claude.calls[0]["seen_files"])

    def test_failure_after_a_final_state_keeps_that_state(self):
        bridge = self._bridge(FakeClaude())
        job_id = bridge.create("Write it.")["job_id"]
        bridge._transition(job_id, "RUNNING")
        bridge.mark_interrupted()
        bridge._fail(job_id, "late error")

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("late error", record["error"])


if __name__ == "__main__":
    unittest.main()
