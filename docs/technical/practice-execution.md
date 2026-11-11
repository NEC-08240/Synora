# Practical Learning: Code and SQL Execution

How Synora runs student C, C++ and SQL. No compiler or SQL engine is built in-house
(handoff section 4). The backend validates, authorises and forwards; execution happens elsewhere.

## Endpoints (all require a Student or Faculty cookie)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/v1/execute/status` | – | `{ code: bool, sql: bool }` which runners are configured |
| POST | `/api/v1/execute/code` | `{ language: "c"\|"cpp", source (≤64 KB), stdin? (≤16 KB) }` | `{ stdout, stderr, exitCode, timedOut, compileError, durationMs }` |
| POST | `/api/v1/execute/sql` | `{ sql (≤16 KB), setupScript? (≤64 KB) }` | `{ columns, rows (≤200), rowCount, truncated, error }` |

Runner not configured → `503`. Runner unreachable → `503`. Runner rejects the request → `502`.
SQL errors (syntax, missing table, timeout) come back as `200` with `error` set: they are the
student's feedback, not a server fault.

## C / C++ proxy (`backend/src/practice/code.js`)

- Forwards to a **Piston-compatible** HTTP runner: `POST {EXECUTOR_URL}/api/v2/execute`.
  Piston runs each job in an isolated container with its own CPU, memory, process and time
  limits; Synora passes `compile_timeout` (10 s) and `run_timeout` (3 s) and aborts the HTTP
  call shortly after.
- Output is clipped at 64 KB per stream. A non-zero compile step sets `compileError: true`
  and returns the compiler's stderr.
- Local setup (Docker):
  ```bash
  docker run -d --name piston -p 2000:2000 -v piston_packages:/piston/packages --privileged ghcr.io/engineer-man/piston
  # then install the toolchains once:
  curl -X POST http://localhost:2000/api/v2/packages -H 'Content-Type: application/json' -d '{"language":"gcc","version":"10.2.0"}'
  ```
  Set `EXECUTOR_URL=http://localhost:2000` in `backend/.env`.

## SQL sandbox (`backend/src/practice/sql.js`)

Guardrail from handoff section 9.3: student SQL **never** touches `SynoraV1`.

- Separate database `SynoraV1_Sandbox` with its own login `synora_sandbox` that has
  `db_ddladmin`, `db_datareader`, `db_datawriter` in that database only. Create both with
  `database/sandbox_setup.sql`, then set `SANDBOX_DB_NAME`, `SANDBOX_DB_USER`,
  `SANDBOX_DB_PASSWORD` in `backend/.env`. Leave `SANDBOX_DB_NAME` empty to disable.
- Each request opens a transaction, runs `setupScript` (the activity's `SqlTaskSpecs.SetupScript`)
  then the student's `sql`, reads at most 200 rows, and **always rolls back**. Nothing a student
  does persists between requests, so every attempt starts from an empty schema.
- `requestTimeout` is 5 s. The pool is small (max 4) so a classroom cannot exhaust the server.

`shortcut:` rollback-only transactions give schema isolation but not CPU/memory isolation inside
the SQL Server instance. Upgrade to a per-container SQL Server (Docker `mcr.microsoft.com/mssql/server`)
if the sandbox is ever exposed beyond the trusted lab network.

## Verification

`backend/test/practice.test.js` (4 tests): auth boundary; sandbox setup + query, proof the table
is gone on the next request, syntax error surfaced as feedback, validation; code proxy against a
fake Piston server (request shape, compile-error mapping); 503 + status without `EXECUTOR_URL`.
Live C/C++ execution is verified only once a Piston runner is reachable.
