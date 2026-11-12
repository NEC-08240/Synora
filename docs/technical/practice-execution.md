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
`COMMIT`, `ROLLBACK`, `BEGIN`/`SAVE TRAN|TRANSACTION|DISTRIBUTED`, `BULK`, `KILL`, `SHUTDOWN`,
`RECONFIGURE`, `GRANT`, `REVOKE`, `DENY`, `USE`, `OPENROWSET`/`OPENQUERY`/`OPENDATASOURCE`,
`CREATE|ALTER|DROP LOGIN|USER`, and `SET`. Two exceptions: the `SET` of a foreign-key action
(`ON DELETE|UPDATE SET NULL|DEFAULT`), and the first `SET` of an `UPDATE <target> SET`. That permit opens
only when `UPDATE` begins a statement (start of input, after `;`, `THEN`, `ELSE`, `BEGIN`, `AS`, `TRY`,
`CATCH`, or a closing `)` as in a CTE or `IF EXISTS(...)`) and is not `UPDATE STATISTICS` or `UPDATE (`;
it closes at the next `;` or after that one `SET`. A second `SET` (`UPDATE t SET a=1 SET DATEFIRST 1`) is
refused. `GLOBAL` is refused anywhere (a `DECLARE c CURSOR GLOBAL` outlives the rollback on the pooled
connection; default cursor scope is also GLOBAL unless the database says otherwise, so the keyword ban is partial).
Number literals are lexed like SQL Server: `0x`, `1e0`, `1.5e3`, `.5` are consumed as numbers and the keyword
after them is still seen (`SELECT 0xSET DATEFIRST 3` runs as `SELECT 0x` then `SET`). Identifiers with digits
(`col1`, `t2`, `a1b`) are unaffected.
A bare exponent also counts (lab-verified: `SELECT 1eSET DATEFIRST 3`, `1.5eSET`, `.5eSET`, `1e+SET` all ran the SET), while `12EXEC x` is `12E` then alias `XEC` on the server, so it is allowed.
Line comments (`--`) end at a bare CR, U+0085 and U+2028 as well as LF (lab-verified: the SET after each ran); the tokenizer ends them at all of those and U+2029.
Known false positives (all refused, rewrite with `;` or a parenthesised condition): `IF 1=1 UPDATE t SET ...`,
`IF @x IS NULL UPDATE ...`, `WHILE ... UPDATE ...`, `BEGIN ... END UPDATE` without a `;`, and a trigger body
`AS BEGIN SET NOCOUNT ON ...` (SET is refused there).
The validator is a text scan and can be wrong in both directions. It is defense in depth, not a security
boundary; the database permissions above are the control. A student can write SQL the validator misses, and
the database must still refuse it.

### Per-run behaviour

- Each run is one transaction: `setupScript`, then the student `sql`. Results are streamed and
  never buffered past 200 rows (`config.practice.maxRows`); the 201st row cancels the request and
  sets `truncated: true`.
- **A fresh SQL session per run.** Every run opens its own single-connection pool (connect timeout 5 s), runs
  `BEGIN TRANSACTION`, the setup and student batches, `ROLLBACK`, the leak sweep, and then closes the pool in a
  `finally`. No SET option, cursor, CONTEXT_INFO or temp object can reach the next student, because the next
  student gets a different session (mssql/tedious never resets pooled sessions, which is why a shared pool was
  not safe if the validator was bypassed). The validator stays as defense in depth.
- The transaction is plain T-SQL on that connection (not `sql.Transaction`, which pins the connection so that
  `pool.close()` waits on it). The rollback is always attempted, then the leak detector lists `sbx` user
  objects (tables, views, procedures, functions, synonyms, sequences, triggers, foreign keys) and drops any
  that escaped, with a `console.warn` per object. The baseline is empty (`SHIPPED_OBJECTS`).
- Timeout (`config.practice.sqlTimeoutMs`, 5 s), cancel, SQL error, failed rollback and failed leak sweep all end
  the same way: the connection is closed, which ends the session and rolls back server-side whatever is
  still open. Close errors are logged, never thrown. If a close takes longer than 5 s (a wedged cancel) it is
  logged and the slot is released while the close continues in the background. A connect failure rejects the
  request (nothing to close beyond the half-open pool).
- Cost: one login handshake per run (tens of milliseconds on a local server, not measured separately; the
  sandbox suite's simple runs finish in well under 100 ms). The old pool recycle code and the
  `needsLeakCheck` flag are gone: a bad connection is never reused, so there is nothing to recycle, and the leak
  sweep after every rollback replaces the deferred check.
- Runs are **serial by default** (`SANDBOX_CONCURRENCY=1`), because students share the `sbx` schema
  and overlapping runs would see each other's uncommitted objects. Up to `SANDBOX_QUEUE_MAX`
  (default 8) requests wait in memory; the next one gets `429`. Changing `SANDBOX_CONCURRENCY`
  above 1 is not supported.

### Observed results (lab run, mssql 12.7.14, tedious)

- Pool reset (corrected, lab run with pool size 1, same `@@SPID`): mssql/tedious does NOT reset a pooled session
  (`tedious` has `reset()` but `mssql/lib/tedious` never calls it). With `0xSET DATEFIRST 3`, `0xSET LOCK_TIMEOUT 77`,
  `1e0SET DATEFIRST 4`, `.5SET DATEFIRST 6`, `0xSET NOCOUNT ON` the option really changed and stayed after the
  rollback and across later requests; a `CURSOR GLOBAL` stayed open in `sys.dm_exec_cursors`. An earlier test
  that read `DATEFIRST` back as `7` on the next request is not reproduced by this finding and is unexplained.
  Superseded by the per-run connection above (tests plant SET/LOCK_TIMEOUT/CONTEXT_INFO/GLOBAL cursor with the
  validator bypassed and the next run sees defaults). The finding is kept as the reason for the design.
  Consequence (before that change): a validator bypass leaks session state to the next student, so the validator is a real
  guard, not decoration.
  Raw `0xUSE`/`0xKILL`/`0xGRANT`/`0xSHUTDOWN`/`0xROLLBACK`/`0xOPENROWSET` were not executed (reasoned from the SET
  result that the keyword after a number literal is parsed as a statement); they are covered by the validator test.
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
- `trustServerCertificate` follows `DB_TRUST_SERVER_CERT` (default false); each sandbox connection uses the
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
| 2,000,000-row `SELECT INTO #big` | hit the 5 s timeout plus a failed 5 s cancel (about 10 s), rollback failed, connection closed; next run fine (measured before the per-run connection change) |
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

- **Victim lockout.** About 20 wrong guesses for an email (per-email scope) lock that account's sign-in for 15
  minutes from any IP, even with the right password. Renewable by repeating. No admin unlock exists. Mitigations:
  short lock, per-IP login rate limit, pair/IP scopes. Waiting out the lock or restarting the process clears it.
- **Faculty authoring conflict.** Topics belong to the subject, so faculty can author only if assigned in every
  batch that has the subject. Two faculty sharing a subject across batches cannot author until the admin assigns
  the same faculty to all of those batches (or removes the other assignment). Read access is unaffected.
- **Lockout tracker eviction.** At 10,000 tracked keys, single-failure unlocked entries are evicted first, so
  displacing a victim's counter needs thousands of distinct IPs. Flooding with locked entries (hard bound 20,000)
  makes each overflow rescan the map (O(n)); only the oldest locked entries are dropped past that bound.
- **Refund can lift an IP lock early.** A correct sign-in returns its reserved per-IP slot, so it can reduce the
  per-IP count below the lock threshold and end an IP lock before its timer. Accepted; the pair and email scopes
  still apply to the guessed account.
- Failure counters are cleared only after the Status check, so suspended accounts no longer reset them.

## Running the sandbox tests in CI

No GitHub Actions workflow exists in this repo. Set `REQUIRE_SANDBOX_TESTS=1` in CI so a missing lab database
(`SANDBOX_DB_*`), `sqlcmd` or Windows authentication fails the run instead of skipping the sandbox tests.
`npm run test:ci` does this (`backend/.env.ci`); `REQUIRE_SANDBOX_TESTS` accepts `1` or `true`.
Unset, they skip and a warning is printed at start; the skipped count appears in the node test summary.

## Verification

- `backend/test/practice.test.js`: auth boundary; sandbox setup + query, proof the table
  is gone on the next request, syntax error surfaced as feedback, validation; code proxy against a
  fake Piston server (request shape, compile-error mapping); 503 + status without `EXECUTOR_URL`.
- `backend/test/sandbox.test.js`: validator unit tests (no database); the lab tests in the
  SQL sandbox suite. They need `SANDBOX_DB_NAME`, `SANDBOX_DB_USER` and `SANDBOX_DB_PASSWORD` for a
  disposable lab database, and skip if they are missing or name a protected database
  (`SynoraV1`, `SynoraV1_Test`, `SynoraV1_Sandbox`).

Live C/C++ execution is verified only once a Piston runner is reachable.
