/**
 * SQL sandbox regression tests. They run against the lab database named by SANDBOX_DB_NAME
 * (see docs/technical/practice-execution.md, "Running the sandbox tests"), never the app DB.
 * This file does not import helpers.js, so it never touches the app or test databases.
 */
import { describe, test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import sql from 'mssql';
import { config } from '../src/config.js';
import { runSql, closeSandboxPool, findForbiddenStatement } from '../src/practice/sql.js';

const PROTECTED_DBS = ['SynoraV1', 'SynoraV1_Test', 'SynoraV1_Sandbox'];
// Permission denials only. SQL Server reports a denied dbo create as "does not exist or you do not
// have permission" (Msg 2760); dbo always exists, so that text means denied here.
const DENIED = /permission (was )?denied|not able to access|blocked access|do not have permission/i;
const REQUIRED_ENV = ['SANDBOX_DB_NAME', 'SANDBOX_DB_USER', 'SANDBOX_DB_PASSWORD'];

function skipReason() {
  const missing = REQUIRED_ENV.filter((key) => !process.env[key]);
  if (missing.length) return `lab env missing: ${missing.join(', ')}`;
  if (PROTECTED_DBS.includes(process.env.SANDBOX_DB_NAME)) {
    return `SANDBOX_DB_NAME=${process.env.SANDBOX_DB_NAME} is protected; point it at the lab database`;
  }
  return false;
}

const directConfig = {
  ...config.practice.sandboxDb,
  options: { encrypt: true, trustServerCertificate: config.db.trustServerCertificate },
};

/** Runs a batch as the sandbox login on a fresh connection, outside the sandbox runner. */
async function asSandbox(text) {
  const pool = await new sql.ConnectionPool(directConfig).connect();
  try {
    return await pool.request().query(text);
  } finally {
    await pool.close();
  }
}

/** Returns the error the sandbox login gets for a batch, or null if it succeeds. */
async function deniedError(text) {
  try {
    await asSandbox(text);
    return null;
  } catch (err) {
    return err;
  }
}

async function objectExists(name) {
  const { recordset } = await asSandbox(`SELECT OBJECT_ID(N'${name}') AS id`);
  return recordset[0].id !== null;
}

/** Windows-auth sysadmin sqlcmd, used only to create and drop disposable peer/check databases. */
const sqlcmdAdmin = (args) => spawnSync('sqlcmd', ['-S', process.env.DB_SERVER ?? 'localhost', '-E', '-C', '-b', ...args], { encoding: 'utf8' });
const adminAvailable = sqlcmdAdmin(['-Q', 'SELECT 1']).status === 0;
const dropDbSql = (db) => `IF DB_ID(N'${db}') IS NOT NULL BEGIN ALTER DATABASE [${db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [${db}]; END`;

/** Drops every user object in sbx and dbo so each test starts from an empty schema. */
async function clearSandbox() {
  await asSandbox(`
    DECLARE @sql NVARCHAR(MAX) = N'';
    SELECT @sql += N'DROP ' + CASE type WHEN 'U' THEN N'TABLE ' WHEN 'V' THEN N'VIEW ' WHEN 'P' THEN N'PROCEDURE ' END
      + QUOTENAME(SCHEMA_NAME(schema_id)) + N'.' + QUOTENAME(name) + N';'
    FROM sys.objects
    WHERE is_ms_shipped = 0 AND type IN ('U', 'V', 'P') AND SCHEMA_NAME(schema_id) IN (N'sbx', N'dbo');
    IF LEN(@sql) > 0 EXEC sp_executesql @sql;`);
}

describe('statement validator (no database needed)', () => {
  test('refuses EXEC, sp_/xp_ names, transaction control and SET outside an UPDATE', () => {
    assert.equal(findForbiddenStatement("EXEC('COM'+'MIT')"), 'EXEC');
    assert.equal(findForbiddenStatement("master..xp_cmdshell 'dir'"), 'xp_cmdshell');
    assert.equal(findForbiddenStatement('ROLLBACK; CREATE TABLE x (id INT)'), 'ROLLBACK');
    assert.equal(findForbiddenStatement('BEGIN TRANSACTION'), 'BEGIN TRANSACTION');
    assert.equal(findForbiddenStatement('SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('DROP USER bob'), 'DROP USER');
  });

  test('a second SET in the same statement is refused even without a semicolon', () => {
    assert.equal(findForbiddenStatement('UPDATE t SET a = 1 SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('UPDATE t SET a = 1; SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('UPDATE t SET a = 1'), null);
  });

  test('SET after UPDATE STATISTICS, FOR UPDATE, AFTER UPDATE or IF UPDATE() is refused', () => {
    assert.equal(findForbiddenStatement('UPDATE STATISTICS sbx.t\nSET LOCK_TIMEOUT 0'), 'SET');
    assert.equal(findForbiddenStatement(
      'DECLARE c CURSOR FOR SELECT a FROM sbx.t FOR UPDATE\nSET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED'), 'SET');
    assert.equal(findForbiddenStatement('DECLARE c CURSOR FOR SELECT a FROM sbx.t FOR UPDATE OF a SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('CREATE TRIGGER sbx.tr ON sbx.t AFTER UPDATE AS SET NOCOUNT ON; SELECT 1'), 'SET');
    assert.equal(findForbiddenStatement('CREATE TRIGGER sbx.tr ON sbx.t AFTER INSERT, UPDATE AS SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('CREATE TRIGGER sbx.tr ON sbx.t AFTER UPDATE, DELETE AS SET NOCOUNT ON'), 'SET');
    assert.equal(findForbiddenStatement('IF UPDATE(a) SET XACT_ABORT ON'), 'SET');
  });

  test('real UPDATE ... SET forms are still allowed', () => {
    for (const ok of [
      'UPDATE sbx.t SET a=1',
      'UPDATE t SET a = 1 WHERE id = 2',
      'UPDATE TOP (5) sbx.t SET a=1',
      'UPDATE TOP (5) PERCENT t SET a=1',
      'UPDATE x SET a=1 FROM sbx.t x JOIN sbx.u y ON x.id = y.id',
      'UPDATE sbx.t AS x SET a=1',
      'UPDATE sbx.t WITH (TABLOCK) SET a=1',
      'UPDATE [dbo].[t] SET [set] = 1',
      'UPDATE #tmp SET a=1',
      'MERGE sbx.t AS d USING sbx.u AS s ON d.id = s.id WHEN MATCHED THEN UPDATE SET d.a = s.a;',
    ]) assert.equal(findForbiddenStatement(ok), null, ok);
  });

  test('keywords inside comments and string literals are ignored', () => {
    assert.equal(findForbiddenStatement('/* EXEC xp_cmdshell */ SELECT 1'), null);
    assert.equal(findForbiddenStatement('SELECT 1 /* a /* nested */ EXEC */'), null);
    assert.equal(findForbiddenStatement("SELECT 'it''s EXEC' AS s -- COMMIT"), null);
  });

  test('a column named committed is not a false positive', () => {
    assert.equal(findForbiddenStatement('SELECT committed FROM t_committed'), null);
  });

  test('bracketed keyword identifiers are allowed; bracketed sp_/xp_ names are refused', () => {
    assert.equal(findForbiddenStatement('SELECT [set], [user] FROM t'), null);
    assert.equal(findForbiddenStatement("[xp_cmdshell] 'x'"), 'xp_cmdshell');
  });

  test('referential actions ON DELETE/UPDATE SET NULL and SET DEFAULT are allowed', () => {
    assert.equal(findForbiddenStatement('CREATE TABLE c (a INT REFERENCES p(id) ON DELETE SET NULL)'), null);
    assert.equal(findForbiddenStatement('CREATE TABLE c (a INT REFERENCES p(id) ON UPDATE SET DEFAULT)'), null);
  });
});

describe('SQL sandbox', { skip: skipReason() }, () => {
  before(clearSandbox);
  after(async () => {
    await clearSandbox();
    await closeSandboxPool();
  });

  describe('statement validation (defense in depth; permissions are the real control)', () => {
    test('COMMIT in setupScript is rejected and the table does not persist', async () => {
      const result = await runSql({
        sql: 'SELECT 1 AS ok',
        setupScript: 'CREATE TABLE persist_probe (id INT); COMMIT;',
      });
      assert.match(result.error ?? '', /COMMIT is not allowed/);
      assert.equal(await objectExists('sbx.persist_probe'), false);
    });

    test("EXEC('COM'+'MIT') is rejected", async () => {
      const result = await runSql({ sql: "EXEC('COM'+'MIT')" });
      assert.match(result.error ?? '', /EXEC is not allowed/);
    });

    test('sp_executesql is rejected', async () => {
      const result = await runSql({ sql: "sp_executesql N'SELECT 1 AS ok'" });
      assert.match(result.error ?? '', /sp_executesql is not allowed/i);
    });

    test('ROLLBACK followed by CREATE TABLE is rejected and the table does not persist', async () => {
      const result = await runSql({ sql: 'ROLLBACK; CREATE TABLE escape_probe (id INT)' });
      assert.match(result.error ?? '', /ROLLBACK is not allowed/);
      assert.equal(await objectExists('sbx.escape_probe'), false);
    });

    test('a column named committed is not a false positive', async () => {
      const result = await runSql({
        sql: 'SELECT committed FROM t_committed',
        setupScript: 'CREATE TABLE t_committed (committed INT); INSERT INTO t_committed VALUES (7);',
      });
      assert.equal(result.error, null);
      assert.deepEqual(result.rows, [{ committed: 7 }]);
    });

    test('SET options are rejected but UPDATE ... SET still works', async () => {
      const nocount = await runSql({ sql: 'SET NOCOUNT ON' });
      assert.match(nocount.error ?? '', /SET is not allowed/);
      const datefirst = await runSql({ sql: 'SET DATEFIRST 7' });
      assert.match(datefirst.error ?? '', /SET is not allowed/);
      const update = await runSql({
        sql: 'UPDATE u_probe SET v = 5; SELECT v FROM u_probe',
        setupScript: 'CREATE TABLE u_probe (id INT, v INT); INSERT INTO u_probe VALUES (1, 0);',
      });
      assert.equal(update.error, null);
      assert.deepEqual(update.rows, [{ v: 5 }]);
    });
  });

  describe('permissions as the sandbox login', () => {
    test('CREATE PROCEDURE is denied', async () => {
      const err = await deniedError('CREATE PROCEDURE sbx.p_probe AS SELECT 1');
      assert.ok(err, 'CREATE PROCEDURE should be denied');
      assert.match(err.message, DENIED);
    });

    test('creating objects in dbo is denied (ALTER on dbo)', async () => {
      const err = await deniedError('CREATE TABLE dbo.alter_probe (id INT)');
      assert.ok(err, 'CREATE TABLE dbo.* should be denied');
      assert.match(err.message, DENIED);
    });

    describe('against a disposable peer database', { skip: !adminAvailable && 'sqlcmd with Windows auth unavailable' }, () => {
      const peer = `${process.env.SANDBOX_DB_NAME}_peer`;
      before(() => {
        const made = sqlcmdAdmin(['-Q', `${dropDbSql(peer)}; CREATE DATABASE [${peer}]`]);
        assert.equal(made.status, 0, 'peer database created');
        assert.equal(sqlcmdAdmin(['-d', peer, '-Q', 'CREATE TABLE dbo.secret (id int); INSERT dbo.secret VALUES (1)']).status, 0);
      });
      after(() => { sqlcmdAdmin(['-Q', dropDbSql(peer)]); });

      test('cross-database SELECT is denied (the peer exists, so this is a real permission denial)', async () => {
        const err = await deniedError(`SELECT TOP 1 id FROM [${peer}].dbo.secret`);
        assert.ok(err, 'SELECT from another database should be denied');
        assert.match(err.message, DENIED);
        assert.doesNotMatch(err.message, /Invalid object name|Cannot open database/i, 'not a missing-object error');
      });

      test('three-part names into the peer and msdb are denied', async () => {
        for (const target of [`[${peer}].dbo.secret`, 'msdb.dbo.sysjobs']) {
          const err = await deniedError(`SELECT TOP 1 * FROM ${target}`);
          assert.ok(err, `${target} should be denied`);
          assert.match(err.message, DENIED, target);
        }
      });
    });

    test('master.sys.databases shows only the sandbox, master and tempdb (VIEW ANY DATABASE is denied by setup)', async () => {
      const { recordset } = await asSandbox('SELECT name FROM master.sys.databases');
      const names = recordset.map((row) => row.name).sort();
      assert.deepEqual(names, ['master', 'tempdb', process.env.SANDBOX_DB_NAME].sort());
    });

    test('master.sys.sql_logins is listable but never reveals password hashes', async () => {
      // Recorded: the login can read login NAMES (sa, itself); password_hash is NULL without CONTROL SERVER.
      const { recordset } = await asSandbox('SELECT name, password_hash FROM master.sys.sql_logins');
      assert.ok(recordset.every((row) => row.password_hash === null));
    });

    test('xp_cmdshell is denied', async () => {
      const err = await deniedError("EXEC master..xp_cmdshell 'echo probe'");
      assert.ok(err, 'xp_cmdshell should be denied');
      assert.match(err.message, DENIED);
    });
  });

  describe('runner limits and recovery', () => {
    test('5M-row recursive CTE returns at most maxRows with truncated=true and bounded memory', async () => {
      const heapBefore = process.memoryUsage().heapUsed;
      const result = await runSql({
        sql: 'WITH n AS (SELECT 1 AS i UNION ALL SELECT i + 1 FROM n WHERE i < 5000000) SELECT i FROM n OPTION (MAXRECURSION 0)',
      });
      const heapGrowthMb = (process.memoryUsage().heapUsed - heapBefore) / 1048576;
      assert.equal(result.error, null);
      assert.equal(result.rows.length, config.practice.maxRows);
      assert.equal(result.truncated, true);
      assert.ok(heapGrowthMb < 100, `heap grew ${heapGrowthMb.toFixed(1)} MB`);
    });

    test("WAITFOR DELAY '00:00:20' aborts near sqlTimeoutMs and the pool recovers", async () => {
      const started = Date.now();
      const slow = await runSql({ sql: "WAITFOR DELAY '00:00:20'; SELECT 1 AS late" });
      const elapsed = Date.now() - started;
      assert.match(slow.error ?? '', /Timeout|ETIMEOUT|Request failed/i);
      assert.ok(elapsed < config.practice.sqlTimeoutMs + 5000, `took ${elapsed}ms`);
      const next = await runSql({ sql: 'SELECT 1 AS ok' });
      assert.equal(next.error, null);
      assert.deepEqual(next.rows, [{ ok: 1 }]);
    });

    test('three simultaneous requests creating table t do not interfere', async () => {
      const setupScript = 'CREATE TABLE t (id INT); INSERT INTO t VALUES (1);';
      const results = await Promise.all([1, 2, 3].map((n) =>
        runSql({ sql: `SELECT ${n} AS n, COUNT(*) AS c FROM t`, setupScript })));
      results.forEach((result, index) => {
        assert.equal(result.error, null, `request ${index + 1}`);
        assert.deepEqual(result.rows, [{ n: index + 1, c: 1 }]);
      });
    });

    test('a normal SELECT works and its setup is rolled back without leak cleanup', async (t) => {
      const warn = t.mock.method(console, 'warn', () => {});
      const result = await runSql({
        sql: 'SELECT id, name FROM rb_probe ORDER BY id',
        setupScript: "CREATE TABLE rb_probe (id INT, name NVARCHAR(20)); INSERT INTO rb_probe VALUES (1, N'a'), (2, N'b');",
      });
      assert.equal(result.error, null);
      assert.deepEqual(result.columns, ['id', 'name']);
      assert.equal(result.rowCount, 2);
      assert.equal(await objectExists('sbx.rb_probe'), false);
      assert.equal(warn.mock.callCount(), 0);
    });

    test('leak detector removes an object planted outside the transaction and warns', async (t) => {
      await asSandbox('CREATE TABLE sbx.planted (id INT)');
      const warn = t.mock.method(console, 'warn', () => {});
      const result = await runSql({ sql: 'SELECT 1 AS ok' });
      assert.equal(result.error, null);
      assert.equal(await objectExists('sbx.planted'), false);
      assert.ok(warn.mock.calls.some((call) => String(call.arguments[0]).includes('planted')));
    });

    test('a 10-request burst gets at least one 429 (1 running + 8 queued by default)', async () => {
      const results = await Promise.allSettled(Array.from({ length: 10 }, () =>
        runSql({ sql: "WAITFOR DELAY '00:00:01'; SELECT 1 AS ok" })));
      const refused = results.filter((r) => r.status === 'rejected');
      assert.ok(refused.length >= 1, 'expected at least one request refused by the queue');
      assert.ok(refused.every((r) => r.reason.status === 429), 'refused requests must be HTTP 429');
    });
  });

  // Observed behaviour, not an assumption. A direct pool (max 1) bypasses the validator on purpose.
  describe('SET state across pooled connections (validator bypassed)', () => {
    test('SET DATEFIRST on a reused pooled connection: observed value on the next request', async () => {
      const pool = await new sql.ConnectionPool({
        ...directConfig,
        pool: { max: 1, min: 0, idleTimeoutMillis: 30000 },
      }).connect();
      try {
        const first = await pool.request().query('SET DATEFIRST 1; SELECT @@SPID AS spid');
        const second = await pool.request().query('SELECT @@SPID AS spid, @@DATEFIRST AS d');
        // Proves the same pooled connection served both requests before reading the SET state.
        assert.equal(second.recordset[0].spid, first.recordsets[0][0].spid, 'requests must share a connection');
        // Observed on this server (mssql 12.7.14 + tedious): the SET does not survive the next request.
        assert.equal(second.recordset[0].d, 7, 'observed: DATEFIRST reset to 7 on the next request');
      } finally {
        await pool.close();
      }
    });
  });
});

// Setup-script assertion: runs sqlcmd as the Windows admin against a throwaway DB (needs sqlcmd + admin; skipped otherwise).
describe('sandbox_setup.sql dbo-objects assertion', { skip: !process.env.SANDBOX_DB_NAME && 'lab env not set' }, () => {
  const db = `${process.env.SANDBOX_DB_NAME}_setupchk`;
  const login = `${db}_l`;
  const script = fileURLToPath(new URL('../../database/sandbox_setup.sql', import.meta.url));
  const admin = sqlcmdAdmin;
  const setup = () => admin(['-v', `SANDBOX_DB=${db}`, `SANDBOX_LOGIN=${login}`, `SANDBOX_PASSWORD=${randomBytes(12).toString('hex')}Aa1!`, '-i', script]);
  const adminOk = adminAvailable;

  after(() => {
    admin(['-Q', `${dropDbSql(db)}; IF SUSER_ID(N'${login}') IS NOT NULL DROP LOGIN [${login}]`]);
  });

  test('succeeds on an empty database, fails once a dbo object exists', { skip: !adminOk && 'sqlcmd with Windows auth unavailable' }, () => {
    assert.equal(setup().status, 0, 'empty database passes');
    assert.equal(admin(['-d', db, '-Q', 'CREATE TABLE dbo.owned (a int)']).status, 0);
    const second = setup();
    assert.notEqual(second.status, 0, 'a dbo object makes setup fail under -b');
    assert.match(second.stdout + second.stderr, /user objects in schema dbo/);
  });
});
