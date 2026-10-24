"""Johan's attach wrapper must hold the Lead mutex while his terminal is open, and must refuse when a turn is running.

Run: python -m unittest tools.pipeline.test_lead_attach -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from .lead_attach import LeadNotReady, attach
from .lead_mutex import LeadBusy, LeadMutex
from .lead_state import LeadState

REPO_ROOT = Path(__file__).resolve().parents[2]

# A stand-in for `claude`: records its working directory, arguments and the marker variable, then exits.
PROBE = (
    "import json, os, sys, pathlib\n"
    "out = pathlib.Path(sys.argv[1])\n"
    "out.write_text(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[2:], "
    "'marker': os.environ.get('CLAUDE_CODE_CHILD_SESSION')}), encoding='utf-8')\n"
)


class AttachTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.state_dir = root / "state"
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.probe_out = root / "probe.json"
        self.session_id = str(uuid.uuid4())
        state = LeadState.load(self.state_dir / "lead_state.json")
        state.begin_create(self.session_id)
        state.mark_active(self.session_id)
        self.executable = [sys.executable, "-B", "-c", PROBE, str(self.probe_out)]

    def tearDown(self):
        self._tmp.cleanup()

    def _attach(self, **kwargs):
        return attach(
            state_path=self.state_dir / "lead_state.json",
            mutex_path=self.state_dir / "lead.lock",
            workspace=self.workspace,
            executable=self.executable,
            **kwargs,
        )

    def test_attach_opens_the_stored_session_in_the_workspace(self):
        self.assertEqual(self._attach(), 0)
        seen = json.loads(self.probe_out.read_text(encoding="utf-8"))
        self.assertEqual(seen["args"][:2], ["--resume", self.session_id])
        self.assertEqual(Path(seen["cwd"]).resolve(), self.workspace.resolve())

    def test_attach_keeps_the_restricted_posture(self):
        self._attach()
        args = json.loads(self.probe_out.read_text(encoding="utf-8"))["args"]
        self.assertIn("--restricted", args)
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(args[args.index("--tools") + 1], "Read,Glob,Grep")
        self.assertIn("--append-system-prompt", args)
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertNotIn("--permission-mode", args)  # Claude's permission prompts stay on for Johan

    def test_attach_removes_the_child_session_marker(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_CHILD_SESSION": "1"}):
            self._attach()
        seen = json.loads(self.probe_out.read_text(encoding="utf-8"))
        self.assertIsNone(seen["marker"])

    def test_attach_holds_the_mutex_while_the_terminal_is_open(self):
        probe_lock = LeadMutex(self.state_dir / "lead.lock", timeout=0)
        observed = {}

        def inside_terminal(*args, **kwargs):
            with self.assertRaises(LeadBusy):
                probe_lock.acquire(timeout=0)
            observed["held"] = True
            return 0

        with mock.patch("tools.pipeline.lead_attach._run_terminal", side_effect=inside_terminal):
            self._attach()
        self.assertTrue(observed.get("held"))
        probe_lock.acquire(timeout=0)  # released after the terminal closes
        probe_lock.release()

    def test_attach_refuses_while_a_turn_is_running_and_launches_nothing(self):
        held = LeadMutex(self.state_dir / "lead.lock", timeout=0)
        held.acquire(timeout=0)
        try:
            with self.assertRaises(LeadBusy):
                self._attach()
        finally:
            held.release()
        self.assertFalse(self.probe_out.exists())

    def test_attach_refuses_when_the_lead_is_not_active(self):
        empty_dir = Path(self._tmp.name) / "empty"
        with self.assertRaises(LeadNotReady):
            attach(
                state_path=empty_dir / "lead_state.json",
                mutex_path=empty_dir / "lead.lock",
                workspace=self.workspace,
                executable=self.executable,
            )
        self.assertFalse(self.probe_out.exists())


if __name__ == "__main__":
    unittest.main()
