import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import jwt from 'jsonwebtoken';
import { ACCOUNTS, DEMO_PASSWORD, api, login, startServer, stopServer, unique } from './helpers.js';

const NEW_PASSWORD = 'Reset-pass-2026';
let baseUrl;
let admin;

const tokenOf = (cookie) => cookie.split('=').slice(1).join('=');
const me = (cookie) => api('GET', '/api/v1/auth/me', { cookie });

/** Creates a throwaway Faculty account (never a demo account) and returns its login cookie and userId. */
async function throwawayUser() {
  const email = `jwt-${unique()}@synora.local`;
  const created = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'JWT Test', email, password: 'Password123', role: 'Faculty' },
  });
  assert.equal(created.status, 201);
  const res = await api('POST', '/api/v1/auth/login', { body: { email, password: 'Password123' } });
  assert.equal(res.status, 200);
  return { cookie: res.cookie, userId: created.body.user.userId, email };
}

before(async () => {
  baseUrl = await startServer();
  admin = await login('admin');
});
after(stopServer);

test('a token works until logout, then the same token is rejected', async () => {
  const user = await throwawayUser();
  assert.equal((await me(user.cookie)).status, 200);
  const out = await api('POST', '/api/v1/auth/logout', { cookie: user.cookie });
  assert.equal(out.status, 204);
  assert.equal((await me(user.cookie)).status, 401, 'revoked jti is refused server-side');
});

test('an admin password reset invalidates tokens issued before it', async () => {
  const user = await throwawayUser();
  assert.equal((await me(user.cookie)).status, 200);
  const reset = await api('PATCH', `/api/v1/users/${user.userId}`, { cookie: admin, body: { password: NEW_PASSWORD } });
  assert.equal(reset.status, 200);
  assert.equal((await me(user.cookie)).status, 401, 'old token carries the previous password version');
  const relogin = await api('POST', '/api/v1/auth/login', { body: { email: user.email, password: NEW_PASSWORD } });
  assert.equal(relogin.status, 200, 'the new password works');
  assert.equal((await me(relogin.cookie)).status, 200);
});

test('a token signed with alg none is rejected', async () => {
  const user = await throwawayUser();
  const [, payload] = tokenOf(user.cookie).split('.');
  const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
  const forged = `${header}.${payload}.`;
  assert.equal((await me(`synora_token=${forged}`)).status, 401);
});

/** Re-signs the real token with one claim replaced, using the real secret, so only that claim is wrong. */
function resign(cookie, { issuer, audience } = {}) {
  const claims = jwt.decode(tokenOf(cookie));
  const options = { algorithm: 'HS256', issuer: claims.iss, audience: claims.aud };
  for (const registered of ['iat', 'exp', 'iss', 'aud']) delete claims[registered];
  return jwt.sign(claims, process.env.JWT_SECRET, { ...options, issuer: issuer ?? options.issuer, audience: audience ?? options.audience });
}

test('a correctly signed token with the wrong issuer is rejected', async () => {
  const user = await throwawayUser();
  const token = resign(user.cookie, { issuer: 'someone-else' });
  assert.equal((await me(`synora_token=${token}`)).status, 401);
});

test('a correctly signed token with the wrong audience is rejected', async () => {
  const user = await throwawayUser();
  const token = resign(user.cookie, { audience: 'other-app' });
  assert.equal((await me(`synora_token=${token}`)).status, 401);
});

test('the unmodified re-signed token is accepted (control for the negative tests)', async () => {
  const user = await throwawayUser();
  const token = resign(user.cookie);
  assert.equal((await me(`synora_token=${token}`)).status, 200);
});

test('the session cookie is httpOnly, SameSite=Lax, 8 hours, and not Secure outside production', async () => {
  const res = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: ACCOUNTS.student, password: DEMO_PASSWORD }),
  });
  const setCookie = res.headers.get('set-cookie');
  assert.match(setCookie, /HttpOnly/i);
  assert.match(setCookie, /SameSite=Lax/i);
  assert.match(setCookie, /Max-Age=28800/);
  assert.doesNotMatch(setCookie, /;\s*Secure/i);
});
