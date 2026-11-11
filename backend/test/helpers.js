/**
 * Integration test helpers. Tests run against the database named in .env.test
 * (SynoraV1_Test, created from database/schema.sql and seeded with `npm run seed:test`).
 */
import { randomBytes } from 'node:crypto';
import bcrypt from 'bcryptjs';
import { createApp } from '../src/app.js';
import { config } from '../src/config.js';
import { closePool, query } from '../src/db.js';
import { attachAiRelay } from '../src/ai/relay.js';

// Per-process random password: no hardcoded credential in tests. startServer() sets the demo
// accounts to it, so test files must run one at a time (see `--test-concurrency=1` in package.json).
export const DEMO_PASSWORD = randomBytes(18).toString('base64url');
export const ACCOUNTS = {
  admin: 'admin@synora.local',
  faculty: 'faculty@synora.local',
  student: 'student@synora.local',
};

let server;
let baseUrl;

async function resetDemoPasswords() {
  const hash = await bcrypt.hash(DEMO_PASSWORD, config.bcryptRounds);
  await query('UPDATE dbo.Users SET PasswordHash = @hash WHERE Email IN (@admin, @faculty, @student)', {
    hash,
    admin: ACCOUNTS.admin,
    faculty: ACCOUNTS.faculty,
    student: ACCOUNTS.student,
  });
}

export async function startServer() {
  if (server) return baseUrl;
  await resetDemoPasswords();
  server = await new Promise((resolve) => {
    const s = createApp().listen(0, () => resolve(s));
  });
  attachAiRelay(server);
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  return baseUrl;
}

export async function stopServer() {
  if (server) await new Promise((resolve) => server.close(resolve));
  server = undefined;
  await closePool();
}

/** fetch wrapper: JSON body in, `{ status, body, cookie }` out. */
export async function api(method, path, { body, cookie } = {}) {
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { ...(body !== undefined && { 'Content-Type': 'application/json' }), ...(cookie && { Cookie: cookie }) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const setCookie = res.headers.get('set-cookie');
  return {
    status: res.status,
    body: text ? JSON.parse(text) : null,
    cookie: setCookie ? setCookie.split(';')[0] : undefined,
  };
}

export async function login(role) {
  const res = await api('POST', '/api/v1/auth/login', { body: { email: ACCOUNTS[role], password: DEMO_PASSWORD } });
  if (res.status !== 200) throw new Error(`login as ${role} failed: ${res.status} ${JSON.stringify(res.body)}`);
  return res.cookie;
}

/** Unique suffix so tests can be re-run against the same database. */
export const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
