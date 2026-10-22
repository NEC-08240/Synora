# Synora agent bridge

Lets Antigravity hand a task to Claude Code, verify it, have it reviewed, and read back the result.
Design and security model: [docs/architecture/agent-bridge.md](../../docs/architecture/agent-bridge.md).

## Tools (MCP server `synora-bridge`)

| Tool | Purpose |
|---|---|
| `submit_task(task, task_type="docs", working_dir=".", target_job_id=None)` | Starts a job in the background and returns its `job_id`. |
| `get_status(job_id)` | Returns status, task type, timestamps, `error`, and `cleanup_error`. |
| `get_result(job_id)` | Returns the full record: Claude result, changed files, diff, verification, review. |

Task types: `docs` (writes under `docs/agent-bridge/`), `code` (writes under `frontend/`, `backend/`, `database/`, `tests/`, and must pass verification), `review` (read-only, needs `target_job_id` of a finished job).

## Run

```bash
python -m tools.pipeline.server                      # from the repo root (MCP stdio)
python -m unittest tools.pipeline.test_bridge -v     # tests (no external services)
```

Requires the `mcp` Python package (v2) and the Claude Code CLI on PATH.

Antigravity registration (`~/.gemini/config/mcp_config.json`):

```json
"synora-bridge": {
  "command": "C:\\Python314\\python.exe",
  "args": ["-m", "tools.pipeline.server"],
  "cwd": "C:\\Users\\Johan Joseph\\Documents\\Synora-worktrees\\agent-bridge-poc"
}
```

## Verification

- `code` tasks need verification commands. The server currently configures none, so `code` jobs FAIL with `NOT_CONFIGURED`. This is deliberate until Synora has a test suite.
- `docs` tasks record `SCOPE_ONLY`: the path check passed, and no test command was run.
- Commands are configured in code (`Bridge(verify_commands=...)`), never from the task text.

## Known limits

- Run one server per records directory. On start, every unfinished job is marked FAILED, including jobs owned by another running server. Do not start a second MCP client while jobs are running.
- Jobs run in background threads. A server restart marks unfinished jobs FAILED, but their worktrees may stay on disk.
- Review tasks use the reviewed job's base commit. Jobs recorded before base commits were stored fall back to HEAD.
- Records are plain JSON and may hold Claude's output and task text.
- The reviewer reads the diff from the prompt, and the diff may contain instructions. The reviewer is read-only, but its verdict is only as good as the model.
- Nothing merges or commits. The owner applies changes by hand.
