import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import sql from 'mssql';

// Unmocked grading: real graders, real loader, real DB. The code runner is a tiny fake Piston so the file runs anywhere.
const SENTINEL = 'SENTINEL-m3i-5d2f';
let runnerMode = 'echo';
let lastRunnerRequest = null;
const runner = http.createServer((req, res) => {
  let raw = '';
  req.on('data', (c) => { raw += c; });
  req.on('end', () => {
    lastRunnerRequest = JSON.parse(raw);
    res.setHeader('Content-Type', 'application/json');
    const stdin = lastRunnerRequest.stdin ?? '';
    res.end(JSON.stringify(runnerMode === 'broken' ? { run: {} } : { run: { stdout: stdin, stderr: stdin, code: 0, signal: null } }));
  });
});
await new Promise((resolve) => runner.listen(0, '127.0.0.1', resolve));
process.env.EXECUTOR_URL = `http://127.0.0.1:${runner.address().port}`;
process.env.RATE_LIMIT_SUBMIT_PER_MIN = '1000';
process.env.ASSESSMENT_GRADE_CONCURRENCY = '1';
process.env.ASSESSMENT_QUEUE_MAX = '1';

const { api, login, startServer, stopServer, demoUser, createActivityFixture, cleanupFixtures } = await import('./helpers.js');
const { getPool, query, queryOne } = await import('../src/db.js');
const { isSqlSandboxAvailable } = await import('../src/practice/sql.js');
const { registerGrader, runGrading } = await import('../src/assessment/grader.js');

const base = (id) => `/api/v1/activities/${id}`;
let faculty;
let student;
before(async () => {
  await startServer();
  [faculty, student] = await Promise.all([login('faculty'), login('student')]);
});
after(async () => {
  await cleanupFixtures();
  await stopServer();
  runner.close();
});

const put = (id, path, body) => api('PUT', `${base(id)}/${path}`, { cookie: faculty, body });
const publish = (id) => api('POST', `${base(id)}/status`, { cookie: faculty, body: { status: 'Published' } });
const count = async (table, id) => (await queryOne(
  table === 'Submissions'
    ? 'SELECT COUNT(*) AS n FROM dbo.Submissions WHERE ActivityId = @a'
    : `SELECT COUNT(*) AS n FROM dbo.${table} WHERE SubmissionId IN (SELECT SubmissionId FROM dbo.Submissions WHERE ActivityId = @a)`,
  { a: id },
)).n;

const quizBody = (n = 2, expl = `${SENTINEL}-expl`) => ({
  questions: Array.from({ length: n }, (_, i) => ({
    questionText: `q${i}`,
    explanation: expl,
    points: 5,
    options: [{ optionText: 'right', isCorrect: true }, { optionText: 'wrong', isCorrect: false }],
  })),
});
async function publishedQuiz() {
  const fx = await createActivityFixture({ type: 'Quiz', status: 'Draft' });
  const q = await put(fx.activityId, 'questions', quizBody());
  assert.equal(q.status, 200);
  assert.equal((await publish(fx.activityId)).status, 200);
  return { ...fx, questions: q.body.questions };
}
const answers = (fx, correct) => fx.questions.map((q, i) => ({
  questionId: q.questionId,
  optionId: q.options.find((o) => o.isCorrect === (i === 0 ? correct : true)).optionId,
}));

async function publishedCoding(cases) {
  const fx = await createActivityFixture({ type: 'Coding', status: 'Draft' });
  assert.equal((await put(fx.activityId, 'test-cases', { testCases: cases })).status, 200);
  assert.equal((await publish(fx.activityId)).status, 200);
  return fx;
}

test('quiz e2e: loader feeds the real grader; answers + counts persisted; student sees counts only', async () => {
  const fx = await publishedQuiz();
  const url = `${base(fx.activityId)}/submissions`;
  const ok = await api('POST', url, { cookie: student, body: { answers: answers(fx, true) } });
  assert.equal(ok.status, 201, JSON.stringify(ok.body));
  assert.equal(Number(ok.body.score), 10);
  assert.equal(ok.body.passed, 2);
  assert.equal(ok.body.total, 2);
  const half = await api('POST', url, { cookie: student, body: { answers: answers(fx, false) } });
  assert.equal(Number(half.body.score), 5);
  assert.equal(half.body.passed, 1);
  assert.equal(await count('SubmissionAnswers', fx.activityId), 4);
  assert.equal(await count('TestCaseResults', fx.activityId), 0, 'quiz writes no per-case rows');
});

test('coding e2e: language derived, hidden cases graded, TestCaseResults keyed by TestCaseId, student sees counts only', async () => {
  runnerMode = 'echo';
  const fx = await publishedCoding([{ inputData: '3', expectedOutput: '3' }, { inputData: '4', expectedOutput: '5' }]);
  const res = await api('POST', `${base(fx.activityId)}/submissions`, { cookie: student, body: { source: 'int main(){}' } });
  assert.equal(res.status, 201, JSON.stringify(res.body));
  assert.equal(lastRunnerRequest.language, 'c');
  assert.equal(Number(res.body.score), 5);
  assert.equal(res.body.passed, 1);
  assert.equal(res.body.total, 2);
  const rows = await query('SELECT r.TestCaseId, r.Passed FROM dbo.TestCaseResults r JOIN dbo.TestCases t ON t.TestCaseId = r.TestCaseId WHERE t.ActivityId = @a ORDER BY t.OrderIndex', { a: fx.activityId });
  assert.deepEqual(rows.map((r) => Boolean(r.Passed)), [true, false]);
  assert.ok(!/testCaseId|perCase/i.test(JSON.stringify(res.body)));

  const detail = await api('GET', base(fx.activityId), { cookie: student });
  assert.equal(detail.body.activity.testCases, undefined, 'students get no hidden-case listing (testCaseId/orderIndex)');
  const mine = await api('GET', `${base(fx.activityId)}/submissions/mine`, { cookie: student });
  assert.equal(mine.body[0].passed, 1);
  assert.equal(mine.body[0].total, 2);
});

test('coding: runner answers without an exit code -> 503 and nothing written', async () => {
  runnerMode = 'broken';
  try {
    const fx = await publishedCoding([{ inputData: '1', expectedOutput: '1' }]);
    const res = await api('POST', `${base(fx.activityId)}/submissions`, { cookie: student, body: { source: 'x' } });
    assert.equal(res.status, 503);
    assert.equal(await count('Submissions', fx.activityId), 0);
  } finally {
    runnerMode = 'echo';
  }
});

test('sql e2e: setup script + expected result graded all-or-nothing', { skip: !isSqlSandboxAvailable() && 'SQL sandbox not configured' }, async () => {
  const fx = await createActivityFixture({ type: 'SQL', status: 'Draft' });
  const spec = await put(fx.activityId, 'sql-spec', {
    setupScript: 'CREATE TABLE t (a INT); INSERT t VALUES (1),(2);',
    expectedResult: { columns: ['a'], rows: [[1], [2]], orderMatters: false },
  });
  assert.equal(spec.status, 200, JSON.stringify(spec.body));
  assert.equal((await publish(fx.activityId)).status, 200);
  const url = `${base(fx.activityId)}/submissions`;
  const good = await api('POST', url, { cookie: student, body: { sql: 'SELECT a FROM t' } });
  assert.equal(good.status, 201, JSON.stringify(good.body));
  assert.equal(Number(good.body.score), 10);
  const bad = await api('POST', url, { cookie: student, body: { sql: 'SELECT a FROM t WHERE a = 1' } });
  assert.equal(Number(bad.body.score), 0);
  assert.equal(await count('TestCaseResults', fx.activityId), 0, 'sql writes no per-case rows');
});

test('student reading a submission: 404 for missing and for someone else\'s, never 403', async () => {
  const fx = await createActivityFixture({ type: 'Assignment' });
  const other = await demoUser('faculty');
  const sub = await queryOne(
    `INSERT dbo.Submissions (StudentId, ActivityId, AttemptNo, SubmittedContent, Status) OUTPUT INSERTED.SubmissionId VALUES (@s, @a, 1, N'x', N'Submitted')`,
    { s: other.UserId, a: fx.activityId },
  );
  const notMine = await api('GET', `/api/v1/submissions/${sub.SubmissionId}`, { cookie: student });
  const missing = await api('GET', '/api/v1/submissions/2000000000', { cookie: student });
  assert.deepEqual([notMine.status, missing.status], [404, 404]);
  assert.deepEqual(notMine.body, missing.body);
});

test('publish re-checks under the edit lock: content emptied while publish waits is not published', async () => {
  const fx = await createActivityFixture({ type: 'Quiz', status: 'Draft' });
  assert.equal((await put(fx.activityId, 'questions', quizBody())).status, 200);
  const tx = new sql.Transaction(await getPool());
  await tx.begin();
  try {
    await new sql.Request(tx).input('id', fx.activityId).query('SELECT 1 FROM dbo.Activities WITH (UPDLOCK) WHERE ActivityId = @id');
    const pending = publish(fx.activityId);
    await new Promise((r) => setTimeout(r, 1500)); // let publish pass its (unlocked) checks and block on the row
    await new sql.Request(tx).input('id', fx.activityId).query('DELETE FROM dbo.QuizQuestions WHERE ActivityId = @id');
    await tx.commit();
    assert.equal((await pending).status, 400);
  } finally {
    await tx.rollback().catch(() => {});
  }
  assert.equal((await queryOne('SELECT Status FROM dbo.Activities WHERE ActivityId = @id', { id: fx.activityId })).Status, 'Draft');
});

test('authoring caps: question/option/test-case counts, text sizes and time limit are bounded (400)', async () => {
  const fx = await createActivityFixture({ type: 'Quiz', status: 'Draft' });
  assert.equal((await put(fx.activityId, 'questions', quizBody(51))).status, 400);
  const manyOptions = quizBody(1);
  manyOptions.questions[0].options = Array.from({ length: 11 }, (_, i) => ({ optionText: `o${i}`, isCorrect: i === 0 }));
  assert.equal((await put(fx.activityId, 'questions', manyOptions)).status, 400);
  assert.equal((await put(fx.activityId, 'questions', quizBody(1, 'x'.repeat(5000)))).status, 400);
  const coding = await createActivityFixture({ type: 'Coding', status: 'Draft' });
  const cases = (n, o = 'x') => ({ testCases: Array.from({ length: n }, () => ({ inputData: 'i', expectedOutput: o })) });
  assert.equal((await put(coding.activityId, 'test-cases', cases(51))).status, 400);
  assert.equal((await put(coding.activityId, 'test-cases', cases(1, 'x'.repeat(20_000)))).status, 400);
  const sqlFx = await createActivityFixture({ type: 'SQL', status: 'Draft' });
  const er = { columns: ['a'], rows: [[1]], orderMatters: false };
  assert.equal((await put(sqlFx.activityId, 'sql-spec', { setupScript: 'x'.repeat(100_000), expectedResult: er })).status, 400);
  const topic = await api('POST', `/api/v1/topics/${fx.topicId}/activities`, {
    cookie: faculty,
    body: { activityType: 'Coding', title: 't', instructions: 'i', isGraded: true, maxScore: 10, timeLimitMs: 99_999_999 },
  });
  assert.equal(topic.status, 400);
  // the existing limits still pass
  assert.equal((await put(fx.activityId, 'questions', quizBody(50))).status, 200);
});

test('grading queue is bounded: with 1 slot and 1 waiter the third caller gets 429 (spec 7.6)', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  registerGrader('StubQueue', async () => { await gate; return { score: 0, results: [] }; });
  const call = () => runGrading({ ActivityType: 'StubQueue' }, {});
  const first = call();
  const second = call();
  const third = await Promise.race([call().catch((err) => err), new Promise((r) => setTimeout(() => r('queued-forever'), 700))]);
  release();
  assert.equal(third?.status, 429, 'third caller must be refused, not queued');
  await Promise.all([first, second]);
  await runGrading({ ActivityType: 'StubQueue' }, {}); // slots are free again
});

test('sentinel: hidden values never reach any student response, error body or log across authoring -> submit', async () => {
  runnerMode = 'echo';
  const seen = [];
  const orig = {};
  for (const m of ['log', 'error', 'warn', 'info']) {
    orig[m] = console[m];
    console[m] = (...args) => seen.push(args.map((x) => (x instanceof Error ? `${x.message}${x.stack}` : typeof x === 'string' ? x : JSON.stringify(x))).join(' '));
  }
  const studentBodies = [];
  try {
    const s = async (...args) => { const r = await api(...args, ); studentBodies.push(JSON.stringify(r.body)); return r; };
    const sc = (method, path, body) => s(method, path, { cookie: student, body });

    const quiz = await createActivityFixture({ type: 'Quiz', status: 'Draft' });
    const qs = (await put(quiz.activityId, 'questions', quizBody(2, `${SENTINEL}-expl`))).body.questions;
    await publish(quiz.activityId);

    const code = await createActivityFixture({ type: 'Coding', status: 'Draft' });
    await put(code.activityId, 'test-cases', { testCases: [{ inputData: `${SENTINEL}-in`, expectedOutput: `${SENTINEL}-out` }] });
    await publish(code.activityId);

    let sqlId = null;
    if (isSqlSandboxAvailable()) {
      const sqlFx = await createActivityFixture({ type: 'SQL', status: 'Draft' });
      await put(sqlFx.activityId, 'sql-spec', {
        setupScript: 'CREATE TABLE s (v NVARCHAR(50)); INSERT s VALUES (N\'pub\');',
        expectedResult: { columns: ['v'], rows: [[`${SENTINEL}-result`]], orderMatters: false },
      });
      await publish(sqlFx.activityId);
      sqlId = sqlFx.activityId;
    }

    for (const fx of [quiz, code]) {
      await sc('GET', `/api/v1/topics/${fx.topicId}/activities`);
      await sc('GET', base(fx.activityId));
      await sc('GET', `${base(fx.activityId)}/draft`);
    }
    await sc('PUT', `${base(code.activityId)}/draft`, { content: 'x' });
    await sc('POST', `${base(quiz.activityId)}/submissions`, { answers: qs.map((q) => ({ questionId: q.questionId, optionId: q.options[1].optionId })) });
    await sc('POST', `${base(quiz.activityId)}/submissions`, { answers: [] });
    const sub = await sc('POST', `${base(code.activityId)}/submissions`, { source: 'x' });
    runnerMode = 'broken';
    await sc('POST', `${base(code.activityId)}/submissions`, { source: 'x' });
    runnerMode = 'echo';
    if (sqlId) {
      await sc('GET', base(sqlId));
      await sc('POST', `${base(sqlId)}/submissions`, { sql: 'SELECT v FROM s' });
      await sc('POST', `${base(sqlId)}/submissions`, { sql: 'SELEKT' });
    }
    await sc('GET', `${base(code.activityId)}/submissions/mine`);
    await sc('GET', `/api/v1/submissions/${sub.body.submissionId}`);
    await sc('POST', `${base(code.activityId)}/events`, { eventType: 'TabSwitch' });
    await sc('POST', `${base(code.activityId)}/events`, { eventType: 'bad' });
  } finally {
    Object.assign(console, orig);
  }
  assert.ok(studentBodies.length >= 14);
  const joined = studentBodies.join('\n');
  assert.ok(!joined.includes(SENTINEL), 'hidden value in a student response body');
  assert.ok(!seen.join('\n').includes(SENTINEL), 'hidden value in console output');
  assert.ok(!/isCorrect|explanation|expectedOutput|expectedResult|inputData|actualOutput|testCaseId/i.test(joined));
});
