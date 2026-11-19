import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';

// The submit limiter (10/min per user) counts every POST in this process; lift it before config is first imported.
process.env.RATE_LIMIT_SUBMIT_PER_MIN = '1000';
const { api, login, startServer, stopServer, demoUser, createActivityFixture, cleanupFixtures } = await import('./helpers.js');
const { query, queryOne } = await import('../src/db.js');
const { registerGrader } = await import('../src/assessment/grader.js');
const { HttpError } = await import('../src/http.js');

const SENTINEL = 'SENTINEL-m32-7c1e';
const base = (id) => `/api/v1/activities/${id}`;
let faculty;
let admin;
let student;
let studentId;

before(async () => {
  await startServer();
  [admin, faculty, student] = await Promise.all([login('admin'), login('faculty'), login('student')]);
  studentId = (await demoUser('student')).UserId;
});
after(async () => {
  await cleanupFixtures();
  await stopServer();
});

const count = async (table, activityId) => {
  const where = ['LearningActivity', 'Submissions'].includes(table)
    ? 'ActivityId = @a'
    : 'SubmissionId IN (SELECT SubmissionId FROM dbo.Submissions WHERE ActivityId = @a)';
  return (await queryOne(`SELECT COUNT(*) AS n FROM dbo.${table} WHERE ${where}`, { a: activityId })).n;
};

async function quizFixture() {
  const fx = await createActivityFixture({ type: 'Quiz' });
  const questions = [];
  for (const i of [1, 2]) {
    const q = await queryOne(
      `INSERT dbo.QuizQuestions (ActivityId, QuestionText, Explanation, Points, OrderIndex) OUTPUT INSERTED.QuestionId VALUES (@a, N'q', @e, 5, @i)`,
      { a: fx.activityId, e: `${SENTINEL}-expl`, i },
    );
    const opts = [];
    for (const [j, ok] of [[1, 1], [2, 0]]) {
      opts.push((await queryOne(`INSERT dbo.QuizOptions (QuestionId, OptionText, IsCorrect, OrderIndex) OUTPUT INSERTED.OptionId VALUES (@q, N'o', @c, @j)`, { q: q.QuestionId, c: ok, j })).OptionId);
    }
    questions.push({ questionId: q.QuestionId, opts });
  }
  return { ...fx, questions };
}
const fullAnswers = (fx) => fx.questions.map((q) => ({ questionId: q.questionId, optionId: q.opts[0] }));

async function codingFixture(type = 'Coding') {
  const fx = await createActivityFixture({ type });
  const tc = await queryOne(`INSERT dbo.TestCases (ActivityId, InputData, ExpectedOutput, OrderIndex) OUTPUT INSERTED.TestCaseId VALUES (@a, @i, @o, 1)`, {
    a: fx.activityId, i: `${SENTINEL}-in`, o: `${SENTINEL}-out`,
  });
  return { ...fx, testCaseId: tc.TestCaseId };
}

/* ------------------------------------ drafts ------------------------------------ */

test('draft: empty -> upsert -> overwrite; one row per student+activity', async () => {
  const { activityId } = await createActivityFixture({ type: 'Coding' });
  assert.deepEqual((await api('GET', `${base(activityId)}/draft`, { cookie: student })).body, { content: null });
  assert.equal((await api('PUT', `${base(activityId)}/draft`, { cookie: student, body: { content: 'v1' } })).status, 200);
  assert.equal((await api('PUT', `${base(activityId)}/draft`, { cookie: student, body: { content: 'v2' } })).status, 200);
  assert.equal((await api('GET', `${base(activityId)}/draft`, { cookie: student })).body.content, 'v2');
  const rows = await query('SELECT * FROM dbo.PracticeDrafts WHERE ActivityId = @a', { a: activityId });
  assert.equal(rows.length, 1);
});

test('draft: rejects Quiz, oversize, non-string, non-students, unpublished and unknown activities', async () => {
  const quiz = await createActivityFixture({ type: 'Quiz' });
  const coding = await createActivityFixture({ type: 'Coding' });
  const draftAct = await createActivityFixture({ type: 'Coding', status: 'Draft' });
  assert.equal((await api('PUT', `${base(quiz.activityId)}/draft`, { cookie: student, body: { content: 'x' } })).status, 400);
  assert.equal((await api('PUT', `${base(coding.activityId)}/draft`, { cookie: student, body: { content: 'x'.repeat(64 * 1024 + 1) } })).status, 400);
  assert.equal((await api('PUT', `${base(coding.activityId)}/draft`, { cookie: student, body: { content: 5 } })).status, 400);
  assert.equal((await api('PUT', `${base(coding.activityId)}/draft`, { cookie: student, body: { content: 'x'.repeat(64 * 1024) } })).status, 200);
  for (const cookie of [faculty, admin]) {
    assert.equal((await api('GET', `${base(coding.activityId)}/draft`, { cookie })).status, 403);
    assert.equal((await api('PUT', `${base(coding.activityId)}/draft`, { cookie, body: { content: 'x' } })).status, 403);
  }
  assert.equal((await api('GET', `${base(draftAct.activityId)}/draft`, { cookie: student })).status, 403);
  assert.equal((await api('GET', `${base(2_000_000_000)}/draft`, { cookie: student })).status, 404);
  assert.equal((await api('GET', `${base('abc')}/draft`, { cookie: student })).status, 400);
});

/* ----------------------------------- submit ----------------------------------- */

test('quiz submit: validates answers, grades via injected grader, writes one Graded row + answers + event', async () => {
  registerGrader('Quiz', async (activity, payload) => ({ score: payload.answers.length === 2 ? 5 : 0, results: [] }));
  const fx = await quizFixture();
  const url = `${base(fx.activityId)}/submissions`;
  const post = (body) => api('POST', url, { cookie: student, body });

  assert.equal((await post({})).status, 400);
  assert.equal((await post({ answers: [fullAnswers(fx)[0]] })).status, 400, 'every question must be answered');
  assert.equal((await post({ answers: [fullAnswers(fx)[0], fullAnswers(fx)[0]] })).status, 400, 'duplicate question');
  assert.equal((await post({ answers: [fullAnswers(fx)[0], { questionId: fx.questions[1].questionId, optionId: fx.questions[0].opts[0] }] })).status, 400, 'option of another question');
  assert.equal((await post({ answers: [{ questionId: 'x', optionId: 1 }] })).status, 400);
  assert.equal(await count('Submissions', fx.activityId), 0);

  const ok = await post({ answers: fullAnswers(fx) });
  assert.equal(ok.status, 201);
  assert.equal(ok.body.attemptNo, 1);
  assert.equal(ok.body.status, 'Graded');
  assert.equal(Number(ok.body.score), 5);
  const row = await queryOne('SELECT * FROM dbo.Submissions WHERE SubmissionId = @id', { id: ok.body.submissionId });
  assert.equal(row.GradedBy, null);
  assert.ok(row.GradedAt);
  assert.equal(await count('SubmissionAnswers', fx.activityId), 2);
  assert.equal(await count('LearningActivity', fx.activityId), 1);
  assert.equal((await post({ answers: fullAnswers(fx) })).body.attemptNo, 2);
});

test('score is clamped to [0, MaxScore]', async () => {
  const fx = await quizFixture();
  for (const [raw, want] of [[99, 10], [-3, 0], [3.456, 3.46]]) {
    registerGrader('Quiz', async () => ({ score: raw, results: [] }));
    const res = await api('POST', `${base(fx.activityId)}/submissions`, { cookie: student, body: { answers: fullAnswers(fx) } });
    assert.equal(Number(res.body.score), want);
  }
  registerGrader('Quiz', async () => ({ score: Number.NaN, results: [] }));
  assert.equal((await api('POST', `${base(fx.activityId)}/submissions`, { cookie: student, body: { answers: fullAnswers(fx) } })).status, 503);
});

test('concurrent submits get distinct consecutive AttemptNo (UPDLOCK/HOLDLOCK allocation)', async () => {
  registerGrader('SQL', async () => ({ score: 1, results: [] }));
  const { activityId } = await createActivityFixture({ type: 'SQL' });
  const rs = await Promise.all([1, 2, 3, 4].map(() => api('POST', `${base(activityId)}/submissions`, { cookie: student, body: { sql: 'select 1' } })));
  assert.deepEqual(rs.map((r) => r.status), [201, 201, 201, 201]);
  assert.deepEqual(rs.map((r) => r.body.attemptNo).sort(), [1, 2, 3, 4]);
});

test('coding submit: results stored, student sees only passed/total flags; bad body 400', async () => {
  const fx = await codingFixture();
  registerGrader('Coding', async () => ({
    score: 10,
    passed: 1,
    total: 1,
    compileError: false,
    timedOut: false,
    results: [{ testCaseId: fx.testCaseId, passed: true, actualOutput: `${SENTINEL}-actual`, executionTimeMs: 7 }],
  }));
  const url = `${base(fx.activityId)}/submissions`;
  assert.equal((await api('POST', url, { cookie: student, body: { source: '' } })).status, 400);
  assert.equal((await api('POST', url, { cookie: student, body: { source: 5 } })).status, 400);
  const res = await api('POST', url, { cookie: student, body: { source: 'int main(){}' } });
  assert.equal(res.status, 201);
  assert.equal(res.body.passed, 1);
  assert.equal(res.body.total, 1);
  assert.equal(res.body.compileError, false);
  assert.equal(res.body.submittedContent, 'int main(){}');
  assert.ok(!JSON.stringify(res.body).includes(SENTINEL));
  assert.equal(await count('TestCaseResults', fx.activityId), 1);
});

test('grader failure or busy: nothing is written (429/503 pass through, other errors become 503)', async () => {
  const fx = await codingFixture();
  const url = `${base(fx.activityId)}/submissions`;
  for (const [err, want] of [[new HttpError(429, 'busy'), 429], [new HttpError(503, 'runner down'), 503], [new Error('boom'), 503]]) {
    registerGrader('Coding', async () => { throw err; });
    const res = await api('POST', url, { cookie: student, body: { source: 'x' } });
    assert.equal(res.status, want);
  }
  assert.equal(await count('Submissions', fx.activityId), 0);
  assert.equal(await count('LearningActivity', fx.activityId), 0);
});

test('assignment: stored Submitted with NULL score, no grader; practice and non-students rejected', async () => {
  const a = await createActivityFixture({ type: 'Assignment' });
  const url = `${base(a.activityId)}/submissions`;
  assert.equal((await api('POST', url, { cookie: student, body: {} })).status, 400);
  const res = await api('POST', url, { cookie: student, body: { content: 'my essay' } });
  assert.equal(res.status, 201);
  assert.equal(res.body.status, 'Submitted');
  assert.equal(res.body.score, null);
  assert.equal(await count('LearningActivity', a.activityId), 1);

  const p = await createActivityFixture({ type: 'Practice' });
  assert.equal((await api('POST', `${base(p.activityId)}/submissions`, { cookie: student, body: { content: 'x' } })).status, 400);
  for (const cookie of [faculty, admin]) assert.equal((await api('POST', url, { cookie, body: { content: 'x' } })).status, 403);
  const hidden = await createActivityFixture({ type: 'Assignment', status: 'Draft' });
  assert.equal((await api('POST', `${base(hidden.activityId)}/submissions`, { cookie: student, body: { content: 'x' } })).status, 403);
  assert.equal((await api('POST', `${base(2_000_000_000)}/submissions`, { cookie: student, body: { content: 'x' } })).status, 404);
});

/* ------------------------------- read back / events ------------------------------- */

test('mine and GET /submissions/:id: own attempts for students, faculty/admin projection by id', async () => {
  const a = await createActivityFixture({ type: 'Assignment' });
  const sub = (await api('POST', `${base(a.activityId)}/submissions`, { cookie: student, body: { content: 'one' } })).body;
  await api('POST', `${base(a.activityId)}/submissions`, { cookie: student, body: { content: 'two' } });
  const mine = await api('GET', `${base(a.activityId)}/submissions/mine`, { cookie: student });
  assert.equal(mine.status, 200);
  assert.deepEqual(mine.body.map((s) => s.attemptNo), [1, 2]);
  assert.ok(mine.body.every((s) => !('studentId' in s) && !('gradedBy' in s)));
  assert.equal((await api('GET', `${base(a.activityId)}/submissions/mine`, { cookie: faculty })).status, 403);

  const own = await api('GET', `/api/v1/submissions/${sub.submissionId}`, { cookie: student });
  assert.equal(own.status, 200);
  assert.ok(!('studentId' in own.body));
  for (const cookie of [faculty, admin]) {
    const r = await api('GET', `/api/v1/submissions/${sub.submissionId}`, { cookie });
    assert.equal(r.status, 200);
    assert.equal(r.body.studentId, studentId);
  }
  assert.equal((await api('GET', '/api/v1/submissions/2000000000', { cookie: student })).status, 404);
});

test('events: TabSwitch only, 1 per 5s per student+activity (excess silently 204), never ActivitySubmitted', async () => {
  const a = await createActivityFixture({ type: 'Coding' });
  const url = `${base(a.activityId)}/events`;
  const first = await api('POST', url, { cookie: student, body: { eventType: 'TabSwitch' } });
  assert.equal(first.status, 201);
  for (let i = 0; i < 3; i += 1) assert.equal((await api('POST', url, { cookie: student, body: { eventType: 'TabSwitch' } })).status, 204);
  assert.equal(await count('LearningActivity', a.activityId), 1);
  assert.equal((await api('POST', url, { cookie: student, body: { eventType: 'ActivitySubmitted' } })).status, 400);
  assert.equal((await api('POST', url, { cookie: student, body: {} })).status, 400);
  assert.equal((await api('POST', url, { cookie: faculty, body: { eventType: 'TabSwitch' } })).status, 403);
  const draft = await createActivityFixture({ type: 'Coding', status: 'Draft' });
  assert.equal((await api('POST', `${base(draft.activityId)}/events`, { cookie: student, body: { eventType: 'TabSwitch' } })).status, 403);
  const other = await createActivityFixture({ type: 'Coding' });
  assert.equal((await api('POST', `${base(other.activityId)}/events`, { cookie: student, body: { eventType: 'TabSwitch' } })).status, 201, 'limit is per activity');
});

/* --------------------------------- hidden data --------------------------------- */

test('sentinel: hidden values never appear in any student response, error body or console output', async () => {
  const seen = [];
  const orig = {};
  for (const m of ['log', 'error', 'warn', 'info']) {
    orig[m] = console[m];
    console[m] = (...args) => seen.push(args.map((x) => (x instanceof Error ? `${x.message}${x.stack}` : typeof x === 'string' ? x : JSON.stringify(x))).join(' '));
  }
  const bodies = [];
  try {
    const call = async (...args) => { const r = await api(...args); bodies.push(JSON.stringify(r.body)); return r; };
    const quiz = await quizFixture();
    const code = await codingFixture();
    const sql = await createActivityFixture({ type: 'SQL' });
    await query('INSERT dbo.SqlTaskSpecs (ActivityId, SetupScript, ExpectedResult) VALUES (@a, N\'select 1\', @r)', { a: sql.activityId, r: JSON.stringify({ rows: [[`${SENTINEL}-result`]] }) });
    registerGrader('Quiz', async () => ({ score: 5, results: [] }));
    registerGrader('Coding', async () => ({ score: 5, passed: 0, total: 1, results: [{ testCaseId: code.testCaseId, passed: false, actualOutput: `${SENTINEL}-actual`, executionTimeMs: 1 }] }));
    registerGrader('SQL', async () => { throw new Error('sandbox unavailable'); });
    const ok = await call('POST', `${base(quiz.activityId)}/submissions`, { cookie: student, body: { answers: fullAnswers(quiz) } });
    await call('POST', `${base(quiz.activityId)}/submissions`, { cookie: student, body: { answers: [] } });
    await call('POST', `${base(code.activityId)}/submissions`, { cookie: student, body: { source: 'x' } });
    await call('POST', `${base(sql.activityId)}/submissions`, { cookie: student, body: { sql: 'select 1' } });
    await call('GET', `${base(code.activityId)}/submissions/mine`, { cookie: student });
    await call('GET', `/api/v1/submissions/${ok.body.submissionId}`, { cookie: student });
    await call('PUT', `${base(code.activityId)}/draft`, { cookie: student, body: { content: 'x' } });
    await call('GET', `${base(code.activityId)}/draft`, { cookie: student });
    await call('POST', `${base(code.activityId)}/events`, { cookie: student, body: { eventType: 'TabSwitch' } });
    await call('POST', `${base(code.activityId)}/events`, { cookie: student, body: { eventType: 'bad' } });
  } finally {
    Object.assign(console, orig);
  }
  assert.ok(bodies.length >= 10);
  assert.ok(!bodies.join('\n').includes(SENTINEL), 'hidden value in a response body');
  assert.ok(!seen.join('\n').includes(SENTINEL), 'hidden value in console output');
  assert.ok(!/isCorrect|explanation|expectedOutput|expectedResult|inputData|actualOutput/i.test(bodies.join('\n')));
});
