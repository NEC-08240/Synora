"""Tests for executable discovery. No real git or Claude Code is needed. Run: python -m unittest tools.pipeline.test_executables -v"""

import tempfile
import unittest
from pathlib import Path

from .executables import CLAUDE_ENV, GIT_ENV, ExecutableNotFound, resolve_executable, resolve_executables


class ExecutableResolutionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fake_git = self.root / "git-custom.exe"
        self.fake_git.write_text("", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_configured_path_wins_over_path_lookup(self):
        found = resolve_executable("git", GIT_ENV, {GIT_ENV: str(self.fake_git)}, which=lambda name: "/usr/bin/git")

        self.assertEqual(found, str(self.fake_git.resolve()))

    def test_configured_path_that_is_not_a_file_is_an_error(self):
        missing = self.root / "nope" / "git.exe"
        with self.assertRaises(ExecutableNotFound) as caught:
            resolve_executable("git", GIT_ENV, {GIT_ENV: str(missing)}, which=lambda name: "/usr/bin/git")

        self.assertIn(GIT_ENV, str(caught.exception))
        self.assertIn("not a file", str(caught.exception))

    def test_path_lookup_is_used_when_nothing_is_configured(self):
        found = resolve_executable("claude", CLAUDE_ENV, {}, which=lambda name: f"/bin/{name}")

        self.assertEqual(found, "/bin/claude")

    def test_blank_configuration_counts_as_unset(self):
        found = resolve_executable("git", GIT_ENV, {GIT_ENV: "   "}, which=lambda name: "/bin/git")

        self.assertEqual(found, "/bin/git")

    def test_missing_executable_says_how_to_fix_it(self):
        with self.assertRaises(ExecutableNotFound) as caught:
            resolve_executable("claude", CLAUDE_ENV, {}, which=lambda name: None)

        message = str(caught.exception)
        self.assertIn("'claude' was not found on PATH", message)
        self.assertIn(CLAUDE_ENV, message)

    def test_resolve_executables_reports_each_tool(self):
        found = resolve_executables(
            {GIT_ENV: str(self.fake_git), CLAUDE_ENV: str(self.fake_git)},
            which=lambda name: None,
        )

        self.assertEqual(set(found), {"git", "claude"})

    def test_resolve_executables_fails_on_the_first_missing_tool(self):
        with self.assertRaises(ExecutableNotFound) as caught:
            resolve_executables({GIT_ENV: str(self.fake_git)}, which=lambda name: None)

        self.assertIn("'claude'", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
