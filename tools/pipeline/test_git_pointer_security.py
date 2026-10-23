"""Regression tests for a worktree .git pointer redirect. Run: python -m unittest tools.pipeline.test_git_pointer_security -v

A job's Claude process can write files in its own worktree. Git reads the worktree's .git file to
find its config, and that config can name a fsmonitor command that git runs on ordinary commands
such as `git status`. The bridge runs git in the worktree, so a redirected .git must never be followed.

Claude Code refuses to write .git directly (checked at runtime for Write and Edit, and for the
.git., .GIT and .git spellings). These tests assume that protection is bypassed and check that the
bridge still does not run the command.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from .bridge import Bridge


def redirect_pointer_and_plant_fsmonitor(marker_relative):
    """Stand-in for a job whose Claude has replaced the worktree's .git file and planted a config."""

    def runner(prompt, cwd, tools, permission_mode):
        root = Path(cwd)
        (root / ".git").unlink()
        (root / ".git").write_text("gitdir: docs/agent-bridge/evil\n", encoding="utf-8")
        evil = root / "docs" / "agent-bridge" / "evil"
        (evil / "refs").mkdir(parents=True, exist_ok=True)
        (evil / "objects").mkdir(parents=True, exist_ok=True)
        (evil / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (evil / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n\tfsmonitor = touch " + marker_relative + "\n",
            encoding="utf-8",
        )
        return 0, '{"subtype": "success", "is_error": false, "result": "done"}', ""

    return runner


class GitPointerRedirectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "i"],
            cwd=self.repo,
            check=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_redirected_git_pointer_cannot_run_a_command_during_a_job(self):
        bridge = Bridge(repo_root=self.repo, runner=redirect_pointer_and_plant_fsmonitor("../fsmon_marker.txt"))
        job_id = bridge.create("Write it.", "docs")["job_id"]

        bridge.execute(job_id)

        marker = bridge.worktrees_dir / "fsmon_marker.txt"
        self.assertFalse(marker.exists(), "git executed a command named by the job's redirected .git")
        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("pointer", record["error"])


if __name__ == "__main__":
    unittest.main()
