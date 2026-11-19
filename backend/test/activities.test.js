import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer, createActivityFixture, cleanupFixtures, unique } from './helpers.js';
import { query } from '../src/db.js';

let admin;
let faculty;
let student;
before(async () => {
  await startServer();
  [admin, faculty, student] = await Promise.all([login('admin'), login('faculty'), login('student')]);
});
after(async () => {
  await cleanupFixtures();
  await stopServer();
});

const SENTINEL = `SENTINEL_${unique()}`;
const base = (over = {}) => ({ activityType: 'Quiz', title: 't', instructions: 'i', isGraded: true, maxScore: 10, ...over });
const create = (topicId, body, cookie = faculty) => api('POST', `/api/v1/topics/${topicId}/activities`, { cookie, body });
const draftFixture = (type = 'Quiz', subject) => createActivityFixture({ type, status: 'Draft', topicStatus: 'Published', subject });
const quiz = (extra = '') => [
  {
    questionText: `Q1 ${extra}`, explanation: `${SENTINEL}-expl`, points: 2.5,
    options: [{ optionText: 'a', isCorrect: true }, { optionText: 'b', isCorrect: false }],
  },
  { questionText: 'Q2', points: 1, options: [{ optionText: 'x', isCorrect: false }, { optionText: 'y', isCorrect: true }] },
];

test('create validates and defaults, admin and student get 403, bad ids 400/404', async () => {
  const { topicId } = await draftFixture();
  const ok = await create(topicId, base());
  assert.equal(ok.status, 201);
  assert.equal(ok.body.activity.status, 'Draft');
  assert.equal((await create(topicId, base(), admin)).status, 403);
  assert.equal((await create(topicId, base(), student)).status, 403);
  assert.equal((await create(topicId, base({ activityType: 'Nope' }))).status, 400);
  assert.equal((await create(topicId, base({ maxScore: -1 }))).status, 400);
  assert.equal((await create(topicId, base({ maxScore: undefined }))).status, 400);
  assert.equal((await create(topicId, base({ isGraded: false }))).status, 400);
  assert.equal((await create(topicId, base({ title: '' }))).status, 400);
  assert.equal((await create(topicId, base({ timeLimitMs: 0 }))).status, 400);
  const practice = await create(topicId, base({ activityType: 'Practice', isGraded: false, maxScore: undefined }));
  assert.equal(practice.status, 201);
  assert.equal(practice.body.activity.maxScore, null);
  assert.equal((await create(99999999, base())).status, 404);
  assert.equal((await api('GET', '/api/v1/activities/abc', { cookie: faculty })).status, 400);
  assert.equal((await api('GET', '/api/v1/activities/99999999', { cookie: faculty })).status, 404);
});

test('coding timeLimitMs defaults; PATCH edits, null clears hints, status ignored', async () => {
  const { topicId } = await draftFixture();
  const c = await create(topicId, base({ activityType: 'Coding', hints: 'h' }));
  assert.equal(c.body.activity.timeLimitMs, 3000);
  const id = c.body.activity.activityId;
  const p = await api('PATCH', `/api/v1/activities/${id}`, { cookie: faculty, body: { title: 'new', hints: null, status: 'Published' } });
  assert.equal(p.status, 200);
  assert.equal(p.body.activity.title, 'new');
  assert.equal(p.body.activity.hints, null);
  assert.equal(p.body.activity.status, 'Draft');
  assert.equal((await api('PATCH', `/api/v1/activities/${id}`, { cookie: admin, body: { title: 'x' } })).status, 403);
  assert.equal((await api('PATCH', `/api/v1/activities/${id}`, { cookie: faculty, body: {} })).status, 400);
});

test('quiz questions: validation, replace, maxScore sum, wrong type', async () => {
  const { topicId } = await draftFixture();
  const id = (await create(topicId, base())).body.activity.activityId;
  const put = (questions, cookie = faculty) => api('PUT', `/api/v1/activities/${id}/questions`, { cookie, body: { questions } });
  const opts = (a, b) => [{ optionText: 'a', isCorrect: a }, { optionText: 'b', isCorrect: b }];
  assert.equal((await put([])).status, 400);
  assert.equal((await put([{ questionText: 'q', points: 1, options: [{ optionText: 'a', isCorrect: true }] }])).status, 400);
  assert.equal((await put([{ questionText: 'q', points: 1, options: opts(true, true) }])).status, 400);
  assert.equal((await put([{ questionText: 'q', points: 1, options: opts(false, false) }])).status, 400);
  assert.equal((await put([{ questionText: 'q', points: 0, options: opts(true, false) }])).status, 400);
  assert.equal((await put(quiz(), admin)).status, 403);
  assert.equal((await api('POST', `/api/v1/activities/${id}/status`, { cookie: faculty, body: { status: 'Published' } })).status, 400);
  const r = await put(quiz());
  assert.equal(r.status, 200);
  assert.equal(r.body.questions.length, 2);
  assert.equal(r.body.questions[0].options[0].isCorrect, true);
  assert.equal((await put(quiz('v2'))).body.questions.length, 2);
  const got = await api('GET', `/api/v1/activities/${id}`, { cookie: faculty });
  assert.equal(got.body.activity.maxScore, 3.5);
  assert.equal(got.body.activity.questions[0].questionText, 'Q1 v2');
  const tc = await api('PUT', `/api/v1/activities/${id}/test-cases`, { cookie: faculty, body: { testCases: [{ expectedOutput: 'x' }] } });
  assert.equal(tc.status, 400);
});

test('publish, edit lock, no reverse transitions, student projection and sentinel', async () => {
  const { topicId } = await draftFixture();
  const id = (await create(topicId, base())).body.activity.activityId;
  await api('PUT', `/api/v1/activities/${id}/questions`, { cookie: faculty, body: { questions: quiz() } });
  const pub = (status, cookie = faculty) => api('POST', `/api/v1/activities/${id}/status`, { cookie, body: { status } });
  assert.equal((await pub('Published', admin)).status, 403);
  assert.equal((await pub('Bogus')).status, 400);
  assert.equal((await pub('Published')).status, 200);
  assert.equal((await pub('Published')).status, 409);
  assert.equal((await pub('Draft')).status, 400);
  assert.equal((await api('PATCH', `/api/v1/activities/${id}`, { cookie: faculty, body: { title: 'z' } })).status, 409);
  assert.equal((await api('PUT', `/api/v1/activities/${id}/questions`, { cookie: faculty, body: { questions: quiz() } })).status, 409);

  const list = await api('GET', `/api/v1/topics/${topicId}/activities`, { cookie: student });
  assert.equal(list.status, 200);
  assert.equal(list.body.activities.length, 1);
  const one = await api('GET', `/api/v1/activities/${id}`, { cookie: student });
  assert.equal(one.status, 200);
  const text = JSON.stringify([list.body, one.body]);
  assert.ok(!text.includes(SENTINEL));
  assert.ok(!/isCorrect|explanation|expectedOutput|inputData|expectedResult/.test(text));
  assert.equal(one.body.activity.questions.length, 2);
  const fac = await api('GET', `/api/v1/activities/${id}`, { cookie: admin });
  assert.equal(fac.status, 200);
  assert.ok(JSON.stringify(fac.body).includes(SENTINEL));
  assert.equal((await pub('Archived')).status, 200);
  assert.equal((await api('GET', `/api/v1/activities/${id}`, { cookie: student })).status, 403);
  assert.equal((await pub('Published')).status, 409);
});

test('draft activities are hidden from students; lock once submissions exist', async () => {
  const { topicId } = await draftFixture();
  const id = (await create(topicId, base({ activityType: 'Assignment' }))).body.activity.activityId;
  assert.equal((await api('GET', `/api/v1/activities/${id}`, { cookie: student })).status, 403);
  const list = await api('GET', `/api/v1/topics/${topicId}/activities`, { cookie: student });
  assert.equal(list.body.activities.length, 0);
  const fl = await api('GET', `/api/v1/topics/${topicId}/activities`, { cookie: faculty });
  assert.equal(fl.body.activities.length, 2); // fixture activity + the new draft
  const { UserId } = (await query(`SELECT UserId FROM dbo.Users WHERE Email = N'student@synora.local'`))[0];
  await query(
    `INSERT dbo.Submissions (ActivityId, StudentId, AttemptNo, Status, SubmittedContent) VALUES (@id, @u, 1, N'Submitted', N'x')`,
    { id, u: UserId },
  );
  assert.equal((await api('PATCH', `/api/v1/activities/${id}`, { cookie: faculty, body: { title: 'z' } })).status, 409);
});

test('coding test cases: validate, replace, hidden from students, publish needs cases', async () => {
  const { topicId } = await draftFixture('Coding');
  const id = (await create(topicId, base({ activityType: 'Coding' }))).body.activity.activityId;
  const put = (testCases) => api('PUT', `/api/v1/activities/${id}/test-cases`, { cookie: faculty, body: { testCases } });
  const pub = () => api('POST', `/api/v1/activities/${id}/status`, { cookie: faculty, body: { status: 'Published' } });
  assert.equal((await put([])).status, 400);
  assert.equal((await put([{ inputData: 'a' }])).status, 400);
  assert.equal((await pub()).status, 400);
  const r = await put([{ inputData: SENTINEL, expectedOutput: `${SENTINEL}out` }, { expectedOutput: 'b' }]);
  assert.equal(r.status, 200);
  assert.equal(r.body.testCases[1].inputData, null);
  assert.equal((await pub()).status, 200);
  const one = await api('GET', `/api/v1/activities/${id}`, { cookie: student });
  assert.equal(one.status, 200);
  assert.equal(one.body.activity.testCases, undefined, 'students get no test case listing');
  assert.ok(!JSON.stringify(one.body).includes(SENTINEL));
});

test('sql spec: validate, store, setupScript visible, expectedResult hidden', async () => {
  const { topicId } = await draftFixture('SQL', 'DBMS/SQL');
  const id = (await create(topicId, base({ activityType: 'SQL' }))).body.activity.activityId;
  const put = (body) => api('PUT', `/api/v1/activities/${id}/sql-spec`, { cookie: faculty, body });
  const good = { setupScript: 'CREATE TABLE t(a INT); INSERT t VALUES (1);', expectedResult: { columns: ['a'], rows: [[1]], orderMatters: false } };
  assert.equal((await put({ setupScript: good.setupScript })).status, 400);
  assert.equal((await put({ ...good, expectedResult: { columns: ['a', 'a'], rows: [], orderMatters: false } })).status, 400);
  assert.equal((await put({ ...good, expectedResult: { columns: ['a'], rows: [[1, 2]], orderMatters: false } })).status, 400);
  assert.equal((await put({ ...good, expectedResult: { columns: ['a'], rows: [], orderMatters: 'x' } })).status, 400);
  assert.equal((await put({ ...good, setupScript: 'EXEC xp_cmdshell 1' })).status, 400);
  assert.equal((await api('POST', `/api/v1/activities/${id}/status`, { cookie: faculty, body: { status: 'Published' } })).status, 400);
  const r = await put({ ...good, setupScript: `${good.setupScript} -- ${SENTINEL}` });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.sqlSpec.expectedResult.rows, [[1]]);
  const wrongType = await createActivityFixture({ type: 'Quiz', status: 'Draft' });
  assert.equal((await api('PUT', `/api/v1/activities/${wrongType.activityId}/sql-spec`, { cookie: faculty, body: good })).status, 400);
  const pub = await api('POST', `/api/v1/activities/${id}/status`, { cookie: faculty, body: { status: 'Published' } });
  assert.ok([200, 503].includes(pub.status), `publish ${pub.status}`);
  if (pub.status === 200) {
    const one = await api('GET', `/api/v1/activities/${id}`, { cookie: student });
    assert.ok(one.body.activity.sqlSpec.setupScript.includes(SENTINEL));
    assert.ok(!JSON.stringify(one.body).includes('orderMatters'));
  }
});
