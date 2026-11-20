import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { LOCKOUT_LIMITS } from '../src/auth/lockout.js';
import { config } from '../src/config.js';
import { startServer, stopServer } from './helpers.js';

let baseUrl;
before(async () => { baseUrl = await startServer(); });
after(stopServer);

const attempt = (email) => fetch(`${baseUrl}/api/v1/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password: 'definitely-wrong' }),
});

test('a parallel burst of wrong passwords is locked out after the pair limit with no extra bcrypt attempts', async () => {
  // Stay under the per-IP rate limit so this exercises the lockout, not the limiter.
  const burst = Math.min(config.rateLimits.login, 30);
  const results = await Promise.all(Array.from({ length: burst }, () => attempt('burst-victim@x.test')));
  const bodies = await Promise.all(results.map(async (r) => ({ status: r.status, error: (await r.json()).error })));
  const verified = bodies.filter((b) => b.status === 401).length;
  const locked = bodies.filter((b) => b.status === 429 && /failed sign-in/.test(b.error)).length;
  assert.equal(verified, LOCKOUT_LIMITS.pair, 'only the pair limit worth of guesses reached bcrypt');
  assert.equal(locked, burst - LOCKOUT_LIMITS.pair);
});

test('login is rate limited per ip independently of lockout, with Retry-After', async () => {
  // The burst test already used part of this minute's budget; spray distinct emails (no pair/email lock) to exhaust it.
  let limited;
  for (let i = 0; i < config.rateLimits.login + 1 && !limited; i += 1) {
    const res = await attempt(`spray${i}@x.test`);
    if (res.status === 429 && /Too many requests/.test((await res.json()).error)) limited = res;
  }
  assert.ok(limited, 'a rate limit 429 (not a lockout) was returned');
  assert.ok(Number(limited.headers.get('Retry-After')) >= 1);
});
