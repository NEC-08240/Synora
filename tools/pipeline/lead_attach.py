"""Johan's way into the persistent Engineering Lead: `python -m tools.pipeline.lead_attach`.

This is the wrapper that holds the Lead mutex while Johan's terminal is open. A bare `claude --resume <id>` does
not take the mutex, so it bypasses the Worker's serialization. Use this wrapper, not a bare resume.

The terminal gets the same posture as a Worker turn: restricted tools, read-only tools, no MCP servers, project
settings only, and the Lead's instructions. Claude's own permission prompts stay on, so Johan approves each tool
use himself. The inherited CLAUDE_CODE_CHILD_SESSION marker is removed: when it is present, Claude does not save the
interactive turns to the transcript.
"""

import os
import subprocess
import sys
from pathlib import Path

from .executables import CLAUDE_ENV, resolve_executable
from .lead import INSTRUCTIONS_FILE, LEAD_TOOLS
from .lead_mutex import LeadBusy, LeadMutex
from .lead_state import LeadState, LeadStateError, STATE_ACTIVE

CHILD_MARKER = "CLAUDE_CODE_CHILD_SESSION"


class LeadNotReady(RuntimeError):
    """The Lead session has not been created, or is not usable. Nothing is opened."""


def attach(state_path, mutex_path, workspace, executable, timeout: float = 0.0) -> int:
    """Open the stored Lead session in an interactive terminal, holding the Lead mutex for as long as it is open."""
    try:
        state = LeadState.load(state_path)
        state.ensure_usable()
    except LeadStateError as err:
        raise LeadNotReady(str(err)) from None
    if state.status != STATE_ACTIVE:
        raise LeadNotReady("The Lead session is not active.")
    mutex = LeadMutex(mutex_path, timeout=timeout)
    mutex.acquire(timeout=timeout)  # raises LeadBusy when a turn is running; nothing is opened then
    try:
        argv = _argv(executable, state.session_id)
        return _run_terminal(argv, cwd=Path(workspace), env=_terminal_environment())
    finally:
        mutex.release()


def _argv(executable, session_id):
    base = list(executable) if isinstance(executable, (list, tuple)) else [executable]
    instructions = INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    return [*base, "--resume", session_id,
            "--restricted", "--tools", LEAD_TOOLS, "--strict-mcp-config", "--setting-sources", "project",
            "--append-system-prompt", instructions]


def _terminal_environment():
    env = dict(os.environ)
    env.pop(CHILD_MARKER, None)
    return env


def _run_terminal(argv, cwd, env):
    return subprocess.call(argv, cwd=cwd, env=env)


def main(argv=None):
    state_dir = Path(os.environ.get("SYNORA_LEAD_STATE_DIR") or Path.home() / ".synora" / "lead")
    workspace = os.environ.get("SYNORA_LEAD_WORKSPACE")
    if not workspace:
        print("SYNORA_LEAD_WORKSPACE is not set. Set it to the Lead workspace folder first.", file=sys.stderr)
        return 2
    try:
        executable = resolve_executable("claude", CLAUDE_ENV)
        print("Attaching to the Engineering Lead. Keep one attachment open; Worker turns wait until you exit.")
        return attach(state_dir / "lead_state.json", state_dir / "lead.lock", workspace, executable)
    except LeadBusy:
        print("The Lead is busy: a turn is running or another terminal is attached. Try again shortly.", file=sys.stderr)
        return 3
    except LeadNotReady as err:
        print(f"The Lead is not ready: {err}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
