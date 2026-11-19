import { Router } from 'express';
import sql from 'mssql';
import { getPool, query, queryOne } from '../db.js';
import { badRequest, conflict, HttpError, notFound } from '../http.js';
import { idParam, validate } from '../validate.js';
import { config } from '../config.js';
import { findForbiddenStatement, isSqlSandboxAvailable, runSql } from '../practice/sql.js';
import { assertCanAuthorActivity, assertCanReadActivity, loadActivity } from './access.js';
import { activityFaculty, activityStudent } from './project.js';

/*
 * Authoring (M3-1, endpoints 1-8). Declares ONLY method+path pairs (no router.use): this router is mounted ahead of
 * contentRouter on /api/v1. Authorization happens inside each handler via access.js (Admin gets 403 on writes).
 */
export const activitiesRouter = Router();

const TYPES = ['Practice', 'Quiz', 'Coding', 'SQL', 'Assignment'];
const MAX_SCORE_LIMIT = 999.99;
const isStudent = (user) => user.RoleName === 'Student';
const cents = (n) => Math.round(n * 100);

/* ------------------------------- helpers ------------------------------- */

async function loadTopic(topicId) {
  const topic = await queryOne('SELECT TopicId, SubjectId, Status FROM dbo.Topics WHERE TopicId = @topicId', { topicId });
  if (!topic) throw notFound('Topic not found');
  return topic;
}

/** A positive number with at most 2 decimals that fits DECIMAL(5,2). */
function checkScore(value, field) {
  const ok = typeof value === 'number' && value > 0 && value <= MAX_SCORE_LIMIT && cents(value) / 100 === value;
  if (!ok) throw badRequest('Validation failed', { [field]: 'must be a positive number with at most 2 decimals' });
  return value;
}

async function loadDetails(activity) {
  const id = activity.ActivityId;
  const questions = await query('SELECT * FROM dbo.QuizQuestions WHERE ActivityId = @id ORDER BY OrderIndex', { id });
  const options = await query(
    `SELECT o.* FROM dbo.QuizOptions o JOIN dbo.QuizQuestions q ON q.QuestionId = o.QuestionId
      WHERE q.ActivityId = @id ORDER BY o.OrderIndex`,
    { id },
  );
  for (const q of questions) q.options = options.filter((o) => o.QuestionId === q.QuestionId);
  const testCases = await query('SELECT * FROM dbo.TestCases WHERE ActivityId = @id ORDER BY OrderIndex', { id });
  const spec = await queryOne('SELECT * FROM dbo.SqlTaskSpecs WHERE ActivityId = @id', { id });
  const sqlSpec = spec && { ...spec, ExpectedResult: JSON.parse(spec.ExpectedResult) };
  return { questions, testCases, sqlSpec };
}

/** Fresh authoring view (hidden data included) of an activity by id. */
async function authoringView(activityId) {
  const activity = await loadActivity(activityId);
  return activityFaculty(activity, await loadDetails(activity));
}

const txQuery = async (tx, text, params = {}) => {
  const request = new sql.Request(tx);
  for (const [name, value] of Object.entries(params)) request.input(name, value);
  return (await request.query(text)).recordset ?? [];
};

/**
 * Runs fn(tx) in a transaction after locking the Activity row and re-checking the edit lock
 * (spec 7.5: not Draft or any submission => 409), so a concurrent publish/submit cannot slip in.
 */
async function withEditLock(activityId, fn) {
  const tx = new sql.Transaction(await getPool());
  await tx.begin();
  try {
    const [row] = await txQuery(tx, 'SELECT Status FROM dbo.Activities WITH (UPDLOCK, HOLDLOCK) WHERE ActivityId = @id', { id: activityId });
    if (!row) throw notFound('Activity not found');
    if (row.Status !== 'Draft') throw conflict('Activity is locked: only Draft activities can be edited');
    const [sub] = await txQuery(tx, 'SELECT TOP 1 1 AS x FROM dbo.Submissions WHERE ActivityId = @id', { id: activityId });
    if (sub) throw conflict('Activity is locked: it already has submissions');
    const result = await fn(tx);
    await tx.commit();
    return result;
  } catch (err) {
    await tx.rollback().catch(() => {});
    throw err;
  }
}

async function loadForAuthoring(req) {
  const activity = await loadActivity(idParam(req.params.id));
  await assertCanAuthorActivity(req.user, activity.SubjectId);
  return activity;
}

/* ------------------------------ 1. list / 2. create ------------------------------ */

activitiesRouter.get('/topics/:topicId/activities', async (req, res) => {
  const topic = await loadTopic(idParam(req.params.topicId, 'topicId'));
  await assertCanReadActivity(req.user, { Status: 'Published', TopicStatus: topic.Status, SubjectId: topic.SubjectId });
  const student = isStudent(req.user);
  const rows = await query(
    `SELECT * FROM dbo.Activities WHERE TopicId = @topicId ${student ? "AND Status = N'Published'" : ''} ORDER BY ActivityId`,
    { topicId: topic.TopicId },
  );
  const project = student ? activityStudent : activityFaculty;
  const activities = rows.map((r) => {
    const { questions, testCases, sqlSpec, ...summary } = project(r); // eslint-disable-line no-unused-vars
    return summary;
  });
  res.json({ activities });
});

activitiesRouter.post('/topics/:topicId/activities', async (req, res) => {
  const topic = await loadTopic(idParam(req.params.topicId, 'topicId'));
  await assertCanAuthorActivity(req.user, topic.SubjectId);
  const b = validate(req.body, {
    activityType: { type: 'enum', values: TYPES, required: true },
    title: { type: 'string', required: true, max: 150 },
    instructions: { type: 'string', required: true },
    isGraded: { type: 'bool', required: true },
    starterCode: { type: 'string' },
    hints: { type: 'string' },
    timeLimitMs: { type: 'int', min: 1 },
  });
  const practice = b.activityType === 'Practice';
  if (b.isGraded === practice) {
    throw badRequest('Validation failed', { isGraded: practice ? 'Practice activities are not graded' : 'must be true for graded types' });
  }
  let maxScore = null;
  if (b.isGraded) maxScore = checkScore(req.body.maxScore, 'maxScore');
  else if (req.body.maxScore != null) throw badRequest('Validation failed', { maxScore: 'not allowed for ungraded activities' });
  const timeLimitMs = b.timeLimitMs ?? (b.activityType === 'Coding' ? config.practice.runTimeoutMs : null);
  const created = await queryOne(
    `INSERT dbo.Activities (TopicId, Title, Instructions, ActivityType, IsGraded, MaxScore, StarterCode, Hints, TimeLimitMs, Status, CreatedBy)
     OUTPUT INSERTED.ActivityId
     VALUES (@topicId, @title, @instructions, @type, @isGraded, @maxScore, @starterCode, @hints, @timeLimitMs, N'Draft', @createdBy)`,
    {
      topicId: topic.TopicId, title: b.title, instructions: b.instructions, type: b.activityType, isGraded: b.isGraded, maxScore,
      starterCode: b.starterCode ?? null, hints: b.hints ?? null, timeLimitMs, createdBy: req.user.UserId,
    },
  );
  res.status(201).json({ activity: await authoringView(created.ActivityId) });
});

/* ------------------------------ 3. get / 4. patch ------------------------------ */

activitiesRouter.get('/activities/:id', async (req, res) => {
  const activity = await loadActivity(idParam(req.params.id));
  await assertCanReadActivity(req.user, activity);
  const details = await loadDetails(activity);
  res.json({ activity: isStudent(req.user) ? activityStudent(activity, details) : activityFaculty(activity, details) });
});

const PATCH_COLUMNS = { title: 'Title', instructions: 'Instructions', maxScore: 'MaxScore', starterCode: 'StarterCode', hints: 'Hints', timeLimitMs: 'TimeLimitMs' };
const CLEARABLE = ['starterCode', 'hints', 'timeLimitMs'];

activitiesRouter.patch('/activities/:id', async (req, res) => {
  const activity = await loadForAuthoring(req);
  const b = validate(req.body, {
    title: { type: 'string', max: 150 },
    instructions: { type: 'string' },
    starterCode: { type: 'string' },
    hints: { type: 'string' },
    timeLimitMs: { type: 'int', min: 1 },
  });
  if (req.body.maxScore != null) {
    if (!activity.IsGraded) throw badRequest('Validation failed', { maxScore: 'not allowed for ungraded activities' });
    b.maxScore = checkScore(req.body.maxScore, 'maxScore');
  }
  // null clears only the optional columns; title/instructions/maxScore cannot be cleared
  const keys = Object.keys(b).filter((k) => b[k] !== null || CLEARABLE.includes(k));
  if (!keys.length) throw badRequest('No editable fields supplied');
  await withEditLock(activity.ActivityId, (tx) => txQuery(
    tx,
    `UPDATE dbo.Activities SET ${keys.map((k) => `${PATCH_COLUMNS[k]} = @${k}`).join(', ')} WHERE ActivityId = @id`,
    { id: activity.ActivityId, ...Object.fromEntries(keys.map((k) => [k, b[k]])) },
  ));
  res.json({ activity: await authoringView(activity.ActivityId) });
});

/* ------------------------------ 5. status ------------------------------ */

const TRANSITIONS = { Draft: ['Published', 'Archived'], Published: ['Archived'], Archived: [] };

async function assertPublishable(activity) {
  const fail = (msg) => { throw badRequest(`Cannot publish: ${msg}`); };
  const details = await loadDetails(activity);
  switch (activity.ActivityType) {
    case 'Quiz': {
      if (!details.questions.length) fail('add at least one question');
      if (details.questions.reduce((s, q) => s + cents(q.Points), 0) !== cents(activity.MaxScore)) fail('maxScore must equal the sum of question points');
      break;
    }
    case 'Coding': {
      if (!details.testCases.length) fail('add at least one test case');
      const subject = await queryOne('SELECT Title FROM dbo.Subjects WHERE SubjectId = @id', { id: activity.SubjectId });
      if (!/^c(\+\+)?(\s|$)/i.test(subject?.Title ?? '')) fail('Coding activities are only supported for C and C++ subjects');
      break;
    }
    case 'SQL': {
      if (!details.sqlSpec) fail('set the SQL spec');
      if (!isSqlSandboxAvailable()) throw new HttpError(503, 'SQL sandbox unavailable; cannot validate the setup script');
      const out = await runSql({ sql: 'SELECT 1 AS ok', setupScript: details.sqlSpec.SetupScript });
      if (out.error) fail('the setup script does not run in the sandbox');
      break;
    }
    default:
  }
}

activitiesRouter.post('/activities/:id/status', async (req, res) => {
  const activity = await loadForAuthoring(req);
  const { status } = validate(req.body, { status: { type: 'enum', values: ['Published', 'Archived'], required: true } });
  if (!TRANSITIONS[activity.Status].includes(status)) throw conflict(`Cannot change status from ${activity.Status} to ${status}`);
  if (status === 'Published') await assertPublishable(activity);
  const updated = await queryOne(
    'UPDATE dbo.Activities SET Status = @status OUTPUT INSERTED.ActivityId WHERE ActivityId = @id AND Status = @from',
    { id: activity.ActivityId, status, from: activity.Status },
  );
  if (!updated) throw conflict('Activity status changed concurrently');
  res.json({ activity: await authoringView(activity.ActivityId) });
});

/* ------------------------------ 6-8. replace-style PUTs ------------------------------ */

const assertType = (activity, type) => {
  if (activity.ActivityType !== type) throw badRequest(`Only ${type} activities accept this`);
};
const nonEmptyArray = (value, name) => {
  if (!Array.isArray(value) || !value.length) throw badRequest('Validation failed', { [name]: 'must be a non-empty array' });
  return value;
};

function parseQuestions(body) {
  return nonEmptyArray(body?.questions, 'questions').map((raw, i) => {
    const q = validate(raw, { questionText: { type: 'string', required: true }, explanation: { type: 'string' } });
    const points = checkScore(raw.points, `questions[${i}].points`);
    const options = nonEmptyArray(raw.options, `questions[${i}].options`).map((o) => validate(o, {
      optionText: { type: 'string', required: true },
      isCorrect: { type: 'bool', required: true },
    }));
    if (options.length < 2 || options.filter((o) => o.isCorrect).length !== 1) {
      throw badRequest('Validation failed', { [`questions[${i}].options`]: 'need at least 2 options with exactly one correct' });
    }
    return { ...q, points, options };
  });
}

activitiesRouter.put('/activities/:id/questions', async (req, res) => {
  const activity = await loadForAuthoring(req);
  const questions = parseQuestions(req.body);
  assertType(activity, 'Quiz');
  await withEditLock(activity.ActivityId, async (tx) => {
    const id = activity.ActivityId;
    await txQuery(tx, 'DELETE FROM dbo.QuizQuestions WHERE ActivityId = @id', { id }); // options cascade
    for (const [i, q] of questions.entries()) {
      const [{ QuestionId }] = await txQuery(
        tx,
        `INSERT dbo.QuizQuestions (ActivityId, QuestionText, Explanation, Points, OrderIndex)
         OUTPUT INSERTED.QuestionId VALUES (@id, @text, @explanation, @points, @i)`,
        { id, text: q.questionText, explanation: q.explanation ?? null, points: q.points, i: i + 1 },
      );
      for (const [j, o] of q.options.entries()) {
        await txQuery(
          tx,
          'INSERT dbo.QuizOptions (QuestionId, OptionText, IsCorrect, OrderIndex) VALUES (@qid, @text, @correct, @j)',
          { qid: QuestionId, text: o.optionText, correct: o.isCorrect, j: j + 1 },
        );
      }
    }
    // Quiz MaxScore is derived, so the spec-5 invariant (MaxScore = sum of Points) holds by construction
    await txQuery(tx, 'UPDATE dbo.Activities SET MaxScore = @max WHERE ActivityId = @id', { id, max: questions.reduce((s, q) => s + cents(q.points), 0) / 100 });
  });
  res.json({ questions: (await authoringView(activity.ActivityId)).questions });
});

activitiesRouter.put('/activities/:id/test-cases', async (req, res) => {
  const activity = await loadForAuthoring(req);
  const cases = nonEmptyArray(req.body?.testCases, 'testCases')
    .map((raw) => validate(raw, { inputData: { type: 'string' }, expectedOutput: { type: 'string', required: true } }));
  assertType(activity, 'Coding');
  await withEditLock(activity.ActivityId, async (tx) => {
    const id = activity.ActivityId;
    await txQuery(tx, 'DELETE FROM dbo.TestCases WHERE ActivityId = @id', { id });
    for (const [i, c] of cases.entries()) {
      await txQuery(
        tx,
        'INSERT dbo.TestCases (ActivityId, InputData, ExpectedOutput, OrderIndex) VALUES (@id, @input, @output, @i)',
        { id, input: c.inputData ?? null, output: c.expectedOutput, i: i + 1 },
      );
    }
  });
  res.json({ testCases: (await authoringView(activity.ActivityId)).testCases });
});

function parseExpectedResult(er) {
  const bad = (msg) => badRequest('Validation failed', { expectedResult: msg });
  if (!er || typeof er !== 'object' || Array.isArray(er)) throw bad('must be an object');
  const { columns, rows, orderMatters } = er;
  if (!Array.isArray(columns) || !columns.length || columns.some((c) => typeof c !== 'string' || !c.trim())) throw bad('columns must be a non-empty array of names');
  if (new Set(columns.map((c) => c.toLowerCase())).size !== columns.length) throw bad('duplicate column names');
  if (!Array.isArray(rows) || rows.length > config.practice.maxRows) throw bad(`rows must be an array of at most ${config.practice.maxRows}`);
  const scalar = (v) => v === null || ['string', 'number', 'boolean'].includes(typeof v);
  if (rows.some((r) => !Array.isArray(r) || r.length !== columns.length || !r.every(scalar))) throw bad('every row must have one scalar per column');
  if (typeof orderMatters !== 'boolean') throw bad('orderMatters must be a boolean');
  return { columns, rows, orderMatters };
}

activitiesRouter.put('/activities/:id/sql-spec', async (req, res) => {
  const activity = await loadForAuthoring(req);
  const { setupScript } = validate(req.body, { setupScript: { type: 'string', required: true } });
  const expectedResult = parseExpectedResult(req.body.expectedResult);
  const refused = findForbiddenStatement(setupScript);
  if (refused) throw badRequest('Validation failed', { setupScript: `statement not allowed: ${refused}` });
  assertType(activity, 'SQL');
  await withEditLock(activity.ActivityId, async (tx) => {
    const id = activity.ActivityId;
    await txQuery(tx, 'DELETE FROM dbo.SqlTaskSpecs WHERE ActivityId = @id', { id });
    await txQuery(
      tx,
      'INSERT dbo.SqlTaskSpecs (ActivityId, SetupScript, ExpectedResult) VALUES (@id, @setup, @expected)',
      { id, setup: setupScript, expected: JSON.stringify(expectedResult) },
    );
  });
  res.json({ sqlSpec: (await authoringView(activity.ActivityId)).sqlSpec });
});
