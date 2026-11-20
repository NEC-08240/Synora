import { test, after, before } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { startServer, stopServer, api, login } from './helpers.js';
import { runCode } from '../src/practice/code.js';
import { closeSandboxPool } from '../src/practice/sql.js';

before(async () => { await startServer(); });
after(async () => { await closeSandboxPool(); await stopServer(); });

test('execute endpoints require a Student or Faculty login', async () => {
  const anon = await api('POST', '/api/v1/execute/sql', { body: { sql: 'SELECT 1' } });
  assert.equal(anon.status, 401);
  const admin = await login('admin');
  const res = await api('POST', '/api/v1/execute/sql', { body: { sql: 'SELECT 1' }, cookie: admin });
  assert.equal(res.status, 403);
});

test('SQL sandbox runs setup + query in a rolled-back transaction, never persisting', async () => {
  const student = await login('student');
  const setupScript = "CREATE TABLE t (id INT, name NVARCHAR(20)); INSERT INTO t VALUES (1, N'a'), (2, N'b');";
  const ok = await api('POST', '/api/v1/execute/sql', {
    body: { sql: 'SELECT id, name FROM t ORDER BY id', setupScript }, cookie: student,
  });
  assert.equal(ok.status, 200);
  assert.deepEqual(ok.body.columns, ['id', 'name']);
  assert.equal(ok.body.rowCount, 2);
  assert.equal(ok.body.error, null);

  // Table from the previous request must be gone.
  const gone = await api('POST', '/api/v1/execute/sql', { body: { sql: 'SELECT * FROM t' }, cookie: student });
  assert.equal(gone.status, 200);
  assert.match(gone.body.error, /Invalid object name 't'/);

  const bad = await api('POST', '/api/v1/execute/sql', { body: { sql: 'SELECT FROM' }, cookie: student });
  assert.equal(bad.status, 200);
  assert.match(bad.body.error, /Incorrect syntax/);

  const missing = await api('POST', '/api/v1/execute/sql', { body: {}, cookie: student });
  assert.equal(missing.status, 400);
});

test('code proxy forwards to a Piston-shaped runner and maps compile/run results', async () => {
  const seen = [];
  const fake = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      const p = JSON.parse(body);
      seen.push({ url: req.url, p });
      const compileFails = p.files[0].content.includes('oops');
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(compileFails
        ? { compile: { code: 1, stdout: '', stderr: 'error: oops' }, run: { code: null } }
        : { compile: { code: 0 }, run: { code: 0, stdout: 'hi\n', stderr: '', signal: null } }));
    });
  });
  await new Promise((r) => fake.listen(0, '127.0.0.1', r));
  const executorUrl = `http://127.0.0.1:${fake.address().port}`;
  try {
    const good = await runCode({ language: 'cpp', source: 'int main(){}', stdin: 'x' }, { executorUrl });
    assert.equal(good.stdout, 'hi\n');
    assert.equal(good.compileError, false);
    assert.equal(seen[0].url, '/api/v2/execute');
    assert.equal(seen[0].p.language, 'c++');
    assert.equal(seen[0].p.files[0].name, 'main.cpp');
    assert.equal(seen[0].p.stdin, 'x');

    const bad = await runCode({ language: 'c', source: 'oops' }, { executorUrl });
    assert.equal(bad.compileError, true);
    assert.match(bad.stderr, /oops/);
  } finally {
    fake.close();
  }
});

test('without EXECUTOR_URL the code endpoint reports 503 and status reflects availability', async () => {
  const student = await login('student');
  const status = await api('GET', '/api/v1/execute/status', { cookie: student });
  assert.deepEqual(status.body, { code: false, sql: true });
  const res = await api('POST', '/api/v1/execute/code', { body: { language: 'c', source: 'int main(){}' }, cookie: student });
  assert.equal(res.status, 503);
});
