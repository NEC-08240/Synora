/**
 * Student SQL sandbox. Runs against a SEPARATE database with a low-privilege login (never the app
 * DB) inside a transaction that is rolled back after every run. The database permissions in
 * database/sandbox_setup.sql are the real control. findForbiddenStatement() is defense in depth
 * only and is NOT an isolation boundary. See docs/technical/practice-execution.md.
 */
import sql from 'mssql';
import { config } from '../config.js';
import { HttpError } from '../http.js';

let poolPromise;
function getSandboxPool() {
  const cfg = config.practice.sandboxDb;
  if (!cfg) throw new HttpError(503, 'The SQL sandbox is not configured on this server');
  poolPromise ??= new sql.ConnectionPool({
    ...cfg,
    requestTimeout: config.practice.sqlTimeoutMs,
    options: { encrypt: true, trustServerCertificate: true },
    pool: { max: 4, min: 0, idleTimeoutMillis: 30000 },
  }).connect();
  return poolPromise;
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

/** @returns {Promise<{columns:string[], rows:object[], rowCount:number, truncated:boolean, error:string|null}>} */
export async function runSql({ sql: studentSql, setupScript = '' }) {
  const forbidden = findForbiddenStatement(setupScript) ?? findForbiddenStatement(studentSql);
  if (forbidden) {
    return { columns: [], rows: [], rowCount: 0, truncated: false, error: `${forbidden} is not allowed in the practice sandbox` };
  }
  const pool = await getSandboxPool();
  const tx = new sql.Transaction(pool);
  await tx.begin();
  try {
    if (setupScript.trim()) await new sql.Request(tx).batch(setupScript);
    const result = await new sql.Request(tx).batch(studentSql);
    const { maxRows } = config.practice;
    const all = result.recordset ?? [];
    return {
      columns: Object.keys(result.recordset?.columns ?? {}),
      rows: all.slice(0, maxRows),
      rowCount: result.recordset ? all.length : result.rowsAffected.reduce((a, b) => a + b, 0),
      truncated: all.length > maxRows,
      error: null,
    };
  } catch (err) {
    // SQL errors (syntax, missing table, timeout) are the student's feedback, not a server failure.
    return { columns: [], rows: [], rowCount: 0, truncated: false, error: err.message };
  } finally {
    await tx.rollback().catch(() => {});
  }
}

export async function closeSandboxPool() {
  if (!poolPromise) return;
  const pool = await poolPromise;
  poolPromise = undefined;
  await pool.close();
}
