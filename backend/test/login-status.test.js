import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { LOCKOUT_LIMITS } from '../src/auth/lockout.js';
import { query } from '../src/db.js';
import { ACCOUNTS, DEMO_PASSWORD, startServer, stopServer } from './helpers.js';

// Own file = own process = fresh lockout and rate-limit state.
let baseUrl;
before(async () => { baseUrl = await startServer(); });
after(stopServer);

test('a correct password on a suspended account does not clear failure counters', async () => {
  const email = ACCOUNTS.faculty;
  await query("UPDATE dbo.Users SET Status = N'Suspended' WHERE Email = @email", { email });
  try {
    const before = await fetch(`${baseUrl}/api/v1/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'wrong' }) });
    assert.equal(before.status, 401);
    for (let i = 0; i < LOCKOUT_LIMITS.pair + 1; i += 1) {
      await fetch(`${baseUrl}/api/v1/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: DEMO_PASSWORD }) });
    }
    const locked = await fetch(`${baseUrl}/api/v1/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: DEMO_PASSWORD }) });
    assert.equal(locked.status, 429, 'repeated suspended-account logins accumulate and lock instead of being cleared each time');
  } finally {
    await query("UPDATE dbo.Users SET Status = N'Active' WHERE Email = @email", { email });
  }
});
