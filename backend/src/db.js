import sql from 'mssql';
import { config } from './config.js';

let poolPromise;

export function getPool() {
  poolPromise ??= new sql.ConnectionPool({
    ...config.db,
    options: { encrypt: true, trustServerCertificate: true },
    pool: { max: 10, min: 0, idleTimeoutMillis: 30000 },
  }).connect();
  return poolPromise;
}

/**
 * Run a parameterised T-SQL statement. `params` maps @name -> value; types are
 * inferred by mssql. Returns the recordset (array of rows).
 */
export async function query(text, params = {}) {
  const pool = await getPool();
  const request = pool.request();
  for (const [name, value] of Object.entries(params)) request.input(name, value);
  const result = await request.query(text);
  return result.recordset ?? [];
}

export async function queryOne(text, params) {
  const rows = await query(text, params);
  return rows[0] ?? null;
}

export async function closePool() {
  if (!poolPromise) return;
  const pool = await poolPromise;
  poolPromise = undefined;
  await pool.close();
}

/** True when the error is a UNIQUE/PK violation (SQL Server 2627/2601). */
export const isUniqueViolation = (err) => err?.number === 2627 || err?.number === 2601;
/** True when the error is a FK violation (SQL Server 547). */
export const isForeignKeyViolation = (err) => err?.number === 547;
