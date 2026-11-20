/**
 * One-off: set a new password on exactly the three demo accounts (the seed never updates existing users).
 * Run: ROTATE_CONFIRM=1 DEMO_NEW_PASSWORD=<16+ chars> node --env-file=.env scripts/rotate-demo.js
 * Single transaction; rolls back unless exactly 3 rows change. Prints no password or hash.
 * Existing tokens stop working because the token password-version claim derives from the stored hash.
 */
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import sql from 'mssql';
import bcrypt from 'bcryptjs';
import { config } from '../src/config.js';
import { getPool, closePool } from '../src/db.js';

const EMAILS = ['admin@synora.local', 'faculty@synora.local', 'student@synora.local'];
const MIN_LENGTH = 16;

export function assertRotateAllowed(env) {
  if (env.ROTATE_CONFIRM !== '1') throw new Error('set ROTATE_CONFIRM=1 to confirm');
  if (!env.DEMO_NEW_PASSWORD || env.DEMO_NEW_PASSWORD.length < MIN_LENGTH) {
    throw new Error(`DEMO_NEW_PASSWORD is required and must be at least ${MIN_LENGTH} characters`);
  }
}

async function main() {
  assertRotateAllowed(process.env);
  const hash = await bcrypt.hash(process.env.DEMO_NEW_PASSWORD, config.bcryptRounds);
  const tx = new sql.Transaction(await getPool());
  await tx.begin();
  try {
    const req = tx.request().input('hash', sql.NVarChar(255), hash);
    EMAILS.forEach((e, i) => req.input(`e${i}`, sql.NVarChar(255), e));
    const r = await req.query(
      `UPDATE dbo.Users SET PasswordHash = @hash WHERE Email IN (${EMAILS.map((_, i) => `@e${i}`).join(',')})`);
    if (r.rowsAffected[0] !== 3) throw new Error(`expected 3 rows, updated ${r.rowsAffected[0]}; rolled back`);
    await tx.commit();
    console.log('rotated 3 demo accounts');
  } catch (err) {
    await tx.rollback().catch(() => {}); // keep the original error; re-check the hashes before retrying
    throw err;
  }
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => { console.error(e.message); process.exitCode = 1; }).finally(closePool);
}
