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

const CLOSE_WARN_MS = 5000;
// Shortcut: the setup script ships no sbx objects, so the baseline is empty. Upgrade: list any
// template-owned sbx object names here if the setup ever creates one.
const SHIPPED_OBJECTS = new Set();

let poolPromise; // Promise<ConnectionPool>; cleared on connect failure and on recycle
let currentPool; // the connected pool behind poolPromise
let needsLeakCheck = false; // set when a rollback or cleanup failed; checked before the next run

async function connectSandboxPool(cfg) {
  const pool = new sql.ConnectionPool({
    ...cfg,
    requestTimeout: config.practice.sqlTimeoutMs,
    options: { encrypt: true, trustServerCertificate: config.db.trustServerCertificate },
    pool: { max: config.practice.sandboxConcurrency, min: 0, idleTimeoutMillis: 30000 },
  });
  try {
    currentPool = await pool.connect();
    return currentPool;
  } catch (err) {
    // Do not cache a failed connect: the next request retries (same as db.js connectPool).
    poolPromise = undefined;
    await pool.close().catch(() => {});
    throw err;
  }
}

function getSandboxPool() {
  const cfg = config.practice.sandboxDb;
  if (!cfg) throw new HttpError(503, 'The SQL sandbox is not configured on this server');
  poolPromise ??= connectSandboxPool(cfg);
  return poolPromise;
}

/** Drops a pool that may hold a connection in an open transaction; the next request connects a new one. */
function recycleSandboxPool(pool, reason) {
  if (currentPool === pool) {
    poolPromise = undefined;
    currentPool = undefined;
  }
  console.warn(`sandbox: recycling the connection pool (${reason})`);
  const timer = setTimeout(
    () => console.error(`sandbox: pool still closing ${CLOSE_WARN_MS} ms after recycle (${reason})`),
    CLOSE_WARN_MS,
  );
  timer.unref();
  // Fire-and-forget: pool.close() waits for checked-out connections, so it must not block a request.
  pool.close()
    .catch((err) => console.error(`sandbox: pool close failed (${reason}): ${err.message}`))
    .finally(() => clearTimeout(timer));
}

export const isSqlSandboxAvailable = () => Boolean(config.practice.sandboxDb);

const SP_XP_PREFIX = /^(sp|xp)_/i;
const SIMPLE_FORBIDDEN = new Set([
  'EXEC', 'EXECUTE', 'COMMIT', 'ROLLBACK', 'BULK', 'KILL', 'SHUTDOWN', 'RECONFIGURE',
  'GRANT', 'REVOKE', 'DENY', 'USE', 'OPENROWSET', 'OPENQUERY', 'OPENDATASOURCE',
]);
const TRANSACTION_WORDS = new Set(['TRAN', 'TRANSACTION', 'DISTRIBUTED']);
const WORD = /[\p{L}_@#][\p{L}\p{N}_@#$]*/uy;

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
      const newline = text.indexOf('\n', i);
      i = newline === -1 ? text.length : newline;
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
    } else {
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
    } else if (token.kind === 'ident') {
      if (SP_XP_PREFIX.test(token.value)) return token.value;
    } else {
      const word = token.value.toUpperCase();
      const next = wordAt(tokens, i + 1);
      if (SP_XP_PREFIX.test(token.value)) return token.value;
      if (SIMPLE_FORBIDDEN.has(word)) return word;
      if ((word === 'BEGIN' || word === 'SAVE') && TRANSACTION_WORDS.has(next)) return `${word} ${next}`;
      if (['CREATE', 'ALTER', 'DROP'].includes(word) && ['LOGIN', 'USER'].includes(next)) return `${word} ${next}`;
      if (word === 'UPDATE' && wordAt(tokens, i - 1) !== 'ON') setPermits = 1;
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

/** Rolls back, then runs leak cleanup. A failed rollback or cleanup recycles the pool. */
async function finishRun(pool, tx, run) {
  if (run.begun) {
    try {
      await tx.rollback();
    } catch (err) {
      console.error(`sandbox: rollback failed: ${err.message}`);
      needsLeakCheck = true;
      recycleSandboxPool(pool, 'rollback failed');
      return;
    }
    if (!(await removeLeakedObjects(pool))) {
      needsLeakCheck = true;
      recycleSandboxPool(pool, 'leak cleanup failed');
      return;
    }
  }
  if (run.aborted) recycleSandboxPool(pool, 'timeout or cancel');
}

async function executeInTransaction(pool, { sql: studentSql, setupScript }) {
  if (needsLeakCheck) needsLeakCheck = !(await removeLeakedObjects(pool));
  const tx = new sql.Transaction(pool);
  const run = { begun: false, aborted: false };
  try {
    await tx.begin();
    run.begun = true;
    if (setupScript.trim()) {
      const setup = await streamBatch(new sql.Request(tx), setupScript, { keepRows: false });
      run.aborted = setup.aborted;
      // SQL errors (syntax, missing table, timeout) are the student's feedback, not a server failure.
      if (setup.error) return failure(setup.error.message);
    }
    const student = await streamBatch(new sql.Request(tx), studentSql, { keepRows: true });
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
    await finishRun(pool, tx, run);
  }
}

/** @returns {Promise<{columns:string[], rows:object[], rowCount:number, truncated:boolean, error:string|null}>} */
export async function runSql({ sql: studentSql, setupScript = '' }) {
  const forbidden = findForbiddenStatement(setupScript) ?? findForbiddenStatement(studentSql);
  if (forbidden) return failure(`${forbidden} is not allowed in the practice sandbox`);
  return runQueued(async () => executeInTransaction(await getSandboxPool(), { sql: studentSql, setupScript }));
}

export async function closeSandboxPool() {
  const pending = poolPromise;
  poolPromise = undefined;
  currentPool = undefined;
  if (!pending) return;
  const pool = await pending.catch(() => null);
  await pool?.close();
}
