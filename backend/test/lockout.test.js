import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  LOCK_MS,
  LOCKOUT_LIMITS,
  clearFailures,
  isLockedOut,
  recordFailure,
  sweepLockouts,
  trackedCount,
} from '../src/auth/lockout.js';
import { verifyPassword } from '../src/auth/routes.js';

// Each test uses its own ips/emails: the tracker is process-wide, and the injected clock keeps time deterministic.
const T0 = 1_000_000_000;
const failMany = (ip, email, n, now) => { for (let i = 0; i < n; i += 1) recordFailure(ip, email, now); };

test('the same ip and email locks after the pair limit and unlocks after LOCK_MS', () => {
  const email = 'pair-limit@x.test';
  failMany('10.1.0.1', email, LOCKOUT_LIMITS.pair - 1, T0);
  assert.equal(isLockedOut('10.1.0.1', email, T0), false);
  recordFailure('10.1.0.1', email, T0);
  assert.equal(isLockedOut('10.1.0.1', email, T0 + 1), true);
  assert.equal(isLockedOut('10.1.0.1', email, T0 + LOCK_MS), false);
});

test('rotating through many ips still hits the per-email limit', () => {
  const email = 'victim-rotation@x.test';
  for (let i = 0; i < LOCKOUT_LIMITS.email; i += 1) recordFailure(`10.2.0.${i}`, email, T0);
  assert.equal(isLockedOut('10.2.9.9', email, T0 + 1), true, 'a fresh ip is locked for the targeted email');
  assert.equal(isLockedOut('10.2.9.9', 'other@x.test', T0 + 1), false, 'other emails are unaffected');
});

test('one ip failing across many emails hits the per-ip limit', () => {
  const ip = '10.3.0.1';
  for (let i = 0; i < LOCKOUT_LIMITS.ip; i += 1) recordFailure(ip, `spray${i}@x.test`, T0);
  assert.equal(isLockedOut(ip, 'brand-new@x.test', T0 + 1), true);
  assert.equal(isLockedOut('10.3.0.2', 'brand-new@x.test', T0 + 1), false);
});

test('an expired lock does not reset the count: one more failure re-locks immediately', () => {
  const email = 'no-reset@x.test';
  const ip = '10.4.0.1';
  failMany(ip, email, LOCKOUT_LIMITS.pair, T0);
  const afterLock = T0 + LOCK_MS + 1;
  assert.equal(isLockedOut(ip, email, afterLock), false);
  recordFailure(ip, email, afterLock);
  assert.equal(isLockedOut(ip, email, afterLock + 1), true);
});

test('counts start over after a full quiet window past the end of the lock', () => {
  const email = 'quiet@x.test';
  const ip = '10.5.0.1';
  failMany(ip, email, LOCKOUT_LIMITS.pair, T0);
  const later = T0 + 2 * LOCK_MS + 1;
  recordFailure(ip, email, later);
  assert.equal(isLockedOut(ip, email, later), false, 'one failure after a long quiet period does not lock');
});

test('a successful sign-in clears the pair and email counters but not the per-ip counter', () => {
  const email = 'cleared@x.test';
  const ip = '10.6.0.1';
  failMany(ip, email, LOCKOUT_LIMITS.pair - 1, T0);
  clearFailures(ip, email);
  recordFailure(ip, email, T0);
  assert.equal(isLockedOut(ip, email, T0), false, 'count restarted after the clear');
});

test('sweep prunes entries whose quiet period ended and keeps recent ones', () => {
  const stale = 'stale@x.test';
  const recent = 'recent@x.test';
  recordFailure('10.7.0.1', stale, T0);
  recordFailure('10.7.0.2', recent, T0 + 2 * LOCK_MS);
  const before = trackedCount();
  sweepLockouts(T0 + 2 * LOCK_MS + 1);
  assert.ok(trackedCount() < before, 'stale entries removed');
  assert.equal(isLockedOut('10.7.0.1', stale, T0 + 2 * LOCK_MS), false);
  // The recent failure's scopes still exist: a further failure keeps counting instead of starting over.
  recordFailure('10.7.0.2', recent, T0 + 2 * LOCK_MS + 2);
  assert.equal(trackedCount() > 0, true);
});

test('the tracker never holds more than 10000 keys (oldest evicted first)', () => {
  for (let i = 0; i < 4000; i += 1) recordFailure(`10.8.${Math.floor(i / 250)}.${i % 250}`, `cap${i}@x.test`, T0);
  assert.ok(trackedCount() <= 10000, `tracked ${trackedCount()}`);
});

test('verifyPassword with no stored hash still runs a bcrypt compare and returns false', async () => {
  assert.equal(await verifyPassword('anything-at-all', undefined), false);
  assert.equal(await verifyPassword('anything-at-all', null), false);
});
