import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer, unique } from './helpers.js';
import { queryOne } from '../src/db.js';

let admin;
let faculty;
let student;
before(async () => {
  await startServer();
  [admin, faculty, student] = await Promise.all([login('admin'), login('faculty'), login('student')]);
});
after(stopServer);

test('student sees the subjects allocated to their batch, with published topics and lessons', async () => {
  const subjects = await api('GET', '/api/v1/subjects', { cookie: student });
  assert.equal(subjects.status, 200);
  assert.deepEqual(
    subjects.body.subjects.map((s) => s.title),
    ['C Programming', 'C++ Programming', 'DBMS/SQL'],
  );
  const topics = await api('GET', `/api/v1/subjects/${subjects.body.subjects[0].subjectId}/topics`, { cookie: student });
  assert.equal(topics.status, 200);
  assert.ok(topics.body.topics.length >= 3);
  assert.ok(topics.body.topics.every((t) => t.status === 'Published'));

  const lessons = await api('GET', `/api/v1/topics/${topics.body.topics[0].topicId}/lessons`, { cookie: student });
  assert.equal(lessons.status, 200);
  assert.ok(lessons.body.lessons.length >= 1);
});

test('viewing a lesson returns its content and records a LessonViewed event for students only', async () => {
  const me = (await api('GET', '/api/v1/auth/me', { cookie: student })).body.user;
  const countBefore = (await queryOne(
    `SELECT COUNT(*) AS n FROM dbo.LearningActivity WHERE StudentId = @id AND EventType = N'LessonViewed'`,
    { id: me.userId },
  )).n;

  const topics = (await api('GET', '/api/v1/subjects/1/topics', { cookie: student })).body.topics;
  const lessons = (await api('GET', `/api/v1/topics/${topics[0].topicId}/lessons`, { cookie: student })).body.lessons;
  const lesson = await api('GET', `/api/v1/lessons/${lessons[0].lessonId}`, { cookie: student });
  assert.equal(lesson.status, 200);
  assert.ok(lesson.body.lesson.contentBody.length > 0);
  assert.ok(Array.isArray(lesson.body.lesson.resources));

  await api('GET', `/api/v1/lessons/${lessons[0].lessonId}`, { cookie: faculty });

  const countAfter = (await queryOne(
    `SELECT COUNT(*) AS n FROM dbo.LearningActivity WHERE StudentId = @id AND EventType = N'LessonViewed'`,
    { id: me.userId },
  )).n;
  assert.equal(countAfter, countBefore + 1);
});

test('faculty authors a draft topic and lesson that students cannot see until published', async () => {
  const tag = unique();
  const subjectId = 3;
  const existing = (await api('GET', `/api/v1/subjects/${subjectId}/topics`, { cookie: faculty })).body.topics;
  const orderIndex = Math.max(0, ...existing.map((t) => t.orderIndex)) + 1;

  const topic = await api('POST', `/api/v1/subjects/${subjectId}/topics`, {
    cookie: faculty,
    body: { title: `Draft topic ${tag}`, orderIndex },
  });
  assert.equal(topic.status, 201);
  assert.equal(topic.body.topic.status, 'Draft');
  const topicId = topic.body.topic.topicId;

  const lesson = await api('POST', `/api/v1/topics/${topicId}/lessons`, {
    cookie: faculty,
    body: { title: `Lesson ${tag}`, contentBody: '## Body', objectives: 'Learn things', orderIndex: 1 },
  });
  assert.equal(lesson.status, 201);
  const lessonId = lesson.body.lesson.lessonId;

  const studentTopics = (await api('GET', `/api/v1/subjects/${subjectId}/topics`, { cookie: student })).body.topics;
  assert.ok(!studentTopics.some((t) => t.topicId === topicId), 'draft topic hidden from students');
  assert.equal((await api('GET', `/api/v1/lessons/${lessonId}`, { cookie: student })).status, 404);

  const publishTopic = await api('PATCH', `/api/v1/topics/${topicId}`, { cookie: faculty, body: { status: 'Published' } });
  assert.equal(publishTopic.status, 200);
  const publishLesson = await api('PATCH', `/api/v1/lessons/${lessonId}`, { cookie: faculty, body: { status: 'Published' } });
  assert.equal(publishLesson.status, 200);

  const resource = await api('POST', `/api/v1/lessons/${lessonId}/resources`, {
    cookie: faculty,
    body: { resourceType: 'Link', title: 'Docs', url: 'https://example.com/docs', orderIndex: 1 },
  });
  assert.equal(resource.status, 201);
  const badUrl = await api('POST', `/api/v1/lessons/${lessonId}/resources`, {
    cookie: faculty,
    body: { resourceType: 'Link', title: 'Docs', url: 'javascript:alert(1)', orderIndex: 2 },
  });
  assert.equal(badUrl.status, 400);

  const visible = await api('GET', `/api/v1/lessons/${lessonId}`, { cookie: student });
  assert.equal(visible.status, 200);
  assert.equal(visible.body.lesson.resources.length, 1);

  const dupOrder = await api('POST', `/api/v1/subjects/${subjectId}/topics`, {
    cookie: faculty,
    body: { title: 'Clash', orderIndex },
  });
  assert.equal(dupOrder.status, 409);
});

test('authoring authorisation: students are refused, faculty need an allocation', async () => {
  assert.equal(
    (await api('POST', '/api/v1/subjects/1/topics', { cookie: student, body: { title: 'x', orderIndex: 99 } })).status,
    403,
  );
  const tag = unique();
  const other = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'Unassigned Faculty', email: `uf-${tag}@synora.local`, password: 'Password123', role: 'Faculty' },
  });
  const otherLogin = await api('POST', '/api/v1/auth/login', { body: { email: other.body.user.email, password: 'Password123' } });
  const res = await api('POST', '/api/v1/subjects/1/topics', { cookie: otherLogin.cookie, body: { title: 'x', orderIndex: 99 } });
  assert.equal(res.status, 403);
  assert.deepEqual((await api('GET', '/api/v1/subjects', { cookie: otherLogin.cookie })).body.subjects, []);
});

test('a student with no batch sees no subjects and cannot read topics', async () => {
  const tag = unique();
  const email = `nobatch-${tag}@synora.local`;
  await api('POST', '/api/v1/users', { cookie: admin, body: { name: 'No Batch', email, password: 'Password123', role: 'Student' } });
  const cookie = (await api('POST', '/api/v1/auth/login', { body: { email, password: 'Password123' } })).cookie;
  assert.deepEqual((await api('GET', '/api/v1/subjects', { cookie })).body.subjects, []);
  assert.equal((await api('GET', '/api/v1/subjects/1/topics', { cookie })).status, 403);
});
