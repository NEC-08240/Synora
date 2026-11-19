import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer, demoUser, createActivityFixture, cleanupFixtures } from './helpers.js';
import { config } from '../src/config.js';
import {
  assertCanReadActivity,
  assertCanAuthorActivity,
  assertCanGradeSubmission,
  assertCanReadSubmission,
  assertStudent,
  loadActivity,
} from '../src/assessment/access.js';
import * as project from '../src/assessment/project.js';
import { registerGrader, runGrading } from '../src/assessment/grader.js';

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

const ENDPOINTS = [
  ['GET', '/api/v1/topics/1/activities'],
  ['POST', '/api/v1/topics/1/activities'],
  ['GET', '/api/v1/activities/1'],
  ['PATCH', '/api/v1/activities/1'],
  ['POST', '/api/v1/activities/1/status'],
  ['PUT', '/api/v1/activities/1/questions'],
  ['PUT', '/api/v1/activities/1/test-cases'],
  ['PUT', '/api/v1/activities/1/sql-spec'],
  ['GET', '/api/v1/activities/1/draft'],
  ['PUT', '/api/v1/activities/1/draft'],
  ['POST', '/api/v1/activities/1/submissions'],
  ['GET', '/api/v1/activities/1/submissions/mine'],
  ['GET', '/api/v1/submissions/1'],
  ['POST', '/api/v1/activities/1/events'],
  ['GET', '/api/v1/activities/1/submissions'],
  ['PATCH', '/api/v1/submissions/1/grade'],
  ['GET', '/api/v1/submissions/1/results'],
];

/* ------------------------------ routing / mounting ------------------------------ */

test('all 17 assessment endpoints are mounted as 501 stubs behind auth', async () => {
  assert.equal(ENDPOINTS.length, 17);
  for (const [method, path] of ENDPOINTS) {
    const anon = await api(method, path);
    assert.equal(anon.status, 401, `${method} ${path} unauthenticated`);
    const res = await api(method, path, { cookie: faculty, body: method === 'GET' ? undefined : {} });
    assert.equal(res.status, 501, `${method} ${path}`);
    assert.ok(res.body.error, `${method} ${path} has {error}`);
  }
});

test('mounting does not shadow existing routes or the 404 fallthrough', async () => {
  for (const cookie of [admin, faculty, student]) {
    assert.equal((await api('GET', '/api/v1/subjects', { cookie })).status, 200);
  }
  assert.equal((await api('GET', '/api/v1/definitely-not-a-route', { cookie: faculty })).status, 404);
  assert.equal((await api('GET', '/api/v1/activities/1/nope', { cookie: faculty })).status, 404);
});

test('submit endpoint is rate limited per user, other endpoints are not touched by that limiter', async () => {
  const max = config.rateLimits.submit;
  assert.ok(Number.isInteger(max) && max > 0);
  for (let i = 0; i < max; i += 1) {
    assert.equal((await api('POST', '/api/v1/activities/1/submissions', { cookie: student, body: {} })).status, 501);
  }
  const limited = await api('POST', '/api/v1/activities/1/submissions', { cookie: student, body: {} });
  assert.equal(limited.status, 429);
  assert.equal((await api('GET', '/api/v1/activities/1/submissions/mine', { cookie: student })).status, 501);
});

test('config exposes a bounded grading concurrency', () => {
  assert.ok(Number.isInteger(config.assessment.gradeConcurrency) && config.assessment.gradeConcurrency >= 1);
});

/* ---------------------------------- access ---------------------------------- */

test('assertCanReadActivity: students need a Published activity under a Published topic allocated to their batch', async () => {
  const s = await demoUser('student');
  const ok = await createActivityFixture();
  await assertCanReadActivity(s, await loadActivity(ok.activityId));

  const draft = await createActivityFixture({ status: 'Draft' });
  await assert.rejects(assertCanReadActivity(s, await loadActivity(draft.activityId)), { status: 403 });

  const hiddenTopic = await createActivityFixture({ topicStatus: 'Draft' });
  await assert.rejects(assertCanReadActivity(s, await loadActivity(hiddenTopic.activityId)), { status: 403 });

  const stranger = { UserId: 2_000_000_001, RoleName: 'Student', BatchId: -1 };
  await assert.rejects(assertCanReadActivity(stranger, await loadActivity(ok.activityId)), { status: 403 });
});

test('assertCanReadActivity: assigned faculty and admin may read drafts, unassigned faculty may not', async () => {
  const f = await demoUser('faculty');
  const a = await demoUser('admin');
  const draft = await createActivityFixture({ status: 'Draft' });
  const activity = await loadActivity(draft.activityId);
  await assertCanReadActivity(f, activity);
  await assertCanReadActivity(a, activity);
  await assert.rejects(assertCanReadActivity({ UserId: 2_000_000_002, RoleName: 'Faculty', BatchId: null }, activity), { status: 403 });
});

test('loadActivity: unknown id is 404', async () => {
  await assert.rejects(loadActivity(2_000_000_000), { status: 404 });
});

test('assertCanAuthorActivity (D1): faculty assigned in >=1 batch only; Admin and Student are 403', async () => {
  const f = await demoUser('faculty');
  const { subjectId } = await createActivityFixture();
  await assertCanAuthorActivity(f, subjectId);
  await assert.rejects(assertCanAuthorActivity(await demoUser('admin'), subjectId), { status: 403 });
  await assert.rejects(assertCanAuthorActivity(await demoUser('student'), subjectId), { status: 403 });
  await assert.rejects(assertCanAuthorActivity({ UserId: 2_000_000_003, RoleName: 'Faculty', BatchId: null }, subjectId), { status: 403 });
});

test('assertCanGradeSubmission: faculty assigned to the STUDENT batch for the subject; Admin read-only', async () => {
  const f = await demoUser('faculty');
  const s = await demoUser('student');
  const { activityId } = await createActivityFixture();
  const submission = { StudentId: s.UserId, ActivityId: activityId };
  await assertCanGradeSubmission(f, submission);
  await assert.rejects(assertCanGradeSubmission(await demoUser('admin'), submission), { status: 403 });
  await assert.rejects(assertCanGradeSubmission(s, submission), { status: 403 });
  await assert.rejects(assertCanGradeSubmission({ UserId: 2_000_000_004, RoleName: 'Faculty', BatchId: null }, submission), { status: 403 });
});

test('assertCanReadSubmission: owner student, batch faculty and admin; other students 403', async () => {
  const f = await demoUser('faculty');
  const a = await demoUser('admin');
  const s = await demoUser('student');
  const { activityId } = await createActivityFixture();
  const submission = { StudentId: s.UserId, ActivityId: activityId };
  await assertCanReadSubmission(s, submission);
  await assertCanReadSubmission(f, submission);
  await assertCanReadSubmission(a, submission);
  await assert.rejects(assertCanReadSubmission({ UserId: s.UserId + 1_000_000, RoleName: 'Student', BatchId: s.BatchId }, submission), { status: 403 });
  await assert.rejects(assertCanReadSubmission({ UserId: 2_000_000_005, RoleName: 'Faculty', BatchId: null }, submission), { status: 403 });
});

test('assertStudent rejects every other role', async () => {
  assertStudent(await demoUser('student'));
  assert.throws(() => assertStudent(faculty && { RoleName: 'Faculty' }), { status: 403 });
  assert.throws(() => assertStudent({ RoleName: 'Administrator' }), { status: 403 });
});

/* -------------------------------- projections -------------------------------- */

const SENTINEL = 'SENTINEL-hidden-9f3a';
const hiddenQuestion = {
  QuestionId: 1,
  QuestionText: 'q?',
  Explanation: `${SENTINEL}-explanation`,
  Points: 2,
  OrderIndex: 1,
  options: [
    { OptionId: 10, OptionText: 'a', IsCorrect: true, OrderIndex: 1 },
    { OptionId: 11, OptionText: 'b', IsCorrect: false, OrderIndex: 2 },
  ],
};
const hiddenTestCase = { TestCaseId: 5, InputData: `${SENTINEL}-in`, ExpectedOutput: `${SENTINEL}-out`, OrderIndex: 1 };
const hiddenSql = { SetupScript: 'CREATE TABLE t(a INT)', ExpectedResult: `{"rows":["${SENTINEL}-result"]}` };
const activityRow = {
  ActivityId: 1, TopicId: 1, Title: 't', Instructions: 'i', ActivityType: 'Coding', IsGraded: true, MaxScore: 10,
  StarterCode: null, Hints: null, TimeLimitMs: 2000, Status: 'Published', CreatedBy: 3,
};

test('student projections never contain hidden answer-key data', () => {
  const out = JSON.stringify([
    project.activityStudent(activityRow, { questions: [hiddenQuestion], testCases: [hiddenTestCase], sqlSpec: hiddenSql }),
    project.questionStudent(hiddenQuestion),
    project.testCaseStudent(hiddenTestCase),
    project.sqlSpecStudent(hiddenSql),
    project.resultStudent({ passed: 1, total: 2, compileError: false, timedOut: false, ActualOutput: `${SENTINEL}-actual`, stderr: `${SENTINEL}-err` }),
    project.submissionStudent({
      SubmissionId: 9, ActivityId: 1, StudentId: 3, AttemptNo: 1, Status: 'Graded', Score: 5, Feedback: null,
      SubmittedContent: 'my code', SubmittedAt: new Date(0), GradedAt: null, GradedBy: null,
      passed: 1, total: 2, results: [{ ActualOutput: `${SENTINEL}-actual`, ExecutionTimeMs: 3 }],
    }),
  ]);
  assert.ok(!out.includes(SENTINEL), 'a hidden value leaked into a student projection');
  assert.ok(!/isCorrect|explanation|expectedResult|expectedOutput|inputData|actualOutput/i.test(out));
  assert.ok(out.includes('CREATE TABLE t(a INT)'), 'SetupScript is student-visible (spec 6, hidden-data protection)');
});

test('faculty projections include the authoring data students must not see', () => {
  const out = JSON.stringify([
    project.questionFaculty(hiddenQuestion),
    project.testCaseFaculty(hiddenTestCase),
    project.sqlSpecFaculty(hiddenSql),
    project.resultFaculty({ TestCaseId: 5, Passed: true, ActualOutput: `${SENTINEL}-actual`, ExecutionTimeMs: 3 }),
  ]);
  for (const part of ['explanation', 'in', 'out', 'result', 'actual']) assert.ok(out.includes(`${SENTINEL}-${part}`), part);
  assert.ok(out.includes('"isCorrect":true'));
});

/* ---------------------------------- graders ---------------------------------- */

test('grader registry: registerGrader is the seam, runGrading dispatches by ActivityType and bounds concurrency', async () => {
  const seen = [];
  let running = 0;
  let peak = 0;
  registerGrader('Quiz', async (activity, payload) => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((r) => setTimeout(r, 15));
    running -= 1;
    seen.push(payload.n);
    return { score: payload.n, results: [] };
  });
  const out = await Promise.all(Array.from({ length: config.assessment.gradeConcurrency + 3 }, (_, n) => runGrading({ ActivityType: 'Quiz' }, { n })));
  assert.deepEqual(out.map((o) => o.score), out.map((_, n) => n));
  assert.ok(peak <= config.assessment.gradeConcurrency, `peak ${peak}`);
  await assert.rejects(runGrading({ ActivityType: 'Assignment' }, {}), { status: 400 });
});

test('stub graders for Coding and SQL are registered and report 501 until M3-3', async () => {
  await assert.rejects(runGrading({ ActivityType: 'Coding' }, {}), { status: 501 });
  await assert.rejects(runGrading({ ActivityType: 'SQL' }, {}), { status: 501 });
});
