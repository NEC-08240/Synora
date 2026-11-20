import { test } from 'node:test';
import assert from 'node:assert/strict';
import { grade, normalizeOutput } from '../src/assessment/graders/code.js';
import { HttpError } from '../src/http.js';

const tc = (id, input, out) => ({ TestCaseId: id, InputData: input, ExpectedOutput: out, OrderIndex: id });
const activity = { ActivityType: 'Coding', MaxScore: 10, language: 'c', testCases: [tc(3, 'b', 'B'), tc(1, 'a', 'A'), tc(2, null, 'C\n')] };
const ok = (stdout) => ({ stdout, stderr: '', exitCode: 0, timedOut: false, compileError: false, durationMs: 5 });
const echoUpper = async ({ stdin }) => ok(stdin ? stdin.toUpperCase() : 'C');

test('normalizeOutput: CRLF, trailing spaces per line, trailing blank lines', () => {
  assert.equal(normalizeOutput('a  \r\nb\t\r\n\r\n\n'), 'a\nb');
  assert.equal(normalizeOutput('  a'), '  a');
});

test('code: runs cases in OrderIndex with stdin, language and source; score proportional', async () => {
  const calls = [];
  const runCode = async (req) => { calls.push(req); return echoUpper(req); };
  const out = await grade(activity, { source: 'src' }, { runCode });
  assert.deepEqual(calls.map((c) => c.stdin), ['a', '', 'b']);
  assert.ok(calls.every((c) => c.language === 'c' && c.source === 'src'));
  assert.equal(out.score, 10);
  assert.deepEqual([out.passed, out.total, out.compileError, out.timedOut], [3, 3, false, false]);
  assert.deepEqual(out.results.map((r) => r.testCaseId), [1, 2, 3]);
  const partial = await grade(activity, { source: 's' }, { runCode: async (r) => ok(r.stdin === 'a' ? 'A' : 'x') });
  assert.equal(partial.score, 3.33);
  assert.equal(partial.passed, 1);
});

test('code: nonzero exit and timeout fail only that case; timedOut is reported', async () => {
  const runCode = async ({ stdin }) => (stdin === 'a' ? { ...ok('A'), exitCode: 1 } : stdin === 'b' ? { ...ok(''), timedOut: true } : ok('C'));
  const out = await grade(activity, { source: 's' }, { runCode });
  assert.equal(out.passed, 1);
  assert.equal(out.timedOut, true);
  assert.equal(out.results.find((r) => r.testCaseId === 3).passed, false);
});

test('code: compile error stops early, scores 0, fails every case', async () => {
  let n = 0;
  const runCode = async () => { n += 1; return { ...ok(''), compileError: true, exitCode: 1, stderr: 'secret' }; };
  const out = await grade(activity, { source: 's' }, { runCode });
  assert.equal(n, 1);
  assert.equal(out.score, 0);
  assert.equal(out.compileError, true);
  assert.equal(out.results.length, 3);
  assert.ok(out.results.every((r) => r.passed === false));
});

test('code: runner failures become 503 and nothing is returned', async () => {
  for (const err of [new HttpError(503, 'down'), new HttpError(502, 'bad'), new SyntaxError('bad json'), new TypeError('x')]) {
    await assert.rejects(grade(activity, { source: 's' }, { runCode: async () => { throw err; } }), { status: 503 });
  }
  await assert.rejects(grade(activity, { source: 's' }, { runCode: async () => { throw new HttpError(429, 'busy'); } }), { status: 429 });
});

test('code: payload and activity validation', async () => {
  await assert.rejects(grade(activity, {}, { runCode: echoUpper }), { status: 400 });
  await assert.rejects(grade(activity, { source: 'x'.repeat(70000) }, { runCode: echoUpper }), { status: 400 });
  await assert.rejects(grade({ ...activity, language: 'java' }, { source: 's' }, { runCode: echoUpper }), { status: 500 });
  await assert.rejects(grade({ ...activity, testCases: [] }, { source: 's' }, { runCode: echoUpper }), { status: 500 });
});
