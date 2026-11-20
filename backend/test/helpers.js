/**
 * Integration test helpers. Tests run against the database named in .env.test
 * (SynoraV1_Test, created from database/schema.sql and seeded with `npm run seed:test`).
 */
import { randomBytes } from 'node:crypto';
import bcrypt from 'bcryptjs';
import { createApp } from '../src/app.js';
import { config } from '../src/config.js';
import { closePool, query, queryOne } from '../src/db.js';
import { attachAiRelay } from '../src/ai/relay.js';

// Per-process random password: no hardcoded credential in tests. startServer() sets the demo
// accounts to it, so test files must run one at a time (see `--test-concurrency=1` in package.json).
export const DEMO_PASSWORD = randomBytes(18).toString('base64url');
export const ACCOUNTS = {
  admin: 'admin@synora.local',
  faculty: 'faculty@synora.local',
  student: 'student@synora.local',
};

let server;
let baseUrl;

async function resetDemoPasswords() {
  const hash = await bcrypt.hash(DEMO_PASSWORD, config.bcryptRounds);
  await query('UPDATE dbo.Users SET PasswordHash = @hash WHERE Email IN (@admin, @faculty, @student)', {
    hash,
    admin: ACCOUNTS.admin,
    faculty: ACCOUNTS.faculty,
    student: ACCOUNTS.student,
  });
}

export async function startServer() {
  if (server) return baseUrl;
  await resetDemoPasswords();
  server = await new Promise((resolve) => {
    const s = createApp().listen(0, () => resolve(s));
  });
  attachAiRelay(server);
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  return baseUrl;
}

export async function stopServer() {
  if (server) await new Promise((resolve) => server.close(resolve));
  server = undefined;
  await closePool();
}

/** fetch wrapper: JSON body in, `{ status, body, cookie }` out. */
export async function api(method, path, { body, cookie } = {}) {
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { ...(body !== undefined && { 'Content-Type': 'application/json' }), ...(cookie && { Cookie: cookie }) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const setCookie = res.headers.get('set-cookie');
  return {
    status: res.status,
    body: text ? JSON.parse(text) : null,
    cookie: setCookie ? setCookie.split(';')[0] : undefined,
  };
}

export async function login(role) {
  const res = await api('POST', '/api/v1/auth/login', { body: { email: ACCOUNTS[role], password: DEMO_PASSWORD } });
  if (res.status !== 200) throw new Error(`login as ${role} failed: ${res.status} ${JSON.stringify(res.body)}`);
  return res.cookie;
}

/** Unique suffix so tests can be re-run against the same database. */
export const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/* ---------------- assessment fixtures (Activities under a throwaway Topic) ---------------- */

const fixtureTopicIds = [];

/** The seeded demo user as the `req.user` shape the access helpers take: { UserId, RoleName, BatchId }. */
export async function demoUser(role) {
  const row = await queryOne(
    `SELECT u.UserId, r.RoleName, u.BatchId FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId WHERE u.Email = @email`,
    { email: ACCOUNTS[role] },
  );
  return row;
}

/**
 * Inserts a Topic (unique title, high OrderIndex so it never collides with seed data) and one Activity under the
 * given seeded subject. Everything created here is removed by cleanupFixtures().
 */
export async function createActivityFixture({
  type = 'Quiz',
  status = 'Published',
  topicStatus = 'Published',
  subject = 'C Programming',
} = {}) {
  const faculty = await demoUser('faculty');
  const { SubjectId: subjectId } = await queryOne('SELECT SubjectId FROM dbo.Subjects WHERE Title = @subject', { subject });
  const topic = await queryOne(
    `INSERT dbo.Topics (SubjectId, Title, OrderIndex, Status, CreatedBy)
     OUTPUT INSERTED.TopicId
     VALUES (@subjectId, @title, @orderIndex, @status, @createdBy)`,
    { subjectId, title: `fx-${unique()}`, orderIndex: 1_000_000 + Math.floor(Math.random() * 1_000_000), status: topicStatus, createdBy: faculty.UserId },
  );
  fixtureTopicIds.push(topic.TopicId);
  const activity = await queryOne(
    `INSERT dbo.Activities (TopicId, Title, Instructions, ActivityType, IsGraded, MaxScore, Status, CreatedBy)
     OUTPUT INSERTED.ActivityId
     VALUES (@topicId, @title, N'fixture', @type, 1, 10, @status, @createdBy)`,
    { topicId: topic.TopicId, title: `fx-${unique()}`, type, status, createdBy: faculty.UserId },
  );
  return { subjectId, topicId: topic.TopicId, activityId: activity.ActivityId };
}

/** Deletes fixture rows in FK order (TestCaseResults/SubmissionAnswers are NO ACTION, so children go first). */
export async function cleanupFixtures() {
  if (!fixtureTopicIds.length) return;
  const ids = fixtureTopicIds.splice(0).join(',');
  const acts = `SELECT ActivityId FROM dbo.Activities WHERE TopicId IN (${ids})`;
  const subs = `SELECT SubmissionId FROM dbo.Submissions WHERE ActivityId IN (${acts})`;
  for (const sql of [
    `DELETE FROM dbo.TestCaseResults WHERE SubmissionId IN (${subs})`,
    `DELETE FROM dbo.SubmissionAnswers WHERE SubmissionId IN (${subs})`,
    `DELETE FROM dbo.Submissions WHERE ActivityId IN (${acts})`,
    `DELETE FROM dbo.PracticeDrafts WHERE ActivityId IN (${acts})`,
    `DELETE FROM dbo.LearningActivity WHERE ActivityId IN (${acts})`,
    `DELETE FROM dbo.Activities WHERE TopicId IN (${ids})`,
    `DELETE FROM dbo.Topics WHERE TopicId IN (${ids})`,
  ]) await query(sql);
}
