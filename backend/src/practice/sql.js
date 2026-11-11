/**
 * Student SQL sandbox. Runs against a SEPARATE database with a low-privilege login (never the app
 * DB) inside a transaction that is always rolled back, so every request starts from an empty
 * schema and nothing a student does persists. CPU/memory isolation is the SQL Server instance's
 * job; see docs/technical/practice-execution.md.
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

/** @returns {Promise<{columns:string[], rows:object[], rowCount:number, truncated:boolean, error:string|null}>} */
export async function runSql({ sql: studentSql, setupScript = '' }) {
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
