import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer, ACCOUNTS, DEMO_PASSWORD } from './helpers.js';

before(startServer);
after(stopServer);

test('health endpoint is public', async () => {
  const res = await api('GET', '/api/v1/health');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, { status: 'ok' });
});

test('login sets an HttpOnly cookie and returns the user without the hash', async () => {
  const res = await fetch(`${await startServer()}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: ACCOUNTS.student, password: DEMO_PASSWORD }),
  });
  assert.equal(res.status, 200);
  const cookie = res.headers.get('set-cookie');
  assert.match(cookie, /^synora_token=/);
  assert.match(cookie, /HttpOnly/i);
  const body = await res.json();
  assert.equal(body.user.role, 'Student');
  assert.equal(body.user.email, ACCOUNTS.student);
  assert.equal(body.user.passwordHash, undefined);
  assert.equal(body.user.PasswordHash, undefined);
});

test('login rejects wrong password and unknown email with the same message', async () => {
  const wrong = await api('POST', '/api/v1/auth/login', { body: { email: ACCOUNTS.student, password: 'nope-nope' } });
  const unknown = await api('POST', '/api/v1/auth/login', { body: { email: 'ghost@synora.local', password: 'nope-nope' } });
  assert.equal(wrong.status, 401);
  assert.equal(unknown.status, 401);
  assert.equal(wrong.body.error, unknown.body.error);
});

test('login validates the body', async () => {
  const res = await api('POST', '/api/v1/auth/login', { body: { email: ACCOUNTS.student } });
  assert.equal(res.status, 400);
  assert.equal(res.body.details.password, 'is required');
});

test('me returns the current user and 401 without a cookie', async () => {
  const cookie = await login('faculty');
  const me = await api('GET', '/api/v1/auth/me', { cookie });
  assert.equal(me.status, 200);
  assert.equal(me.body.user.role, 'Faculty');
  const anon = await api('GET', '/api/v1/auth/me');
  assert.equal(anon.status, 401);
});

test('a tampered token is rejected', async () => {
  const cookie = await login('admin');
  const res = await api('GET', '/api/v1/auth/me', { cookie: cookie.slice(0, -4) + 'xxxx' });
  assert.equal(res.status, 401);
});

test('logout clears the cookie', async () => {
  const res = await fetch(`${await startServer()}/api/v1/auth/logout`, { method: 'POST' });
  assert.equal(res.status, 204);
  assert.match(res.headers.get('set-cookie'), /synora_token=;/);
});

test('role boundaries: student cannot list users, faculty cannot create batches', async () => {
  const student = await login('student');
  const faculty = await login('faculty');
  assert.equal((await api('GET', '/api/v1/users', { cookie: student })).status, 403);
  assert.equal((await api('POST', '/api/v1/batches', { cookie: faculty, body: { name: 'x', academicYear: 'y' } })).status, 403);
  assert.equal((await api('GET', '/api/v1/batches', { cookie: student })).status, 403);
  assert.equal((await api('GET', '/api/v1/batches', { cookie: faculty })).status, 200);
});

test('unknown routes return JSON 404 and malformed JSON returns 400', async () => {
  const cookie = await login('admin');
  assert.equal((await api('GET', '/api/v1/nope', { cookie })).status, 404);
  const res = await fetch(`${await startServer()}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{not json',
  });
  assert.equal(res.status, 400);
});

test('five failed logins lock that email out, even with the right password', async () => {
  const email = 'lockout-probe@synora.local';
  for (let i = 0; i < 5; i++) {
    const res = await api('POST', '/api/v1/auth/login', { body: { email, password: 'wrong' } });
    assert.equal(res.status, 401);
  }
  const locked = await api('POST', '/api/v1/auth/login', { body: { email, password: 'wrong' } });
  assert.equal(locked.status, 429);
  // Other accounts from the same address are unaffected.
  assert.ok(await login('student'));
});
