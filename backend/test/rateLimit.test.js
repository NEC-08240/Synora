import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rateLimit, userOrIpKey } from '../src/rateLimit.js';

function fakeRes() {
  return { headers: {}, setHeader(name, value) { this.headers[name] = value; } };
}

function run(middleware, req, res = fakeRes()) {
  let arg;
  let called = false;
  middleware(req, res, (err) => { called = true; arg = err; });
  return { called, err: arg, res };
}

test('the N+1th request in a window gets 429 with Retry-After and the rest pass', () => {
  let t = 0;
  const limiter = rateLimit({ windowMs: 60_000, max: 3, keyFn: () => 'k', now: () => t });
  for (let i = 0; i < 3; i += 1) assert.equal(run(limiter, {}).called, true);
  const blocked = run(limiter, {});
  assert.equal(blocked.err.status, 429);
  assert.match(blocked.err.message, /Too many requests/);
  assert.equal(blocked.res.headers['Retry-After'], '60');
});

test('the window resets after windowMs', () => {
  let t = 0;
  const limiter = rateLimit({ windowMs: 1000, max: 1, keyFn: () => 'k', now: () => t });
  assert.equal(run(limiter, {}).called, true);
  assert.equal(run(limiter, {}).err.status, 429);
  t = 1000;
  assert.equal(run(limiter, {}).called, true);
});

test('other keys are unaffected by one key being limited', () => {
  let t = 0;
  const limiter = rateLimit({ windowMs: 60_000, max: 1, keyFn: userOrIpKey, now: () => t });
  assert.equal(run(limiter, { user: { UserId: 1 } }).called, true);
  assert.equal(run(limiter, { user: { UserId: 1 } }).err.status, 429);
  assert.equal(run(limiter, { user: { UserId: 2 } }).called, true);
});

test('sweep prunes expired keys and keeps live ones', () => {
  let t = 0;
  const limiter = rateLimit({ windowMs: 1000, max: 5, keyFn: (req) => req.key, now: () => t });
  run(limiter, { key: 'a' });
  t = 500;
  run(limiter, { key: 'b' });
  assert.equal(limiter.size(), 2);
  t = 1000;
  limiter.sweep();
  assert.equal(limiter.size(), 1);
});

test('userOrIpKey uses the user id when authenticated and the address otherwise', () => {
  assert.equal(userOrIpKey({ user: { UserId: 7 }, ip: '1.2.3.4' }), 'user:7');
  assert.equal(userOrIpKey({ ip: '1.2.3.4' }), 'ip:1.2.3.4');
});
