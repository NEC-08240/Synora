import { test } from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError, safeUrl, setUnauthorizedHandler } from '../src/api.js';

const respond = (status, body) => { globalThis.fetch = async (url, init) => ({ ok: status < 400, status, text: async () => body, url, init }); };

test('api sends JSON to /api/v1 and parses the reply', async () => {
  let seen;
  globalThis.fetch = async (url, init) => { seen = { url, init }; return { ok: true, status: 200, text: async () => '{"a":1}' }; };
  assert.deepEqual(await api('POST', '/auth/login', { email: 'x' }), { a: 1 });
  assert.equal(seen.url, '/api/v1/auth/login');
  assert.equal(seen.init.body, '{"email":"x"}');
  assert.equal(seen.init.credentials, 'same-origin');
});

test('api throws ApiError with the server message, and tolerates empty bodies', async () => {
  respond(401, '{"error":"Invalid credentials"}');
  await assert.rejects(api('GET', '/auth/me'), (e) => e instanceof ApiError && e.status === 401 && e.message === 'Invalid credentials');
  respond(204, '');
  assert.equal(await api('POST', '/auth/logout'), null);
});

test('safeUrl only passes http(s) links', () => {
  assert.equal(safeUrl('https://example.com/a'), 'https://example.com/a');
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//evil', '', null]) assert.equal(safeUrl(bad), undefined);
});

test('a 401 from a normal endpoint invokes the registered unauthorized handler', async () => {
  let calls = 0;
  setUnauthorizedHandler(() => { calls += 1; });
  respond(401, '{"error":"Sign in again"}');
  await assert.rejects(api('GET', '/subjects'), ApiError);
  assert.equal(calls, 1);
  setUnauthorizedHandler(null);
});

test('a 401 from login or the startup session check does not invoke the unauthorized handler', async () => {
  let calls = 0;
  setUnauthorizedHandler(() => { calls += 1; });
  respond(401, '{"error":"Invalid credentials"}');
  await assert.rejects(api('POST', '/auth/login', { email: 'x' }), ApiError);
  await assert.rejects(api('GET', '/auth/me'), ApiError);
  assert.equal(calls, 0);
  setUnauthorizedHandler(null);
});

test('non-401 errors do not invoke the unauthorized handler', async () => {
  let calls = 0;
  setUnauthorizedHandler(() => { calls += 1; });
  respond(429, '{"error":"Too many"}');
  await assert.rejects(api('POST', '/auth/login', {}), (e) => e.status === 429);
  respond(500, '{"error":"boom"}');
  await assert.rejects(api('GET', '/subjects'), (e) => e.status === 500);
  assert.equal(calls, 0);
  setUnauthorizedHandler(null);
});

test('a non-JSON error response still produces an ApiError', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 502, text: async () => '<html>Bad Gateway</html>' });
  await assert.rejects(api('GET', '/subjects'), (e) => e instanceof ApiError && e.status === 502);
});
