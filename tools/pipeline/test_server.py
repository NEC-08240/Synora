"""Tests for server startup: single-owner refusal, tool discovery exit codes, and startup recovery.

Each test runs the real module in a subprocess against a temporary repo. Run: python -m unittest tools.pipeline.test_server -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from .records import DirectoryOwner

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")


def _run_server(repo, extra_env=None, timeout=60):
    env = {**os.environ, "SYNORA_BRIDGE_REPO": str(repo), "SYNORA_BRIDGE_GIT": GIT, **(extra_env or {})}
    return subprocess.run(
        [sys.executable, "-m", "tools.pipeline.server"],
        cwd=PACKAGE_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class ServerStartupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.records = self.repo / ".agents" / "pipeline" / "jobs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_second_server_on_the_same_records_directory_is_refused(self):
        owner = DirectoryOwner(self.records).acquire()
        try:
            result = _run_server(self.repo)
        finally:
            owner.release()

        self.assertEqual(result.returncode, 3)
        self.assertIn("already owns", result.stderr)
        self.assertEqual(result.stdout, "", "refused server must not write to the MCP stdout channel")

    def test_missing_git_is_reported_with_the_fix(self):
        result = _run_server(self.repo, {"SYNORA_BRIDGE_GIT": str(Path(self._tmp.name) / "no-git.exe")})

        self.assertEqual(result.returncode, 2)
        self.assertIn("SYNORA_BRIDGE_GIT", result.stderr)

    def test_missing_claude_is_reported_with_the_fix(self):
        result = _run_server(self.repo, {"SYNORA_BRIDGE_CLAUDE": str(Path(self._tmp.name) / "no-claude.exe")})

        self.assertEqual(result.returncode, 2)
        self.assertIn("SYNORA_BRIDGE_CLAUDE", result.stderr)

    def test_server_recovers_abandoned_jobs_then_releases_the_directory(self):
        self.records.mkdir(parents=True)
        job_id = str(uuid.uuid4())
        abandoned = {
            "job_id": job_id, "task": "Write it.", "task_type": "docs", "working_dir": ".",
            "status": "RUNNING", "target_job_id": None, "created_at": "2026-10-22T00:00:00+00:00",
            "updated_at": "2026-10-22T00:00:00+00:00", "started_at": None, "finished_at": None,
            "claude_result": "", "changed_files": [], "diff": "", "base_commit": None,
            "diff_truncated": False, "verification": None, "review": None, "error": "", "cleanup_error": "",
        }
        (self.records / f"{job_id}.json").write_text(json.dumps(abandoned), encoding="utf-8")

        result = _run_server(self.repo)

        self.assertEqual(result.returncode, 0, result.stderr)
        stored = json.loads((self.records / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "FAILED")
        self.assertIn("was RUNNING", stored["error"])
        owner = DirectoryOwner(self.records).acquire()
        owner.release()


if __name__ == "__main__":
    unittest.main()
