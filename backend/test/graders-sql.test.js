import { test } from 'node:test';
import assert from 'node:assert/strict';
import { grade, resultsMatch } from '../src/assessment/graders/sql.js';
import { HttpError } from '../src/http.js';

const expected = (o) => JSON.stringify({ columns: ['id', 'name'], rows: [[1, 'a'], [2, null]], orderMatters: false, ...o });
const activity = (er = expected()) => ({ ActivityType: 'SQL', MaxScore: 5, sqlSpec: { SetupScript: 'setup', ExpectedResult: er } });
const run = (rows, columns = ['ID', 'Name'], extra = {}) => async () => ({ columns, rows, rowCount: rows.length, truncated: false, error: null, ...extra });

test('sql: passes setup and student sql to the sandbox; match scores MaxScore', async () => {
  let req;
  const out = await grade(activity(), { sql: 'select 1' }, { runSql: async (r) => { req = r; return run([{ ID: 2, Name: null }, { ID: 1, Name: 'a' }])(); } });
  assert.deepEqual(req, { sql: 'select 1', setupScript: 'setup' });
  assert.equal(out.score, 5);
  assert.deepEqual(out.results, [{ passed: true }]);
  assert.equal(out.passed, 1);
});

test('sql: mismatch, error and truncated fail with score 0', async () => {
  const bad = await grade(activity(), { sql: 's' }, { runSql: run([{ ID: 1, Name: 'a' }]) });
  assert.equal(bad.score, 0);
  for (const extra of [{ error: 'Invalid object' }, { truncated: true }]) {
    const out = await grade(activity(), { sql: 's' }, { runSql: run([{ ID: 1, Name: 'a' }, { ID: 2, Name: null }], ['ID', 'Name'], extra) });
    assert.equal(out.score, 0);
    assert.equal(out.results[0].passed, false);
  }
});

test('sql: order matters only when flagged', () => {
  const e = { columns: ['a'], rows: [[1], [2]], orderMatters: true };
  const rev = { columns: ['a'], rows: [{ a: 2 }, { a: 1 }] };
  assert.equal(resultsMatch(e, rev), false);
  assert.equal(resultsMatch({ ...e, orderMatters: false }, rev), true);
  assert.equal(resultsMatch({ columns: ['a'], rows: [[1], [1]] }, { columns: ['a'], rows: [{ a: 1 }, { a: 2 }] }), false);
});

test('sql: column names case-insensitive and ordered; counts must agree', () => {
  assert.equal(resultsMatch({ columns: ['A', 'b'], rows: [] }, { columns: ['a', 'B'], rows: [] }), true);
  assert.equal(resultsMatch({ columns: ['a', 'b'], rows: [] }, { columns: ['b', 'a'], rows: [] }), false);
  assert.equal(resultsMatch({ columns: ['a'], rows: [[1]] }, { columns: ['a', 'b'], rows: [{ a: 1, b: 2 }] }), false);
});

test('sql: value normalisation (NULL, BIT, DATETIME, DECIMAL, strings exact)', () => {
  const m = (ev, sv) => resultsMatch({ columns: ['x'], rows: [[ev]] }, { columns: ['x'], rows: [{ x: sv }] });
  assert.equal(m(null, null), true);
  assert.equal(m(null, 0), false);
  assert.equal(m(1, true), true);
  assert.equal(m(0, false), true);
  assert.equal(m(true, 1), true);
  assert.equal(m('2024-01-02T03:04:05.000Z', new Date('2024-01-02T03:04:05Z')), true);
  assert.equal(m(1.5, 1.5000000004), true);
  assert.equal(m(1.5, 1.51), false);
  assert.equal(m('a', 'A'), false);
  assert.equal(m('1', 1), false);
});

test('sql: sandbox failures propagate; bad ExpectedResult is a 500; bad payload 400', async () => {
  await assert.rejects(grade(activity(), { sql: 's' }, { runSql: async () => { throw new HttpError(503, 'down'); } }), { status: 503 });
  await assert.rejects(grade(activity(), { sql: 's' }, { runSql: async () => { throw new HttpError(429, 'busy'); } }), { status: 429 });
  await assert.rejects(grade(activity(), { sql: 's' }, { runSql: async () => { throw new Error('boom'); } }), { status: 503 });
  await assert.rejects(grade(activity('{"nope":1}'), { sql: 's' }, { runSql: run([]) }), { status: 500 });
  await assert.rejects(grade(activity('not json'), { sql: 's' }, { runSql: run([]) }), { status: 500 });
  await assert.rejects(grade(activity(), {}, { runSql: run([]) }), { status: 400 });
  await assert.rejects(grade(activity(), { sql: 'x'.repeat(70000) }, { runSql: run([]) }), { status: 400 });
});
