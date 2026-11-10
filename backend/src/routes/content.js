import { Router } from 'express';
import { query, queryOne } from '../db.js';
import { badRequest, forbidden, notFound } from '../http.js';
import { idParam, validate } from '../validate.js';
import { requireRole } from '../auth/middleware.js';

/**
 * Course content: Subjects -> Topics -> Lessons (+ LessonResources).
 * Students read Published content for subjects allocated to their batch (via FacultyAssignments)
 * and generate LessonViewed events. Faculty author topics/lessons for subjects they are assigned to.
 * Administrators can read everything.
 */
export const contentRouter = Router();

const CONTENT_STATUSES = ['Draft', 'Published', 'Archived'];

const topicDto = (t) => ({
  topicId: t.TopicId,
  subjectId: t.SubjectId,
  title: t.Title,
  orderIndex: t.OrderIndex,
  status: t.Status,
  lessonCount: t.LessonCount,
});
const lessonDto = (l) => ({
  lessonId: l.LessonId,
  topicId: l.TopicId,
  title: l.Title,
  objectives: l.Objectives,
  orderIndex: l.OrderIndex,
  status: l.Status,
});
const resourceDto = (r) => ({
  resourceId: r.ResourceId,
  resourceType: r.ResourceType,
  title: r.Title,
  url: r.Url,
  orderIndex: r.OrderIndex,
});

/* ------------------------------ access helpers ------------------------------ */

const isStudent = (user) => user.RoleName === 'Student';

/** Students only see Published rows; faculty/admin see every status. */
const statusFilter = (user, alias) => (isStudent(user) ? `AND ${alias}.Status = N'Published'` : '');

/** 403 unless the user may read this subject (students: allocated to their batch). */
async function assertCanReadSubject(user, subjectId) {
  if (!isStudent(user)) return;
  const row = await queryOne(
    `SELECT 1 AS ok FROM dbo.FacultyAssignments WHERE SubjectId = @subjectId AND BatchId = @batchId`,
    { subjectId, batchId: user.BatchId ?? -1 },
  );
  if (!row) throw forbidden('Subject is not allocated to your batch');
}

/** 403 unless faculty is assigned to the subject (any batch). Admin always passes. */
async function assertCanAuthorSubject(user, subjectId) {
  if (user.RoleName === 'Administrator') return;
  const row = await queryOne(
    `SELECT 1 AS ok FROM dbo.FacultyAssignments WHERE SubjectId = @subjectId AND FacultyId = @facultyId`,
    { subjectId, facultyId: user.UserId },
  );
  if (!row) throw forbidden('You are not assigned to this subject');
}

async function loadTopic(topicId) {
  const topic = await queryOne(`SELECT * FROM dbo.Topics WHERE TopicId = @id`, { id: topicId });
  if (!topic) throw notFound('Topic not found');
  return topic;
}

async function loadLesson(lessonId) {
  const lesson = await queryOne(
    `SELECT l.*, t.SubjectId FROM dbo.Lessons l JOIN dbo.Topics t ON t.TopicId = l.TopicId WHERE l.LessonId = @id`,
    { id: lessonId },
  );
  if (!lesson) throw notFound('Lesson not found');
  return lesson;
}

/* --------------------------------- subjects --------------------------------- */

contentRouter.get('/subjects', async (req, res) => {
  const scope = isStudent(req.user)
    ? `WHERE s.Status = N'Active' AND EXISTS (SELECT 1 FROM dbo.FacultyAssignments fa WHERE fa.SubjectId = s.SubjectId AND fa.BatchId = @batchId)`
    : req.user.RoleName === 'Faculty'
      ? `WHERE EXISTS (SELECT 1 FROM dbo.FacultyAssignments fa WHERE fa.SubjectId = s.SubjectId AND fa.FacultyId = @me)`
      : '';
  const rows = await query(
    `SELECT s.SubjectId, s.Title, s.Description, s.Status,
            (SELECT COUNT(*) FROM dbo.Topics t WHERE t.SubjectId = s.SubjectId ${statusFilter(req.user, 't')}) AS TopicCount
       FROM dbo.Subjects s ${scope} ORDER BY s.SubjectId`,
    { batchId: req.user.BatchId ?? -1, me: req.user.UserId },
  );
  res.json({
    subjects: rows.map((s) => ({
      subjectId: s.SubjectId,
      title: s.Title,
      description: s.Description,
      status: s.Status,
      topicCount: s.TopicCount,
    })),
  });
});

/* ---------------------------------- topics ---------------------------------- */

contentRouter.get('/subjects/:id/topics', async (req, res) => {
  const subjectId = idParam(req.params.id, 'subject id');
  await assertCanReadSubject(req.user, subjectId);
  const rows = await query(
    `SELECT t.*, (SELECT COUNT(*) FROM dbo.Lessons l WHERE l.TopicId = t.TopicId ${statusFilter(req.user, 'l')}) AS LessonCount
       FROM dbo.Topics t WHERE t.SubjectId = @subjectId ${statusFilter(req.user, 't')} ORDER BY t.OrderIndex`,
    { subjectId },
  );
  res.json({ topics: rows.map(topicDto) });
});

contentRouter.post('/subjects/:id/topics', requireRole('Faculty', 'Administrator'), async (req, res) => {
  const subjectId = idParam(req.params.id, 'subject id');
  await assertCanAuthorSubject(req.user, subjectId);
  const body = validate(req.body, {
    title: { type: 'string', required: true, max: 150 },
    orderIndex: { type: 'int', required: true, min: 1 },
    status: { type: 'enum', values: CONTENT_STATUSES },
  });
  const inserted = await queryOne(
    `INSERT INTO dbo.Topics (SubjectId, Title, OrderIndex, Status, CreatedBy) OUTPUT INSERTED.TopicId
     VALUES (@subjectId, @title, @orderIndex, @status, @by)`,
    { subjectId, title: body.title, orderIndex: body.orderIndex, status: body.status ?? 'Draft', by: req.user.UserId },
  );
  res.status(201).json({ topic: topicDto({ ...(await loadTopic(inserted.TopicId)), LessonCount: 0 }) });
});

contentRouter.patch('/topics/:id', requireRole('Faculty', 'Administrator'), async (req, res) => {
  const topicId = idParam(req.params.id, 'topic id');
  const topic = await loadTopic(topicId);
  await assertCanAuthorSubject(req.user, topic.SubjectId);
  const body = validate(req.body, {
    title: { type: 'string', max: 150 },
    orderIndex: { type: 'int', min: 1 },
    status: { type: 'enum', values: CONTENT_STATUSES },
  });
  await query(
    `UPDATE dbo.Topics SET Title = COALESCE(@title, Title), OrderIndex = COALESCE(@orderIndex, OrderIndex),
        Status = COALESCE(@status, Status) WHERE TopicId = @id`,
    { id: topicId, title: body.title ?? null, orderIndex: body.orderIndex ?? null, status: body.status ?? null },
  );
  res.json({ topic: topicDto(await loadTopic(topicId)) });
});

/* ---------------------------------- lessons --------------------------------- */

contentRouter.get('/topics/:id/lessons', async (req, res) => {
  const topicId = idParam(req.params.id, 'topic id');
  const topic = await loadTopic(topicId);
  await assertCanReadSubject(req.user, topic.SubjectId);
  if (isStudent(req.user) && topic.Status !== 'Published') throw notFound('Topic not found');
  const rows = await query(
    `SELECT LessonId, TopicId, Title, Objectives, OrderIndex, Status FROM dbo.Lessons
      WHERE TopicId = @topicId ${statusFilter(req.user, 'Lessons')} ORDER BY OrderIndex`,
    { topicId },
  );
  res.json({ lessons: rows.map(lessonDto) });
});

contentRouter.get('/lessons/:id', async (req, res) => {
  const lessonId = idParam(req.params.id, 'lesson id');
  const lesson = await loadLesson(lessonId);
  await assertCanReadSubject(req.user, lesson.SubjectId);
  if (isStudent(req.user) && lesson.Status !== 'Published') throw notFound('Lesson not found');
  const resources = await query(`SELECT * FROM dbo.LessonResources WHERE LessonId = @id ORDER BY OrderIndex`, { id: lessonId });
  if (isStudent(req.user)) {
    await query(`INSERT INTO dbo.LearningActivity (StudentId, EventType, LessonId) VALUES (@sid, N'LessonViewed', @lid)`, {
      sid: req.user.UserId,
      lid: lessonId,
    });
  }
  res.json({ lesson: { ...lessonDto(lesson), contentBody: lesson.ContentBody, resources: resources.map(resourceDto) } });
});

contentRouter.post('/topics/:id/lessons', requireRole('Faculty', 'Administrator'), async (req, res) => {
  const topicId = idParam(req.params.id, 'topic id');
  const topic = await loadTopic(topicId);
  await assertCanAuthorSubject(req.user, topic.SubjectId);
  const body = validate(req.body, {
    title: { type: 'string', required: true, max: 150 },
    contentBody: { type: 'string', max: 200000 },
    objectives: { type: 'string', max: 4000 },
    orderIndex: { type: 'int', required: true, min: 1 },
    status: { type: 'enum', values: CONTENT_STATUSES },
  });
  const inserted = await queryOne(
    `INSERT INTO dbo.Lessons (TopicId, Title, ContentBody, Objectives, OrderIndex, Status) OUTPUT INSERTED.LessonId
     VALUES (@topicId, @title, @contentBody, @objectives, @orderIndex, @status)`,
    {
      topicId,
      title: body.title,
      contentBody: body.contentBody ?? null,
      objectives: body.objectives ?? null,
      orderIndex: body.orderIndex,
      status: body.status ?? 'Draft',
    },
  );
  const lesson = await loadLesson(inserted.LessonId);
  res.status(201).json({ lesson: { ...lessonDto(lesson), contentBody: lesson.ContentBody, resources: [] } });
});

contentRouter.patch('/lessons/:id', requireRole('Faculty', 'Administrator'), async (req, res) => {
  const lessonId = idParam(req.params.id, 'lesson id');
  const existing = await loadLesson(lessonId);
  await assertCanAuthorSubject(req.user, existing.SubjectId);
  const body = validate(req.body, {
    title: { type: 'string', max: 150 },
    contentBody: { type: 'string', max: 200000 },
    objectives: { type: 'string', max: 4000 },
    orderIndex: { type: 'int', min: 1 },
    status: { type: 'enum', values: CONTENT_STATUSES },
  });
  await query(
    `UPDATE dbo.Lessons SET Title = COALESCE(@title, Title), ContentBody = COALESCE(@contentBody, ContentBody),
        Objectives = COALESCE(@objectives, Objectives), OrderIndex = COALESCE(@orderIndex, OrderIndex),
        Status = COALESCE(@status, Status) WHERE LessonId = @id`,
    {
      id: lessonId,
      title: body.title ?? null,
      contentBody: body.contentBody ?? null,
      objectives: body.objectives ?? null,
      orderIndex: body.orderIndex ?? null,
      status: body.status ?? null,
    },
  );
  const lesson = await loadLesson(lessonId);
  const resources = await query(`SELECT * FROM dbo.LessonResources WHERE LessonId = @id ORDER BY OrderIndex`, { id: lessonId });
  res.json({ lesson: { ...lessonDto(lesson), contentBody: lesson.ContentBody, resources: resources.map(resourceDto) } });
});

contentRouter.post('/lessons/:id/resources', requireRole('Faculty', 'Administrator'), async (req, res) => {
  const lessonId = idParam(req.params.id, 'lesson id');
  const lesson = await loadLesson(lessonId);
  await assertCanAuthorSubject(req.user, lesson.SubjectId);
  const body = validate(req.body, {
    resourceType: { type: 'enum', required: true, values: ['Image', 'Video', 'Link'] },
    title: { type: 'string', required: true, max: 150 },
    url: { type: 'string', required: true, max: 500 },
    orderIndex: { type: 'int', required: true, min: 1 },
  });
  if (!/^https?:\/\//i.test(body.url)) throw badRequest('Validation failed', { url: 'must start with http:// or https://' });
  const inserted = await queryOne(
    `INSERT INTO dbo.LessonResources (LessonId, ResourceType, Title, Url, OrderIndex) OUTPUT INSERTED.ResourceId
     VALUES (@lessonId, @type, @title, @url, @orderIndex)`,
    { lessonId, type: body.resourceType, title: body.title, url: body.url, orderIndex: body.orderIndex },
  );
  const row = await queryOne(`SELECT * FROM dbo.LessonResources WHERE ResourceId = @id`, { id: inserted.ResourceId });
  res.status(201).json({ resource: resourceDto(row) });
});
