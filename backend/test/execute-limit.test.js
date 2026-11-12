import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { config } from '../src/config.js';
import { login, startServer, stopServer } from './helpers.js';

let baseUrl;
let student;
let faculty;

before(async () => {
  baseUrl = await startServer();
  student = await login('student');
  faculty = await login('faculty');
});
after(stopServer);

/** Raw fetch so the test can read the Retry-After header. An empty body fails validation (400) without running SQL. */
function postSql(cookie) {
  return fetch(`${baseUrl}/api/v1/execute/sql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: '{}',
  });
}

test('the execute limit allows the configured count per user per minute, then returns 429 with Retry-After', async () => {
  const max = config.rateLimits.execute;
  for (let i = 0; i < max; i += 1) {
    const res = await postSql(student);
    assert.equal(res.status, 400, `request ${i + 1} is under the limit`);
  }
  const refused = await postSql(student);
  assert.equal(refused.status, 429);
  assert.ok(Number(refused.headers.get('Retry-After')) >= 1);
  assert.match((await refused.json()).error, /Too many requests/);
});

test('another user is not affected by the student hitting the limit', async () => {
  const res = await postSql(faculty);
  assert.equal(res.status, 400, 'faculty still gets through to validation');
});
