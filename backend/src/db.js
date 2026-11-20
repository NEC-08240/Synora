import sql from 'mssql';
import { config } from './config.js';

let poolPromise;

export function createConnectionPool() {
  const pool = new sql.ConnectionPool({
    ...config.db,
    options: { encrypt: true, trustServerCertificate: config.db.trustServerCertificate },
    pool: { max: 10, min: 0, idleTimeoutMillis: 30000 },
  });
  // Without a listener an idle-connection error would crash the process; log the message only (it can carry connection details).
  pool.on('error', (err) => console.error('SQL pool error:', err?.message));
  return pool;
}

async function connectPool(makePool) {
  const pool = makePool();
  try {
    return await pool.connect();
  } catch (err) {
    // Do not cache a failed connect: the next getPool() call retries.
    poolPromise = undefined;
    await pool.close().catch(() => {});
    throw err;
  }
}

export function getPool(makePool = createConnectionPool) {
  poolPromise ??= connectPool(makePool);
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
  const pending = poolPromise;
  poolPromise = undefined;
  if (!pending) return;
  const pool = await pending.catch(() => null);
  await pool?.close();
}

/** True when the error is a UNIQUE/PK violation (SQL Server 2627/2601). */
export const isUniqueViolation = (err) => err?.number === 2627 || err?.number === 2601;
/** True when the error is a FK violation (SQL Server 547). */
export const isForeignKeyViolation = (err) => err?.number === 547;
