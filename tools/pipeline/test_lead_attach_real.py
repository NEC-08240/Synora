"""Real attachment: a message typed through lead_attach becomes part of the same Lead conversation.

This test uses the real Claude CLI and a real pseudo-terminal (winpty). It spends a few cents of API budget and needs
an interactive session, so it is OFF unless SYNORA_REAL_LEAD_TESTS=1 is set. It uses temporary state and workspace
folders only; it never touches ~/.synora. Claude stores the transcript under the user's Claude projects folder.

Run: SYNORA_REAL_LEAD_TESTS=1 python -m unittest tools.pipeline.test_lead_attach_real -v
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from .lead import LeadRunner
from .lead_mutex import LeadBusy, LeadMutex
from .lead_state import LeadState

REPO_ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get("SYNORA_REAL_LEAD_TESTS") == "1"
WINPTY = shutil.which("winpty")
MARKER = "INTERACTIVE-MARK-7731"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-Za-z]|\x1b[=>]|\r")


def _job(text):
    return {"job_id": str(uuid.uuid4()), "developer_id": "johan-admin", "branch": "feature/johan-admin/lead",
            "task": text, "request_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/johan-admin/*"]}}


def _wait(predicate, seconds, label, context=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.5)
    tail = context() if context else ""
    raise AssertionError(f"timed out waiting for {label}\n--- terminal (tail) ---\n{tail}")


@unittest.skipUnless(ENABLED, "set SYNORA_REAL_LEAD_TESTS=1 to run the real attachment test")
@unittest.skipUnless(WINPTY, "winpty is required for a real pseudo-terminal")
class RealAttachmentTest(unittest.TestCase):
    def setUp(self):
        # A winpty child may still hold files for a moment after the test; that must not hide the real result.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.state_dir = root / "state"
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.state_path = self.state_dir / "lead_state.json"
        self.mutex_path = self.state_dir / "lead.lock"
        self.terminal_out = root / "terminal.raw"

    def tearDown(self):
        self._tmp.cleanup()

    def _runner(self, lock_timeout=60):
        return LeadRunner(state_path=self.state_path, mutex_path=self.mutex_path, workspace=self.workspace,
                          log_path=self.state_dir / "turns.jsonl", lock_timeout=lock_timeout)

    def _screen(self):
        raw = self.terminal_out.read_bytes().decode("utf-8", "replace") if self.terminal_out.exists() else ""
        return ANSI.sub("", raw)

    def _transcript(self, session_id):
        matches = list((Path.home() / ".claude" / "projects").rglob(f"{session_id}.jsonl"))
        return matches[0].read_text(encoding="utf-8") if matches else ""

    def _mutex_held(self):
        probe = LeadMutex(self.mutex_path, timeout=0)
        try:
            probe.acquire(timeout=0)
        except LeadBusy:
            return True
        probe.release()
        return False

    def test_typed_message_becomes_part_of_the_same_lead_conversation(self):
        # Arrange: a real session with one headless turn.
        self._runner().run_turn(_job("Remember the code word AMBER-FOX-9. Reply with only OK."))
        session_id = LeadState.load(self.state_path).session_id
        self.assertFalse(self._mutex_held())

        # Act: attach through the supported wrapper, in a pseudo-terminal.
        env = dict(os.environ, SYNORA_LEAD_STATE_DIR=str(self.state_dir), SYNORA_LEAD_WORKSPACE=str(self.workspace),
                   CLAUDE_CODE_CHILD_SESSION="1", PYTHONDONTWRITEBYTECODE="1")
        out = open(self.terminal_out, "wb")
        attach = subprocess.Popen(
            [WINPTY, "-Xallow-non-tty", sys.executable, "-B", "-m", "tools.pipeline.lead_attach"],
            cwd=REPO_ROOT, env=env, stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT,
        )
        try:
            _wait(lambda: "trust this folder" in self._screen(), 90, "folder trust prompt")
            attach.stdin.write(b"\x1b[B")  # choose "Yes, I trust this folder"
            attach.stdin.flush()
            time.sleep(1)
            attach.stdin.write(b"\r")
            attach.stdin.flush()
            _wait(self._mutex_held, 90, "the attachment to hold the Lead mutex")
            # Wait until the existing conversation is on screen and the input prompt is ready, before typing.
            _wait(lambda: "AMBER-FOX-9" in self._screen() and "auto mode on" in self._screen(), 120, "the conversation to render")
            time.sleep(3)

            # The Worker's Lead turn is refused while the attachment is open.
            with self.assertRaises(LeadBusy):
                self._runner(lock_timeout=1).run_turn(_job("Worker request during attachment."))

            # Johan types a message and submits it (text first, then Enter, as a person would).
            attach.stdin.write(f"Johan here. The second code word is {MARKER}. Reply with OK.".encode())
            attach.stdin.flush()
            time.sleep(3)
            attach.stdin.write(b"\r")
            attach.stdin.flush()
            _wait(lambda: MARKER in self._transcript(session_id), 150, "the typed message in the transcript",
                  context=lambda: self._screen()[-1200:])

            # Close the attachment with the real /exit command.
            time.sleep(3)
            attach.stdin.write(b"/exit")
            attach.stdin.flush()
            time.sleep(3)
            attach.stdin.write(b"\r")
            attach.stdin.flush()
            attach.wait(timeout=120)
        finally:
            if attach.poll() is None:
                attach.kill()
                attach.wait()
            attach.stdin.close()
            out.close()

        # Assert: the mutex is free, the session ID is unchanged, and a later Worker turn sees the typed message.
        # The reviewer may reject a bare code-word answer as possibly credential-like (a known false positive), so
        # the check is on what the Lead saw and that the turn did not fail, not on the review verdict.
        self.assertFalse(self._mutex_held())
        self.assertEqual(LeadState.load(self.state_path).session_id, session_id)
        later = self._runner().run_turn(_job("What is the second code word Johan typed in the terminal? Reply with only it."))
        self.assertNotEqual(later["status"], "FAILED", later.get("error"))
        self.assertIn(MARKER, later.get("result", ""))
        self.assertEqual(LeadState.load(self.state_path).session_id, session_id)


if __name__ == "__main__":
    unittest.main()
