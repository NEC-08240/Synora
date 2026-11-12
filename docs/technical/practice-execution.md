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
SQL errors (syntax, missing table, timeout, refused statement) come back as `200` with `error` set:
they are the student's feedback, not a server fault. A full sandbox queue returns `429`.

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

Guardrail from handoff section 9.3: student SQL **never** touches the app database.

### What the database enforces (the real control)

Set up by `database/sandbox_setup.sql` (idempotent; run with `sqlcmd -v SANDBOX_DB=... SANDBOX_LOGIN=... SANDBOX_PASSWORD=...`):

- A separate database and a login with `CHECK_POLICY = ON`, default schema `sbx`. The login is not
  a member of `db_ddladmin`, `db_datareader` or `db_datawriter`.
- Granted: `CREATE TABLE`, and `SELECT, INSERT, UPDATE, DELETE, ALTER` on schema `sbx` only.
- Denied: `CREATE PROCEDURE`, `CREATE FUNCTION`, `CREATE TYPE` (database level), `CREATE SEQUENCE`
  and `ALTER` on schema `dbo`. Reads from other databases fail (verified: cross-database SELECT is
  denied; `xp_cmdshell`, `Ole Automation Procedures`, `Ad Hoc Distributed Queries` are off).
- `RECOVERY SIMPLE`, data file capped at 512 MB and log at 256 MB.
- **Not denied:** `CREATE TRIGGER` cannot be denied by permission, and a DML trigger needs ALTER
  on its table, which the `sbx` grant gives. Triggers are therefore caught by the leak detector and
  the reset script, not by the permissions.

### What the validator does (defense in depth only, NOT isolation)

`findForbiddenStatement()` tokenises both `setupScript` and `sql` (comments and string literals
are ignored) and refuses before any database work: `EXEC`/`EXECUTE`, any `sp_`/`xp_` name,
`COMMIT`, `ROLLBACK`, `BEGIN`/`SAVE TRAN`, `BULK`, `KILL`, `SHUTDOWN`, `RECONFIGURE`, `GRANT`,
`REVOKE`, `DENY`, `USE`, `OPENROWSET`/`OPENQUERY`/`OPENDATASOURCE`, `CREATE|ALTER|DROP LOGIN|USER`,
and `SET` (except `ON DELETE|UPDATE SET NULL|DEFAULT`, and the `SET` of a real `UPDATE <target> SET`;
`UPDATE STATISTICS`, cursor `FOR UPDATE`, trigger `AFTER UPDATE` and `IF UPDATE(col)` do not open that permit). The validator is a text scan, so it can be wrong in both directions. It is
not a security boundary; the permissions above are. A student can still write SQL the validator
misses, and the database must still refuse it.

### Per-run behaviour

- Each run is one transaction: `setupScript`, then the student `sql`. Results are streamed and
  never buffered past 200 rows (`config.practice.maxRows`); the 201st row cancels the request and
  sets `truncated: true`.
- The transaction is always rolled back. After the rollback, the leak detector lists `sbx` user
  objects (tables, views, procedures, functions, synonyms, sequences, triggers, foreign keys) and
  drops any that escaped the transaction, with a `console.warn` per object. The baseline is empty
  (`SHIPPED_OBJECTS`); the setup script ships no `sbx` objects.
- Timeout (`config.practice.sqlTimeoutMs`, 5 s), cancel, failed rollback or failed leak cleanup
  **recycles the pool**: the pool is dropped and closed in the background, so no connection stays
  in an open transaction. The close is never awaited in the request path.
- Runs are **serial by default** (`SANDBOX_CONCURRENCY=1`), because students share the `sbx` schema
  and overlapping runs would see each other's uncommitted objects. Up to `SANDBOX_QUEUE_MAX`
  (default 8) requests wait in memory; the next one gets `429`. Changing `SANDBOX_CONCURRENCY`
  above 1 is not supported.

### Observed results (lab run, mssql 12.7.14, tedious)

- SET state on a reused pooled connection: `SET DATEFIRST 1` in one request was read back as `7`
  in the next request on the same connection (same `@@SPID`). So the driver does not carry
  session SET state across requests in this setup. This is observed, not guaranteed; the validator
  still refuses SET because the rule is cheap and a future driver change would not be noticed.
- A 5,000,000-row recursive CTE returns 200 rows with `truncated: true` in about 90 ms.
- `WAITFOR DELAY '00:00:20'` is aborted at about 5.1 s and the next request succeeds.

### Residual limits (not fixed here)

- **tempdb is instance-wide.** A student's large sort or spool uses shared tempdb; the data-file
  cap does not apply to tempdb.
- **Resource Governor** is configured on this Developer Edition server (`sys.resource_governor_configuration`)
  but **disabled** (`is_enabled = 0`), and no workload group limits are set. Resource Governor is
  not available on the Express edition, so an Express deployment has no per-workload limits at all.
- **CPU is not capped.** A query can use CPU up to the instance limit until the 5 s timeout ends it.
- **The queue is in-memory and single-instance.** It does not protect a second backend process.
- **The reset schedule is manual.** `database/sandbox_reset.sql` drops every `sbx` user object; run
  it with `sqlcmd` from Windows Task Scheduler (SQL Agent is installed but stopped on this server,
  and the reset does not depend on it). Run it nightly, or after any shared-state incident.
- **Session state is only partly constrained.** The validator refuses `SET`; the DATEFIRST result
  above is the only test evidence that pooled connections do not carry SET state. No other session
  option was tested.
- `trustServerCertificate` follows `DB_TRUST_SERVER_CERT` (default false); the sandbox pool uses the
  same setting as the app pool.

For production, a per-container SQL Server (Docker `mcr.microsoft.com/mssql/server`) is the
upgrade path if the sandbox is ever exposed beyond the trusted lab network.

### Verified bypass tests (lab run, SQL Server instance with the sandbox login)

Executed through `runSql` against a disposable lab database (regression tests in `backend/test/sandbox.test.js`):

| Input | Result |
|---|---|
| `UPDATE STATISTICS ... SET`, `FOR UPDATE ... SET`, `AFTER UPDATE ... SET` variants | refused (`SET is not allowed`) |
| `SELECT name FROM master.sys.databases` | accepted; lists only master, tempdb and the sandbox because setup runs `DENY VIEW ANY DATABASE` (without it: every database name on the instance) |
| `SELECT ... FROM master.sys.sql_logins` | accepted; login names visible, `password_hash` is NULL |
| three-part names into another database / msdb | denied by permissions |
| `SELECT * INTO ##g` / `#tmp` | accepted; gone by the next run (rolled back). tempdb growth is bounded only by the 5 s timeout |
| 2,000,000-row `SELECT INTO #big` | hit the 5 s timeout plus a failed 5 s cancel (about 10 s), rollback failed, pool recycled; next run fine |
| `CAST('x' AS int)` / `1/0` batch abort | error returned, nothing persisted, next run sees `@@TRANCOUNT = 1` (its own transaction, no leaked one). The runner logs "rollback failed" and recycles the pool because the aborted transaction cannot be rolled back again; noisy but safe |
| 5000 `SELECT` result sets in one batch | first set returned in about 0.4 s, pool usable afterwards (CPU not measured separately) |
| `CREATE TRIGGER` after `CREATE TABLE` in the same batch | refused by SQL Server (must be the first statement), so a trigger cannot fire inside a run |
| `CREATE TRIGGER ... ON sbx.t` alone, with `dbo.victim` present | the trigger statement runs; the leak detector then removes the pre-existing `sbx.t`. Trigger firing against a `dbo` object was **not** demonstrated |
| plain `SELECT` of a `dbo` table | denied |

`sandbox_setup.sql` refuses (THROW, non-zero under `-b`) a database that already contains `dbo` user objects:
`sbx` is owned by `dbo`, so a student trigger there could chain ownership into `dbo` objects. Use an empty
database dedicated to the sandbox. Pooled SET state: the validator refuses all SET outside a real UPDATE, and the
DATEFIRST observation above shows no carry-over; no session-reset prelude was added.

## Accepted limitations

- **Slot monopolisation.** With `SANDBOX_CONCURRENCY=1` one student looping queries of about 5 s (for example
  `WAITFOR DELAY '00:00:04'`) keeps the single slot busy and blocks the sandbox for everyone. Impact is
  availability only. Mitigations in place: per-user execute rate limit (`RATE_LIMIT_EXECUTE_PER_MIN`), the 5 s
  timeout, and the queue cap (`SANDBOX_QUEUE_MAX`, then 429). A later improvement is per-user fairness in the queue.
- **In-memory JWT revocation list.** The `jti` denylist lives in process memory: a restart empties it and
  multiple instances do not share it, so a logged-out or revoked token is honoured again until its natural expiry.
  A password change still invalidates tokens through the `pv` claim. Upgrade path: a database table or Redis.
- **TRUST_PROXY** must equal the real number of trusted reverse-proxy hops (`1` behind one proxy; unset with none).
  Too low makes every client share the proxy's address (per-IP limits and lockout then hit everyone). Too high
  lets a client forge `X-Forwarded-For` and pick its own IP, bypassing per-IP limits and lockout.

## Verification

- `backend/test/practice.test.js`: auth boundary; sandbox setup + query, proof the table
  is gone on the next request, syntax error surfaced as feedback, validation; code proxy against a
  fake Piston server (request shape, compile-error mapping); 503 + status without `EXECUTOR_URL`.
- `backend/test/sandbox.test.js`: validator unit tests (no database); the lab tests in the
  SQL sandbox suite. They need `SANDBOX_DB_NAME`, `SANDBOX_DB_USER` and `SANDBOX_DB_PASSWORD` for a
  disposable lab database, and skip if they are missing or name a protected database
  (`SynoraV1`, `SynoraV1_Test`, `SynoraV1_Sandbox`).

Live C/C++ execution is verified only once a Piston runner is reachable.
