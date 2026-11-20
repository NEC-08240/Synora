import { Router } from 'express';
import sql from 'mssql';
import { getPool, isUniqueViolation, query, queryOne } from '../db.js';
import { HttpError, badRequest, conflict } from '../http.js';
import { idParam, validate } from '../validate.js';
import { assertCanReadActivity, assertCanReadSubmission, assertStudent, loadActivity } from './access.js';
import { loadGradable, runGrading } from './grader.js';
import { resultStudent, submissionFaculty, submissionStudent } from './project.js';

/*
 * Student work and submit (spec endpoints 9-14). Router declares ONLY method+path pairs (no router.use): it is mounted ahead of contentRouter.
 * Grading runs first, read-only and under the grading semaphore; only then one short transaction writes the attempt (spec section 7).
 */
export const submissionsRouter = Router();

const MAX_DRAFT_CHARS = 64 * 1024;
const MAX_SUBMISSION_CHARS = 1024 * 1024;
const TAB_SWITCH_WINDOW_SECONDS = 5;
const DRAFT_TYPES = ['Coding', 'SQL', 'Assignment', 'Practice'];
const GRADED_TYPES = ['Quiz', 'Coding', 'SQL']; // D6 option 1: Practice is not graded; Assignment waits for faculty
const SUBMIT_FIELD = { Coding: 'source', SQL: 'sql', Assignment: 'content' };

const SUBMISSION_SELECT = `SELECT s.*,
       (SELECT COUNT(*) FROM dbo.TestCaseResults r WHERE r.SubmissionId = s.SubmissionId) AS total,
       (SELECT COUNT(*) FROM dbo.TestCaseResults r WHERE r.SubmissionId = s.SubmissionId AND r.Passed = 1) AS passed
  FROM dbo.Submissions s`;

/** Load the activity and check the student may read it (published activity + topic, subject allocated to their batch). */
async function studentActivity(req) {
  assertStudent(req.user);
  const activity = await loadActivity(idParam(req.params.id));
  await assertCanReadActivity(req.user, activity);
  return activity;
}

const studentRow = (row) => submissionStudent(row.total > 0 ? row : { ...row, total: undefined });

submissionsRouter.get('/activities/:id/draft', async (req, res) => {
  const activity = await studentActivity(req);
  const row = await queryOne('SELECT Content FROM dbo.PracticeDrafts WHERE StudentId = @s AND ActivityId = @a', {
    s: req.user.UserId,
    a: activity.ActivityId,
  });
  res.json({ content: row?.Content ?? null });
});

submissionsRouter.put('/activities/:id/draft', async (req, res) => {
  const activity = await studentActivity(req);
  if (!DRAFT_TYPES.includes(activity.ActivityType)) throw badRequest('Drafts are not supported for this activity type');
  const { content } = validate(req.body, { content: { type: 'string', required: true, max: MAX_DRAFT_CHARS } });
  await query(
    `MERGE dbo.PracticeDrafts WITH (HOLDLOCK) AS d
       USING (SELECT @s AS StudentId, @a AS ActivityId) AS src ON d.StudentId = src.StudentId AND d.ActivityId = src.ActivityId
       WHEN MATCHED THEN UPDATE SET Content = @c, UpdatedAt = SYSUTCDATETIME()
       WHEN NOT MATCHED THEN INSERT (StudentId, ActivityId, Content) VALUES (@s, @a, @c);`,
    { s: req.user.UserId, a: activity.ActivityId, c: content },
  );
  res.json({ saved: true });
});

/** Returns { payload, answers } where answers is the validated quiz answer list (or null). */
async function parseSubmission(activity, body) {
  const type = activity.ActivityType;
  if (type === 'Quiz') {
    if (!body || !Array.isArray(body.answers)) throw badRequest('answers must be an array');
    const rows = await query(
      `SELECT q.QuestionId, o.OptionId FROM dbo.QuizQuestions q LEFT JOIN dbo.QuizOptions o ON o.QuestionId = q.QuestionId WHERE q.ActivityId = @a`,
      { a: activity.ActivityId },
    );
    const questions = new Map();
    for (const r of rows) {
      if (!questions.has(r.QuestionId)) questions.set(r.QuestionId, new Set());
      if (r.OptionId !== null) questions.get(r.QuestionId).add(r.OptionId);
    }
    const chosen = new Map();
    for (const a of body.answers) {
      if (!Number.isInteger(a?.questionId) || !Number.isInteger(a?.optionId)) throw badRequest('Each answer needs integer questionId and optionId');
      if (!questions.get(a.questionId)?.has(a.optionId)) throw badRequest('Answer does not match a question option');
      if (chosen.has(a.questionId)) throw badRequest('Each question may be answered once');
      chosen.set(a.questionId, a.optionId);
    }
    if (questions.size === 0 || chosen.size !== questions.size) throw badRequest('Every question must be answered');
    const answers = [...chosen].map(([questionId, optionId]) => ({ questionId, optionId }));
    return { payload: { answers }, answers };
  }
  const field = SUBMIT_FIELD[type];
  if (!field) throw badRequest('This activity is not graded');
  const value = validate(body, { [field]: { type: 'string', required: true, max: MAX_SUBMISSION_CHARS } })[field];
  return { payload: { [field]: value }, answers: null };
}

/** Grader failures never write anything: 429/503 pass through, anything else becomes a generic 503 (no detail leaks). */
async function gradeOrFail(activity, payload) {
  let out;
  try {
    out = await runGrading(await loadGradable(activity), payload);
  } catch (err) {
    console.error('Grading failed:', err?.message);
    throw err instanceof HttpError ? err : new HttpError(503, 'Grading is temporarily unavailable');
  }
  const raw = Number(out?.score);
  if (!Number.isFinite(raw)) {
    console.error('Grading failed: non-numeric score');
    throw new HttpError(503, 'Grading is temporarily unavailable');
  }
  const score = Math.round(Math.min(Math.max(raw, 0), Number(activity.MaxScore)) * 100) / 100;
  return { ...out, score };
}

const DEADLOCK = 1205;
const APPLOCK_TIMEOUT_MS = 10000;
const MAX_DEADLOCK_RETRIES = 2;

/** Retries only a deadlock victim (SQL error 1205); the applock below makes that a second line of defence. */
async function writeAttempt(req, activity, content, graded, answers) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await writeAttemptOnce(req, activity, content, graded, answers);
    } catch (err) {
      if (err?.number !== DEADLOCK || attempt >= MAX_DEADLOCK_RETRIES) throw err;
      await new Promise((r) => setTimeout(r, 20 + Math.random() * 60));
    }
  }
}

async function writeAttemptOnce(req, activity, content, graded, answers) {
  const tx = new sql.Transaction(await getPool());
  await tx.begin();
  try {
    const run = (text, params) => {
      const r = new sql.Request(tx);
      for (const [k, v] of Object.entries(params)) r.input(k, v);
      return r.query(text);
    };
    const params = { s: req.user.UserId, a: activity.ActivityId };
    // Serialise allocation per (student, activity): the range lock alone let concurrent submits deadlock (1205) and surface as 409.
    const lock = new sql.Request(tx);
    lock.input('res', sql.NVarChar(255), `submit:${params.s}:${params.a}`);
    lock.input('t', sql.Int, APPLOCK_TIMEOUT_MS);
    lock.output('rc', sql.Int);
    const lockRc = (await lock.query("EXEC @rc = sp_getapplock @Resource = @res, @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = @t")).output.rc;
    if (lockRc < 0) throw conflict('Another attempt is in progress, please retry');
    const max = (await run('SELECT MAX(AttemptNo) AS m FROM dbo.Submissions WITH (UPDLOCK, HOLDLOCK) WHERE StudentId = @s AND ActivityId = @a', params)).recordset[0].m;
    const status = graded ? 'Graded' : 'Submitted';
    const ins = await run(
      `INSERT dbo.Submissions (StudentId, ActivityId, AttemptNo, SubmittedContent, Status, Score, GradedBy, GradedAt)
       OUTPUT INSERTED.SubmissionId
       VALUES (@s, @a, @n, @c, @st, @sc, NULL, ${graded ? 'SYSUTCDATETIME()' : 'NULL'})`,
      { ...params, n: (max ?? 0) + 1, c: content, st: status, sc: graded ? graded.score : null },
    );
    const submissionId = ins.recordset[0].SubmissionId;
    for (const r of graded?.results ?? []) {
      if (r.testCaseId == null) continue; // only Coding results map to a TestCases row; quiz/SQL keep counts only
      await run('INSERT dbo.TestCaseResults (SubmissionId, TestCaseId, Passed, ActualOutput, ExecutionTimeMs) VALUES (@id, @t, @p, @o, @ms)', {
        id: submissionId, t: r.testCaseId, p: Boolean(r.passed), o: r.actualOutput ?? null, ms: r.executionTimeMs ?? null,
      });
    }
    for (const a of answers ?? []) {
      await run('INSERT dbo.SubmissionAnswers (SubmissionId, QuestionId, OptionId) VALUES (@id, @q, @o)', { id: submissionId, q: a.questionId, o: a.optionId });
    }
    await run("INSERT dbo.LearningActivity (StudentId, EventType, ActivityId) VALUES (@s, N'ActivitySubmitted', @a)", params);
    await tx.commit();
    return submissionId;
  } catch (err) {
    await tx.rollback().catch(() => {});
    if (isUniqueViolation(err) || err?.number === DEADLOCK) throw conflict('Another attempt was recorded at the same time, please retry');
    throw err;
  }
}

submissionsRouter.post('/activities/:id/submissions', async (req, res) => {
  const activity = await studentActivity(req);
  const { payload, answers } = await parseSubmission(activity, req.body);
  const graded = GRADED_TYPES.includes(activity.ActivityType) ? await gradeOrFail(activity, payload) : null;
  const content = answers ? JSON.stringify(answers) : Object.values(payload)[0];
  const submissionId = await writeAttempt(req, activity, content, graded, answers);
  const row = await queryOne(`${SUBMISSION_SELECT} WHERE s.SubmissionId = @id`, { id: submissionId });
  const body = studentRow(row);
  if (graded && graded.total > 0) Object.assign(body, resultStudent({ passed: graded.passed, total: graded.total, compileError: graded.compileError, timedOut: graded.timedOut }));
  res.status(201).json(body);
});

submissionsRouter.get('/activities/:id/submissions/mine', async (req, res) => {
  const activity = await studentActivity(req);
  const rows = await query(`${SUBMISSION_SELECT} WHERE s.StudentId = @s AND s.ActivityId = @a ORDER BY s.AttemptNo`, {
    s: req.user.UserId,
    a: activity.ActivityId,
  });
  res.json(rows.map(studentRow));
});

submissionsRouter.get('/submissions/:id', async (req, res) => {
  const row = await queryOne(`${SUBMISSION_SELECT} WHERE s.SubmissionId = @id`, { id: idParam(req.params.id) });
  if (!row) throw new HttpError(404, 'Submission not found');
  try {
    await assertCanReadSubmission(req.user, row);
  } catch (err) {
    // students must not be able to tell "not yours" from "does not exist"
    if (req.user.RoleName === 'Student' && err.status === 403) throw new HttpError(404, 'Submission not found');
    throw err;
  }
  res.json(req.user.RoleName === 'Student' ? studentRow(row) : submissionFaculty(row));
});

submissionsRouter.post('/activities/:id/events', async (req, res) => {
  const activity = await studentActivity(req);
  validate(req.body, { eventType: { type: 'enum', required: true, values: ['TabSwitch'] } });
  const params = { s: req.user.UserId, a: activity.ActivityId, w: -TAB_SWITCH_WINDOW_SECONDS };
  // shortcut: check-then-insert is not atomic, so two simultaneous requests can both land; harmless for an analytics counter.
  const recent = await queryOne(
    `SELECT 1 AS hit FROM dbo.LearningActivity WHERE StudentId = @s AND ActivityId = @a AND EventType = N'TabSwitch' AND OccurredAt > DATEADD(SECOND, @w, SYSUTCDATETIME())`,
    params,
  );
  if (recent) return res.status(204).end();
  await query("INSERT dbo.LearningActivity (StudentId, EventType, ActivityId) VALUES (@s, N'TabSwitch', @a)", { s: params.s, a: params.a });
  res.status(201).json({ recorded: true });
});
