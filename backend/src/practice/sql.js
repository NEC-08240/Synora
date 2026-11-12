/**
 * Student SQL sandbox. Runs against a SEPARATE database with a low-privilege login (never the app
 * DB). Each run is one transaction that is rolled back; a leak detector then removes any sbx object
 * that escaped it. The database permissions in database/sandbox_setup.sql are the real control.
 * findForbiddenStatement() is defense in depth and NOT an isolation boundary. Runs are serial by
 * default because students share the sbx schema. See docs/technical/practice-execution.md.
 */
import sql from 'mssql';
import { config } from '../config.js';
import { HttpError, tooManyRequests } from '../http.js';

const CONNECT_TIMEOUT_MS = 5000;
const CLOSE_WARN_MS = 5000;
// Shortcut: the setup script ships no sbx objects, so the baseline is empty. Upgrade: list any
// template-owned sbx object names here if the setup ever creates one.
const SHIPPED_OBJECTS = new Set();

/**
 * A brand-new single-connection pool for ONE run, so no SET option, cursor or CONTEXT_INFO from an
 * earlier run can exist (mssql/tedious never resets pooled sessions). Closed by the caller.
 */
async function openRunConnection() {
  const cfg = config.practice.sandboxDb;
  if (!cfg) throw new HttpError(503, 'The SQL sandbox is not configured on this server');
  const pool = new sql.ConnectionPool({
    ...cfg,
    connectionTimeout: CONNECT_TIMEOUT_MS,
    requestTimeout: config.practice.sqlTimeoutMs,
    options: { encrypt: true, trustServerCertificate: config.db.trustServerCertificate },
    pool: { max: 1, min: 0 },
  });
  try {
    return await pool.connect();
  } catch (err) {
    await closeRunConnection(pool, 'connect failed');
    throw err;
  }
}

/**
 * Never throws and never waits longer than CLOSE_WARN_MS: pool.close() waits for a checked-out connection, so a
 * wedged one (failed cancel) must not hold the sandbox slot. It is logged and keeps closing in the background.
 */
async function closeRunConnection(pool, reason) {
  let timer;
  const closing = pool.close().catch((err) => console.error(`sandbox: connection close failed (${reason}): ${err.message}`));
  const stalled = new Promise((resolve) => {
    timer = setTimeout(() => {
      console.error(`sandbox: connection still closing ${CLOSE_WARN_MS} ms after run (${reason})`);
      resolve();
    }, CLOSE_WARN_MS);
  });
  await Promise.race([closing, stalled]);
  clearTimeout(timer);
}


export const isSqlSandboxAvailable = () => Boolean(config.practice.sandboxDb);

const SP_XP_PREFIX = /^(sp|xp)_/i;
const SIMPLE_FORBIDDEN = new Set([
  'EXEC', 'EXECUTE', 'COMMIT', 'ROLLBACK', 'BULK', 'KILL', 'SHUTDOWN', 'RECONFIGURE',
  'GRANT', 'REVOKE', 'DENY', 'USE', 'OPENROWSET', 'OPENQUERY', 'OPENDATASOURCE',
]);
const TRANSACTION_WORDS = new Set(['TRAN', 'TRANSACTION', 'DISTRIBUTED']);
const WORD = /[\p{L}_@#][\p{L}\p{N}_@#$]*/uy;
// SQL Server ends a number where the letters stop fitting it (a bare exponent `1e` counts), so `0xSET` is `0x` then SET.
const NUMBER = /0x[0-9a-f]*|(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d*)?/iy;


/** Index just past the end of a quoted run starting at `start`; a doubled closer is an escape. */
function endOfQuoted(text, start, closer) {
  let i = start + 1;
  while (i < text.length) {
    if (text[i] === closer) {
      if (text[i + 1] !== closer) return i + 1;
      i += 2;
    } else {
      i += 1;
    }
  }
  return text.length;
}

/** Index just past a block comment; SQL Server block comments nest. */
function endOfBlockComment(text, start) {
  let depth = 0;
  let i = start;
  while (i < text.length) {
    if (text.startsWith('/*', i)) {
      depth += 1;
      i += 2;
    } else if (text.startsWith('*/', i)) {
      depth -= 1;
      i += 2;
      if (depth === 0) return i;
    } else {
      i += 1;
    }
  }
  return text.length;
}

/**
 * Splits T-SQL into words, bracketed/quoted identifiers and ';'. Comments and string literals are
 * dropped, so a keyword inside them never counts.
 */
function tokenize(text) {
  const tokens = [];
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (text.startsWith('--', i)) {
      // The server also ends a comment at a bare CR, U+0085 and U+2028 (lab-verified); stop at all line breaks.
      const newline = text.slice(i).search(/[\n\r\x85\u2028\u2029]/);
      i = newline === -1 ? text.length : i + newline;
    } else if (text.startsWith('/*', i)) {
      i = endOfBlockComment(text, i);
    } else if (ch === "'") {
      i = endOfQuoted(text, i, "'");
    } else if (ch === '[' || ch === '"') {
      const end = endOfQuoted(text, i, ch === '[' ? ']' : '"');
      tokens.push({ kind: 'ident', value: text.slice(i + 1, end).replace(/["\]]$/, '') });
      i = end;
    } else if (ch === ';') {
      tokens.push({ kind: 'semi' });
      i += 1;
    } else if (ch === ',') {
      tokens.push({ kind: 'comma' });
      i += 1;
    } else if (ch === '(' || ch === ')') {
      tokens.push({ kind: 'paren', value: ch });
      i += 1;
    } else {
      NUMBER.lastIndex = i;
      const num = NUMBER.exec(text);
      if (num) {
        i = NUMBER.lastIndex;
        continue;
      }
      WORD.lastIndex = i;
      const match = WORD.exec(text);
      if (match) {
        tokens.push({ kind: 'word', value: match[0] });
        i = WORD.lastIndex;
      } else {
        i += 1;
      }
    }
  }
  return tokens;
}

const wordAt = (tokens, index) => (tokens[index]?.kind === 'word' ? tokens[index].value.toUpperCase() : '');

/** `ON DELETE SET NULL` / `ON UPDATE SET DEFAULT` are referential actions, not SET options. */
function isReferentialAction(tokens, index) {
  return ['DELETE', 'UPDATE'].includes(wordAt(tokens, index - 1))
    && wordAt(tokens, index - 2) === 'ON'
    && ['NULL', 'DEFAULT'].includes(wordAt(tokens, index + 1));
}

// Allow-list: UPDATE starts a DML statement only after one of these. Anything else (BEFORE/AFTER/FOR/ON/
// OF/IF/AND, a comma in a trigger event list, '(' ...) is a trigger event, cursor clause, FK action or
// IF UPDATE(col) test and does not open the SET permit. ')' covers WITH c AS (...) UPDATE and IF EXISTS(...) UPDATE.
// Known false positives, refused on purpose: `IF 1=1 UPDATE ...` and a second UPDATE after a statement
// that is not separated by ';'.
const DML_PRECEDERS = new Set(['THEN', 'ELSE', 'BEGIN', 'AS', 'TRY', 'CATCH']);

/** True only when this UPDATE begins a real `UPDATE <target> SET` statement. */
function isDmlUpdate(tokens, index) {
  const prev = tokens[index - 1];
  const startsStatement = prev === undefined || prev.kind === 'semi' || (prev.kind === 'paren' && prev.value === ')')
    || (prev.kind === 'word' && DML_PRECEDERS.has(prev.value.toUpperCase()));
  const next = tokens[index + 1];
  return startsStatement && next !== undefined && next.kind !== 'paren' && wordAt(tokens, index + 1) !== 'STATISTICS';
}

/**
 * Returns the name of the first statement the sandbox refuses (for example "EXEC" or "SET"), or
 * null. Defense in depth only: the database permissions are the real control. A single UPDATE
 * arms one SET; a second SET in the same statement (no semicolon needed) is refused.
 */
export function findForbiddenStatement(text) {
  const tokens = tokenize(text);
  let setPermits = 0;
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];
    if (token.kind === 'semi') {
      setPermits = 0;
    } else if (token.kind === 'paren' || token.kind === 'comma') {
      continue;
    } else if (token.kind === 'ident') {
      if (SP_XP_PREFIX.test(token.value)) return token.value;
    } else {
      const word = token.value.toUpperCase();
      const next = wordAt(tokens, i + 1);
      if (SP_XP_PREFIX.test(token.value)) return token.value;
      if (SIMPLE_FORBIDDEN.has(word)) return word;
      // A GLOBAL cursor survives the rollback on a pooled connection (pool does not reset sessions).
      if (word === 'GLOBAL') return word;
      if ((word === 'BEGIN' || word === 'SAVE') && TRANSACTION_WORDS.has(next)) return `${word} ${next}`;
      if (['CREATE', 'ALTER', 'DROP'].includes(word) && ['LOGIN', 'USER'].includes(next)) return `${word} ${next}`;
      if (word === 'UPDATE' && isDmlUpdate(tokens, i)) setPermits = 1;
      if (word === 'SET' && !isReferentialAction(tokens, i)) {
        if (setPermits === 0) return 'SET';
        setPermits = 0;
      }
    }
  }
  return null;
}

const failure = (message) => ({ columns: [], rows: [], rowCount: 0, truncated: false, error: message });

// Serial runs by default (see config.practice.sandboxConcurrency). `running` counts jobs holding a slot.
let running = 0;
const waiting = [];

/** Runs `job` in a slot; at most sandboxQueueMax requests wait, and the rest are refused with 429. */
async function runQueued(job) {
  const { sandboxConcurrency, sandboxQueueMax } = config.practice;
  if (running < sandboxConcurrency) {
    running += 1;
  } else if (waiting.length < sandboxQueueMax) {
    await new Promise((resolve) => waiting.push(resolve)); // the finishing job hands over its slot
  } else {
    throw tooManyRequests('The SQL sandbox is busy. Try again in a moment.');
  }
  try {
    return await job();
  } finally {
    const next = waiting.shift();
    if (next) next();
    else running -= 1;
  }
}

/**
 * Runs one batch in stream mode so rows are never buffered past maxRows. Resolves on 'done' only:
 * in stream mode mssql emits 'error' and then 'done', and the batch promise never rejects.
 */
function streamBatch(request, text, { keepRows }) {
  const { maxRows } = config.practice;
  const out = { columns: [], rows: [], rowCount: 0, truncated: false, error: null, aborted: false };
  let recordsetIndex = -1;
  let stopped = false;
  request.stream = true;
  return new Promise((resolve, reject) => {
    request.on('recordset', (columns) => {
      recordsetIndex += 1;
      if (recordsetIndex === 0) out.columns = Object.keys(columns);
    });
    request.on('row', (row) => {
      if (!keepRows || recordsetIndex !== 0 || stopped) return;
      if (out.rows.length < maxRows) {
        out.rows.push(row);
        return;
      }
      // The row past maxRows proves truncation: cancel so the server stops producing rows.
      out.truncated = true;
      stopped = true;
      request.cancel();
    });
    request.on('error', (err) => {
      if (stopped && err.code === 'ECANCEL') return; // our own cancel after the truncation row
      out.error ??= err;
      if (err.code === 'ETIMEOUT' || err.code === 'ECANCEL') out.aborted = true;
    });
    request.on('done', ({ rowsAffected }) => {
      out.rowCount = recordsetIndex >= 0 ? out.rows.length : (rowsAffected ?? []).reduce((a, b) => a + b, 0);
      resolve(out);
    });
    request.batch(text).catch(reject);
  });
}

// Catalog query for every sbx object a rolled-back run could have left behind (and their parents).
const LEAK_QUERY = `
  SELECT o.name, CAST(NULL AS sysname) AS parent, RTRIM(o.type) AS kind
  FROM sys.objects o
  WHERE o.is_ms_shipped = 0 AND SCHEMA_NAME(o.schema_id) = N'sbx'
    AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF', 'SN', 'SO')
  UNION ALL
  SELECT fk.name, OBJECT_NAME(fk.parent_object_id), 'F'
  FROM sys.foreign_keys fk
  WHERE fk.is_ms_shipped = 0 AND OBJECT_SCHEMA_NAME(fk.parent_object_id) = N'sbx'
  UNION ALL
  SELECT tr.name, OBJECT_NAME(tr.parent_id), 'TR'
  FROM sys.triggers tr
  WHERE tr.is_ms_shipped = 0 AND OBJECT_SCHEMA_NAME(tr.parent_id) = N'sbx'`;

// Drop order: constraints and triggers first, then dependants, then tables.
const DROP_KEYWORD = {
  F: 'CONSTRAINT', TR: 'TRIGGER', V: 'VIEW', P: 'PROCEDURE', FN: 'FUNCTION', IF: 'FUNCTION',
  TF: 'FUNCTION', SN: 'SYNONYM', SO: 'SEQUENCE', U: 'TABLE',
};
const quoteName = (name) => `[${String(name).replace(/]/g, ']]')}]`;
const dropSql = ({ name, parent, kind }) => (kind === 'F'
  ? `ALTER TABLE ${quoteName('sbx')}.${quoteName(parent)} DROP CONSTRAINT ${quoteName(name)}`
  : `DROP ${DROP_KEYWORD[kind]} ${quoteName('sbx')}.${quoteName(name)}`);

/** Removes sbx objects that survived a rollback. Returns false if any step failed. */
async function removeLeakedObjects(pool) {
  try {
    const { recordset } = await pool.request().query(LEAK_QUERY);
    const order = Object.keys(DROP_KEYWORD);
    const leaks = recordset
      .filter((obj) => !SHIPPED_OBJECTS.has(obj.name))
      .sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
    for (const obj of leaks) {
      console.warn(`sandbox: removing leaked object sbx.${obj.name} (${obj.kind})`);
      await pool.request().query(dropSql(obj));
    }
    return true;
  } catch (err) {
    console.error(`sandbox: leak cleanup failed: ${err.message}`);
    return false;
  }
}

const ROLLBACK_SQL = 'IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION';

/**
 * Rolls back and sweeps leaked objects. Best effort: the caller closes the connection either way, which ends the
 * session and rolls any open transaction back server-side. The transaction is plain T-SQL on the pool's single
 * connection (not sql.Transaction, which pins the connection and would make pool.close() wait on it forever).
 */
async function finishRun(pool, run) {
  if (!run.begun) return;
  try {
    await pool.request().batch(ROLLBACK_SQL);
  } catch (err) {
    console.error(`sandbox: rollback failed: ${err.message}`);
    return;
  }
  await removeLeakedObjects(pool);
}

async function executeInTransaction(pool, { sql: studentSql, setupScript }) {
  const run = { begun: false, aborted: false };
  try {
    await pool.request().batch('BEGIN TRANSACTION');
    run.begun = true;
    if (setupScript.trim()) {
      const setup = await streamBatch(new sql.Request(pool), setupScript, { keepRows: false });
      run.aborted = setup.aborted;
      // SQL errors (syntax, missing table, timeout) are the student's feedback, not a server failure.
      if (setup.error) return failure(setup.error.message);
    }
    const student = await streamBatch(new sql.Request(pool), studentSql, { keepRows: true });
    run.aborted = student.aborted;
    if (student.error) return failure(student.error.message);
    return {
      columns: student.columns,
      rows: student.rows,
      rowCount: student.rowCount,
      truncated: student.truncated,
      error: null,
    };
  } catch (err) {
    run.aborted = true;
    throw err;
  } finally {
    await finishRun(pool, run);
  }
}

async function runOnFreshConnection(studentSql, setupScript) {
  const pool = await openRunConnection();
  try {
    return await executeInTransaction(pool, { sql: studentSql, setupScript });
  } finally {
    await closeRunConnection(pool, 'run finished');
  }
}

/** @returns {Promise<{columns:string[], rows:object[], rowCount:number, truncated:boolean, error:string|null}>} */
export async function runSql({ sql: studentSql, setupScript = '' }) {
  const forbidden = findForbiddenStatement(setupScript) ?? findForbiddenStatement(studentSql);
  if (forbidden) return failure(`${forbidden} is not allowed in the practice sandbox`);
  return runQueued(() => runOnFreshConnection(studentSql, setupScript));
}

/** Test seam: same queue and fresh connection, but WITHOUT the validator (to plant session state). */
export const runSqlUnvalidatedForTests = ({ sql: studentSql, setupScript = '' }) =>
  runQueued(() => runOnFreshConnection(studentSql, setupScript));

/** Kept for callers; there is no shared pool any more, so nothing to close. */
export async function closeSandboxPool() {}
