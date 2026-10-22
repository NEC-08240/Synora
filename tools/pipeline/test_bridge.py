"""Tests for the Synora agent bridge. Run: python -m unittest tools.pipeline.test_bridge -v"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from .bridge import Bridge


def fake_claude(path, text="# Agent Bridge Test\n", returncode=0, subtype="success"):
    """Stand-in for Claude Code: writes one file in the job worktree and returns a JSON result."""

    def runner(prompt, cwd):
        target = Path(cwd) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        payload = {"subtype": subtype, "is_error": subtype != "success", "result": "Wrote the file."}
        return returncode, json.dumps(payload), ""

    return runner


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

    def _run(self, runner, task="Write the test section."):
        bridge = Bridge(repo_root=self.repo, runner=runner)
        job_id = bridge.create(task)["job_id"]
        bridge.execute(job_id)
        return bridge, bridge.get(job_id)

    def test_docs_change_succeeds_and_is_recorded(self):
        _, record = self._run(fake_claude("docs/agent-bridge/test.md"))

        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["changed_files"], ["docs/agent-bridge/test.md"])
        self.assertIn("Agent Bridge Test", record["diff"])
        self.assertEqual(record["claude_result"], "Wrote the file.")

    def test_change_outside_allowed_folder_fails(self):
        _, record = self._run(fake_claude("src/main.c"))

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("Changes outside docs/agent-bridge/", record["error"])

    def test_no_file_change_fails(self):
        _, record = self._run(lambda prompt, cwd: (0, json.dumps({"subtype": "success", "result": "ok"}), ""))

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("no file changes", record["error"])

    def test_claude_error_fails(self):
        _, record = self._run(fake_claude("docs/agent-bridge/test.md", returncode=1, subtype="error_max_turns"))

        self.assertEqual(record["status"], "FAILED")
        self.assertIn("did not finish cleanly", record["error"])

    def test_bad_job_id_is_rejected(self):
        bridge = Bridge(repo_root=self.repo, runner=fake_claude("docs/agent-bridge/x.md"))

        with self.assertRaises(ValueError):
            bridge.get("../../etc/passwd")

    def test_working_dir_escape_is_rejected(self):
        bridge = Bridge(repo_root=self.repo, runner=fake_claude("docs/agent-bridge/x.md"))

        for escape in ("..", "../outside", str(self.repo)):
            with self.subTest(working_dir=escape), self.assertRaises(ValueError):
                bridge.create("task", "docs", escape)

    def test_non_docs_task_type_is_rejected(self):
        bridge = Bridge(repo_root=self.repo, runner=fake_claude("docs/agent-bridge/x.md"))

        with self.assertRaises(ValueError):
            bridge.create("task", "bugfix")

    def test_record_contains_no_environment_values(self):
        os.environ["SYNORA_BRIDGE_TEST_SECRET"] = "s3cr3t-value-xyz"
        try:
            bridge, record = self._run(fake_claude("docs/agent-bridge/test.md"))
            stored = bridge._record_path(record["job_id"]).read_text(encoding="utf-8")
        finally:
            del os.environ["SYNORA_BRIDGE_TEST_SECRET"]

        self.assertNotIn("s3cr3t-value-xyz", stored)

    def test_worktree_is_removed_after_job(self):
        bridge, record = self._run(fake_claude("docs/agent-bridge/test.md"))

        self.assertFalse((bridge.worktrees_dir / record["job_id"]).exists())
        self.assertEqual(self._git("status", "--porcelain").strip(), "")


if __name__ == "__main__":
    unittest.main()
