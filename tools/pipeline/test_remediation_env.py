"""F2: Claude must receive an explicit allowlisted environment. Run: python -m unittest tools.pipeline.test_remediation_env -v

The stand-in below is a real executable that records the environment and arguments it receives,
so the tests check the actual child process rather than trusting Claude to refuse to print a secret.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .bridge import CLAUDE_ENV_ALLOWLIST, IMPLEMENT_TOOLS, claude_environment, run_claude

WORKER_SECRETS = {
    "SYNORA_TEST_SECRET_004": "TEST_SECRET_004_VALUE",
    "SYNORA_WORKER_PRIVATE_KEY_B64": "TEST_WORKER_KEY_B64_VALUE",
    "SYNORA_WORKER_KEY_FILE": "C:/synthetic/worker.key",
    "SYNORA_GATEWAY_SIGNING_SECRET": "TEST_GATEWAY_SIGNING_VALUE",
    "SYNORA_TEST_GITHUB_TOKEN_002": "TEST_GITHUB_TOKEN_002_VALUE",
    "GITHUB_TOKEN": "TEST_GITHUB_TOKEN_VALUE",
    "ANTHROPIC_API_KEY": "TEST_ANTHROPIC_KEY_VALUE",
}


# The stand-in is a .bat file that only Windows executes. Linux CI skips these; they run on the Windows Worker.
@unittest.skipUnless(os.name == "nt", "stand-in is a Windows .bat file")
class StandInClaudeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.stand_in = self.folder / "fake_claude.bat"
        self.stand_in.write_text(
            "@echo off\r\n"
            "set > \"%~dp0child_env.txt\"\r\n"
            "echo %* > \"%~dp0child_args.txt\"\r\n"
            "echo {\"subtype\": \"success\", \"is_error\": false, \"result\": \"ok\"}\r\n",
            encoding="utf-8",
        )
        self.worker_env = {**os.environ, **WORKER_SECRETS, "USERPROFILE": os.environ.get("USERPROFILE", "C:/Users/test")}

    def tearDown(self):
        self._tmp.cleanup()

    def _run_child(self, source):
        with mock.patch.dict(os.environ, source, clear=True):
            code, _out, _err = run_claude("prompt", str(self.folder), IMPLEMENT_TOOLS, "acceptEdits", str(self.stand_in))
        self.assertEqual(code, 0)
        child_env = (self.folder / "child_env.txt").read_text(errors="replace")
        child_args = (self.folder / "child_args.txt").read_text(errors="replace")
        return child_env, child_args

    def test_f2_1_worker_secret_is_not_seen_by_the_claude_child(self):
        child_env, _ = self._run_child(self.worker_env)

        for name, value in WORKER_SECRETS.items():
            with self.subTest(name=name):
                self.assertNotIn(name + "=", child_env)
                self.assertNotIn(value, child_env)

    def test_f2_2_claude_runtime_variables_are_kept(self):
        env = {**self.worker_env, "PATH": "C:/tools", "APPDATA": "C:/synthetic/appdata", "LOCALAPPDATA": "C:/synthetic/local"}
        child_env, _ = self._run_child(env)

        self.assertIn("APPDATA=C:/synthetic/appdata", child_env)
        self.assertIn("LOCALAPPDATA=C:/synthetic/local", child_env)
        self.assertIn("PATH=", child_env)

    def test_f2_3_worker_key_configuration_cannot_reach_claude(self):
        env = {"SYNORA_WORKER_PRIVATE_KEY_B64": "TEST_WORKER_KEY_B64_VALUE", "SYNORA_WORKER_KEY_FILE": "C:/x.key", "PATH": "C:/tools"}
        self.assertEqual(claude_environment(env), {"PATH": "C:/tools"})

    def test_f2_4_gateway_signing_secret_cannot_reach_claude(self):
        env = {"SYNORA_GATEWAY_SIGNING_SECRET": "TEST_GATEWAY_SIGNING_VALUE", "PATH": "C:/tools"}
        self.assertNotIn("SYNORA_GATEWAY_SIGNING_SECRET", claude_environment(env))

    def test_f2_5_tool_restrictions_are_still_passed_to_claude(self):
        _, child_args = self._run_child(self.worker_env)

        self.assertIn("--restricted", child_args)
        self.assertIn("--strict-mcp-config", child_args)
        self.assertIn("--setting-sources project", child_args)
        self.assertIn("--tools Read,Write,Edit,Glob,Grep", child_args)
        self.assertNotIn("Bash", child_args)
        self.assertNotIn("WebFetch", child_args)

    def test_allowlist_contains_no_secret_style_names(self):
        for name in CLAUDE_ENV_ALLOWLIST:
            with self.subTest(name=name):
                lowered = name.lower()
                self.assertFalse(any(word in lowered for word in ("secret", "token", "key", "password")))


if __name__ == "__main__":
    unittest.main()
