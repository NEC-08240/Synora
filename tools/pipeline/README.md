# Synora agent bridge

Lets Antigravity hand a task to Claude Code, verify it, have it reviewed, and read back the result.
Design and trust boundaries: [docs/architecture/agent-bridge.md](../../docs/architecture/agent-bridge.md).

## Tools (MCP server `synora-bridge`)

| Tool | Purpose |
|---|---|
| `submit_task(task, task_type="docs", working_dir=".", target_job_id=None)` | Starts a job in the background and returns its `job_id`. |
| `get_status(job_id)` | Returns status, task type, timestamps, `error`, and `cleanup_error`. |
| `get_result(job_id)` | Returns the full record: Claude result, changed files, diff, verification, and review with evidence. |

Task types: `docs` (writes under `docs/agent-bridge/`), `code` (writes under `frontend/`, `backend/`, `database/`, `tests/`, and must pass configured verification), `review` (read-only, needs `target_job_id` of a finished job).

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SYNORA_BRIDGE_REPO` | Repo root whose `.agents/pipeline/` holds records and worktrees. | The checkout this package lives in. |
| `SYNORA_BRIDGE_GIT` | Full path to `git`. | Lookup on PATH. |
| `SYNORA_BRIDGE_CLAUDE` | Full path to the Claude Code executable. | Lookup on PATH. |

An explicit variable is checked first. If it points at something that is not a file, startup fails and names the variable. If neither is set and PATH does not have the tool, startup fails with exit code 2 and says what to set. Nothing is downloaded or installed.

Register it in Antigravity's MCP config. Set the full paths in `env` if the Antigravity process PATH does not include the tools:

```json
"synora-bridge": {
  "command": "<path-to-python.exe>",
  "args": ["-m", "tools.pipeline.server"],
  "cwd": "<path-to-worktree>",
  "env": {
    "SYNORA_BRIDGE_GIT": "<path-to-git.exe>",
    "SYNORA_BRIDGE_CLAUDE": "<path-to-claude.exe>"
  }
}
```

Use long paths. On Windows, an 8.3 short name in a path (for example `PROFIL~1` in place of a long profile folder) made the Claude harness refuse file reads for the reviewer.

## Running one server per records directory

On start, the server takes an exclusive lock on `.agents/pipeline/jobs/.owner.lock`:

- A second server on the same directory exits with code 3 and names the owner's PID. It does not touch the records.
- The lock is an OS file lock. A crashed server releases it automatically, so there is no stale-file takeover and no PID comparison.
- After the lock is taken, the server marks every unfinished job FAILED, with the status it was in, and removes only bridge-created worktrees. Records are never deleted.

## Run

```bash
# Run all unit and integration tests (181 tests)
python -m unittest tools.pipeline.test_bridge tools.pipeline.test_executables tools.pipeline.test_hardening tools.pipeline.test_server tools.pipeline.test_storage tools.pipeline.test_step3 tools.pipeline.test_gateway_api tools.pipeline.test_gateway_auth tools.pipeline.test_gateway_authorization tools.pipeline.test_gateway_concurrency tools.pipeline.test_worker_network tools.pipeline.test_worker_reconnect tools.pipeline.test_worker_security tools.pipeline.test_result_signing tools.pipeline.test_remote_protocol tools.pipeline.test_git_ownership tools.pipeline.test_lan_mode

# Run local stdio MCP bridge
python -m tools.pipeline.server

# Run remote MCP shim
python -m tools.pipeline.remote_shim
```

Requires `mcp`, `starlette`, `uvicorn`, `cryptography`, and `websocket-client`. The tests use real git, creating temporary repositories where necessary, and mock Claude execution so no Claude Code token is required during automated testing.

## Verification

- `code` tasks need verification commands. None are configured on the MCP server, so `code` jobs FAIL with `NOT_CONFIGURED`. This is deliberate until Synora has a test suite.
- `docs` tasks record `SCOPE_ONLY`. The path check passed, and no test or build command ran.
- Commands are configured in code (`Bridge(verify_commands=...)`), never from task text.

## Known limits

- Tasks run in background threads. A hard kill leaves worktrees on disk until the next start removes them.
- Records are plain JSON. They can hold Claude's output and the task text.
- The reviewer reads the file and the diff. It cannot run tests. See the architecture doc for exactly what its verdict proves.
- Nothing commits, pushes, or merges. The owner applies changes by hand.


## Phase C Step 3 & Step 4 Architecture Modules

| Module | Purpose | Status |
|---|---|---|
| `team_registry.py` | Developer enrollment, Ed25519 public keys, branch patterns, module scope ACLs. | IMPLEMENTED |
| `worker_registry.py` | Worker enrollment, Ed25519 worker keys, status, capabilities, and lifecycle. | IMPLEMENTED |
| `auth.py` | Cryptographic challenge-response auth, replay protection, IP-agnostic session tokens. | IMPLEMENTED |
| `authorization.py` | Cross-developer job isolation, branch and file scope enforcement, owner admin checks. | IMPLEMENTED |
| `contribution_gate.py` | Reusable contribution gate validating diffs, bug fixes, failure evidence, and path security. | IMPLEMENTED |
| `protocol.py` | Structured gateway-worker protocol envelopes and payload validation. | IMPLEMENTED |
| `result_envelope.py` | Cryptographic Ed25519 signed result envelopes with canonical deterministic serialization. | IMPLEMENTED |
| `queue.py` | Persistent SQLite queue with fair scheduling, atomic claiming, replay protection, and reaper. | IMPLEMENTED |
| `audit.py` | Structured JSON Lines audit logging with recursive secret scrubbing. | IMPLEMENTED |
| `gateway.py` | Gateway coordination engine orchestrating auth, authorization, queue, and result verification. | IMPLEMENTED |
| `gateway_app.py` | Starlette REST API (`/auth/*`, `/jobs/*`, `/health`, `/worker/status`) & WebSocket endpoint (`/ws/worker`). | IMPLEMENTED |
| `worker.py` | `OutboundWorker` persistent daemon establishing outbound WSS connection from Johan's PC. | IMPLEMENTED |
| `tls_config.py` | Hardened TLS 1.2+ configuration, strict certificate validation, and ephemeral cert generator. | IMPLEMENTED |
| `remote_shim.py` | Remote MCP adapter translating Antigravity MCP calls into Gateway HTTPS requests. | IMPLEMENTED |
