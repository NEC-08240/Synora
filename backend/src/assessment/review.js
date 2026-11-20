import { Router } from 'express';
import { query, queryOne } from '../db.js';
import { HttpError, badRequest, forbidden } from '../http.js';
import { idParam } from '../validate.js';
import { assertCanGradeSubmission, assertCanReadSubmission, loadActivity } from './access.js';
import { resultFaculty, submissionFaculty } from './project.js';

/*
 * Faculty review (spec endpoints 15-17). Declares ONLY method+path pairs (no router.use): this router is mounted ahead of contentRouter on /api/v1.
 * Scope is batch-level (spec section 3): faculty see only students of batches they are assigned for the activity's subject; Admin reads, never grades.
 */
export const reviewRouter = Router();

const MAX_LIMIT = 100;
const MAX_FEEDBACK_CHARS = 8000;
const STATUSES = ['Submitted', 'Graded'];

const intQuery = (raw, name, { min, max, fallback }) => {
  if (raw === undefined) return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < min || n > max) throw badRequest(`${name} must be an integer between ${min} and ${max}`);
  return n;
};

const loadSubmission = async (id) => {
  const row = await queryOne('SELECT * FROM dbo.Submissions WHERE SubmissionId = @id', { id });
  if (!row) throw new HttpError(404, 'Submission not found');
  return row;
};

reviewRouter.get('/activities/:id/submissions', async (req, res) => {
  const { RoleName: role, UserId: userId } = req.user;
  if (role === 'Student') throw forbidden('Students cannot list submissions');
  const activity = await loadActivity(idParam(req.params.id));
  const { status, studentId } = req.query;
  if (status !== undefined && !STATUSES.includes(status)) throw badRequest(`status must be one of ${STATUSES.join(', ')}`);
  const limit = intQuery(req.query.limit, 'limit', { min: 1, max: MAX_LIMIT, fallback: 50 });
  const offset = intQuery(req.query.offset, 'offset', { min: 0, max: 1_000_000, fallback: 0 });
  const student = intQuery(studentId, 'studentId', { min: 1, max: 2_147_483_647, fallback: null });
  const rows = await query(
    `SELECT s.*
       FROM dbo.Submissions s
       JOIN dbo.Users u ON u.UserId = s.StudentId
      WHERE s.ActivityId = @activityId
        AND (@status IS NULL OR s.Status = @status)
        AND (@studentId IS NULL OR s.StudentId = @studentId)
        AND (@role = 'Administrator' OR EXISTS (
              SELECT 1 FROM dbo.FacultyAssignments fa
               WHERE fa.FacultyId = @facultyId AND fa.BatchId = u.BatchId AND fa.SubjectId = @subjectId))
      ORDER BY s.SubmittedAt DESC, s.SubmissionId DESC
     OFFSET @offset ROWS FETCH NEXT @limit ROWS ONLY`,
    { activityId: activity.ActivityId, status: status ?? null, studentId: student, role, facultyId: userId, subjectId: activity.SubjectId, offset, limit },
  );
  res.json(rows.map(submissionFaculty));
});

reviewRouter.patch('/submissions/:id/grade', async (req, res) => {
  const id = idParam(req.params.id);
  const submission = await loadSubmission(id);
  await assertCanGradeSubmission(req.user, submission);
  const { score, feedback } = req.body ?? {};
  const activity = await loadActivity(submission.ActivityId);
  if (typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > Number(activity.MaxScore)) {
    throw badRequest(`score must be a number between 0 and ${activity.MaxScore}`);
  }
  if (feedback != null && (typeof feedback !== 'string' || feedback.length > MAX_FEEDBACK_CHARS)) {
    throw badRequest(`feedback must be a string of at most ${MAX_FEEDBACK_CHARS} characters`);
  }
  const row = await queryOne(
    `UPDATE dbo.Submissions
        SET Status = 'Graded', Score = @score, Feedback = @feedback, GradedBy = @by, GradedAt = SYSUTCDATETIME()
     OUTPUT INSERTED.*
      WHERE SubmissionId = @id`,
    { id, score, feedback: feedback ?? null, by: req.user.UserId },
  );
  res.json(submissionFaculty(row));
});

reviewRouter.get('/submissions/:id/results', async (req, res) => {
  if (req.user.RoleName === 'Student') throw forbidden('Students cannot read per-case results');
  const submission = await loadSubmission(idParam(req.params.id));
  await assertCanReadSubmission(req.user, submission);
  const rows = await query(
    `SELECT r.TestCaseId, r.Passed, r.ActualOutput, r.ExecutionTimeMs
       FROM dbo.TestCaseResults r JOIN dbo.TestCases t ON t.TestCaseId = r.TestCaseId
      WHERE r.SubmissionId = @id ORDER BY t.OrderIndex`,
    { id: submission.SubmissionId },
  );
  res.json(rows.map(resultFaculty));
});
