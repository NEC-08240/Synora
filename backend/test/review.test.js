import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';

const { api, login, startServer, stopServer, demoUser, createActivityFixture, cleanupFixtures } = await import('./helpers.js');
const { query, queryOne } = await import('../src/db.js');

let faculty;
let student;
let admin;
let fx;
let studentUser;
let subId;
before(async () => {
  await startServer();
  [faculty, student, admin] = await Promise.all([login('faculty'), login('student'), login('admin')]);
  studentUser = await demoUser('student');
  fx = await createActivityFixture({ type: 'Assignment' });
  const row = await queryOne(
    `INSERT dbo.Submissions (StudentId, ActivityId, AttemptNo, SubmittedContent, Status)
     OUTPUT INSERTED.SubmissionId VALUES (@s, @a, 1, N'my essay', 'Submitted')`,
    { s: studentUser.UserId, a: fx.activityId },
  );
  subId = row.SubmissionId;
});
after(async () => {
  await cleanupFixtures();
  await stopServer();
});

const list = (cookie, qs = '') => api('GET', `/api/v1/activities/${fx.activityId}/submissions${qs}`, { cookie });
const grade = (cookie, body, id = subId) => api('PATCH', `/api/v1/submissions/${id}/grade`, { cookie, body });

test('#15 faculty and admin list submissions; student is refused', async () => {
  for (const c of [faculty, admin]) {
    const res = await list(c);
    assert.equal(res.status, 200);
    assert.ok(res.body.some((s) => s.submissionId === subId && s.studentId === studentUser.UserId));
  }
  assert.equal((await list(student)).status, 403);
});

test('#15 filters and paging are validated', async () => {
  assert.equal((await list(faculty, '?status=Graded')).body.length, 0);
  assert.equal((await list(faculty, '?status=Submitted')).body.length, 1);
  assert.equal((await list(faculty, '?limit=1&offset=1')).body.length, 0);
  assert.equal((await list(faculty, '?limit=101')).status, 400);
  assert.equal((await list(faculty, '?status=Nope')).status, 400);
});

test('#16 grade: validates score, faculty only, sets Graded fields', async () => {
  assert.equal((await grade(admin, { score: 5 })).status, 403);
  assert.equal((await grade(student, { score: 5 })).status, 403);
  assert.equal((await grade(faculty, { score: 11 })).status, 400);
  assert.equal((await grade(faculty, { score: -1 })).status, 400);
  assert.equal((await grade(faculty, {})).status, 400);
  assert.equal((await grade(faculty, { score: 5 }, 999999999)).status, 404);
  const res = await grade(faculty, { score: 7.5, feedback: 'good' });
  assert.equal(res.status, 200);
  assert.equal(res.body.status, 'Graded');
  assert.equal(Number(res.body.score), 7.5);
  assert.equal(res.body.feedback, 'good');
  const f = await demoUser('faculty');
  assert.equal(res.body.gradedBy, f.UserId);
  const again = await grade(faculty, { score: 9 }); // override
  assert.equal(again.status, 200);
  assert.equal(Number(again.body.score), 9);
});

test('#17 results: faculty and admin see hidden per-case data; student 403', async () => {
  const tc = await queryOne(
    `INSERT dbo.TestCases (ActivityId, InputData, ExpectedOutput, OrderIndex) OUTPUT INSERTED.TestCaseId VALUES (@a, N'in', N'out', 1)`,
    { a: fx.activityId },
  );
  await query(`INSERT dbo.TestCaseResults (SubmissionId, TestCaseId, Passed, ActualOutput, ExecutionTimeMs) VALUES (@s, @t, 1, N'out', 5)`, { s: subId, t: tc.TestCaseId });
  for (const c of [faculty, admin]) {
    const res = await api('GET', `/api/v1/submissions/${subId}/results`, { cookie: c });
    assert.equal(res.status, 200);
    assert.deepEqual(res.body.map((r) => [r.testCaseId, r.passed, r.actualOutput]), [[tc.TestCaseId, true, 'out']]);
  }
  assert.equal((await api('GET', `/api/v1/submissions/${subId}/results`, { cookie: student })).status, 403);
  assert.equal((await api('GET', '/api/v1/submissions/999999999/results', { cookie: faculty })).status, 404);
});
