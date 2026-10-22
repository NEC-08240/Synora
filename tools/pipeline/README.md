# Synora agent bridge (proof of concept)

Lets Antigravity hand a documentation task to Claude Code and read back the result.

```text
Antigravity → MCP (server.py) → bridge.py → Claude Code (claude -p)
                                   ↓
                     job record in .agents/pipeline/jobs/
                                   ↓
                     Antigravity reads it with get_status / get_result
```

## Tools

| Tool | Purpose |
|---|---|
| `submit_task(task, task_type="docs", working_dir=".")` | Starts a job in the background and returns its `job_id`. |
| `get_status(job_id)` | Returns the job's status and timestamps. |
| `get_result(job_id)` | Returns the full record: Claude's result, changed files, and diff. |

## Safety rules

- Claude runs in a detached git worktree under `.agents/pipeline/worktrees/`. Nothing is committed, pushed, or merged.
- Only `docs/agent-bridge/` may change. Any other change marks the job FAILED.
- Claude has only `Read`, `Write`, `Edit`, `Glob`, `Grep`. No shell, no MCP servers, and no user-level hooks or plugins (`--setting-sources project`).
- Job IDs must be canonical UUIDs. `working_dir` must be relative and stay inside the worktree.
- Job records and worktrees are gitignored.
- The mock path from CIPHER is not included.

## Run

```bash
python -m tools.pipeline.server          # from the repo root
python -m unittest tools.pipeline.test_bridge -v
```

Requires the `mcp` Python package (v2) and the Claude Code CLI on PATH.

## Known limits

- Jobs run in background threads. A server restart marks running jobs FAILED.
- Records are not encrypted. They hold Claude's output, which may contain whatever Claude read.
- The "bridge checkout unchanged" check only covers the checkout the server runs from.
- Nothing merges results back. The owner applies changes by hand.
