# Synora Agent Bridge: architecture

Status: Phase B (controlled workflow), proof of concept. Tooling lives in `tools/pipeline/`. It is separate from `frontend/`, `backend/`, `database/`, and `prototypes/`.

## Path

```text
Antigravity → MCP (synora-bridge) → bridge → Claude Code (headless)
                                       ↓
                       isolated worktree → verification → reviewer
                                       ↓
                         job record (.agents/pipeline/, gitignored)
                                       ↓
                       Antigravity: get_status / get_result
```

## Job lifecycle

```text
QUEUED → RUNNING → VERIFYING → REVIEWING → SUCCEEDED
                                        ↘ CHANGES_REQUIRED
any unfinished state → FAILED
```

- `review` tasks skip `VERIFYING`: `RUNNING → REVIEWING → SUCCEEDED`.
- `FAILED` is set on any error. Nothing turns a failure into success.
- Illegal transitions raise an error. The allowed moves are defined in `ALLOWED_NEXT` in `bridge.py`.
- On server start, any unfinished job is set to `FAILED`.

## Task types

| Type | Writes | Verification | Review |
|---|---|---|---|
| `docs` | `docs/agent-bridge/` only | scope check (`SCOPE_ONLY` if no commands) | yes |
| `code` | `frontend/`, `backend/`, `database/`, `tests/` | commands required (`NOT_CONFIGURED` otherwise) | yes |
| `review` | nothing | none | yes, read-only |

## Isolation and enforcement

- Each job gets its own detached git worktree under `.agents/pipeline/worktrees/<job_id>`. The path comes from a validated UUID, so it cannot be steered by task text.
- A job records its base commit when it starts. A review worktree starts from the reviewed job's base commit, and the reviewed diff is applied there, so the candidate change is what gets reviewed.
- The user's checkout is never a working directory. The bridge checks its own checkout's `git status` before and after each job.
- Claude's tools are set by the CLI flag `--tools`:
  - implementer: `Read,Write,Edit,Glob,Grep`, permission `acceptEdits`. Writes are limited to the job worktree.
  - reviewer: `Read,Glob,Grep`, permission `dontAsk`. The bridge also checks that the reviewer left the worktree unchanged.
- `--strict-mcp-config` and `--setting-sources project` keep the headless Claude from loading the bridge itself, other MCP servers, or user-level hooks and plugins.
- Scope allowlists are checked after the run, in code. A change outside the allowlist fails the job.
- Verification commands come from the server's configuration, never from the task. They run without a shell.

## What counts as enforcement

- **Tool-level (enforced by Claude Code):** the `--tools` list, the permission mode, and the working-directory limit on file tools. The write-outside-worktree case was refused by a tool-level denial.
- **Code-level (enforced by the bridge):** UUID validation, relative and contained `working_dir`, allowlists, status transitions, and the worktree-unchanged check for the reviewer.
- **Prompt-level (not a boundary):** instructions in the prompt, such as "write only under docs/agent-bridge/". The model may follow them, but no security decision depends on that.

## Records

- JSON under `.agents/pipeline/jobs/`, written atomically under a lock.
- Contains: task, type, status, timestamps, Claude's result (capped), changed files, diff (capped), verification results (command, exit code, output tail), review verdict and findings, and any error.
- Contains no environment variables and no credentials.

## Open items (not in Phase B)

- No approval gate, commit, push, or merge. Those are Phase C.
- No repair loop, and no background scheduler.
- Synora has no test suite yet, so `code` tasks cannot succeed until verification commands are configured.
- The reviewer cannot run tests; it only reads.
- One server per records directory. Startup fails every unfinished job, so a second server would also fail the first server's live jobs. Job records have no owner field yet.
- Diffs are capped. A review of a diff over the cap fails rather than reviewing part of it.
