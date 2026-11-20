import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer } from './helpers.js';
import { takeSession } from '../src/ai/sessions.js';

const PENDING_CAP = 5; // ai/sessions.js: pending >= 5 per user is refused
let student;
let studentId;
const firstSessions = [];

before(async () => {
  await startServer();
  student = await login('student');
  studentId = (await api('GET', '/api/v1/auth/me', { cookie: student })).body.user.userId;
});
after(stopServer);

test('the pending-session cap returns 429 with a clear message, not 400', async () => {
  for (let i = 0; i < PENDING_CAP; i += 1) {
    const created = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} });
    assert.equal(created.status, 201);
    firstSessions.push(created.body.sessionId);
  }
  const refused = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} });
  assert.equal(refused.status, 429);
  assert.equal(refused.body.error, 'Too many pending AI sessions, try again shortly');
});

test('takeSession returns a session only to its owner, and only once', () => {
  const sessionId = firstSessions[0];
  assert.equal(takeSession(sessionId, studentId + 100000), null, 'a foreign user cannot take it');
  const owned = takeSession(sessionId, studentId);
  assert.ok(owned, 'the owner can still take it after a foreign attempt');
  assert.equal(takeSession(sessionId, studentId), null, 'single use');
});
