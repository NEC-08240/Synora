import { queryOne } from '../db.js';
import { forbidden, notFound } from '../http.js';
import { assertAssignedToSubject } from '../routes/content.js';

/*
 * Access rules for assessment (spec section 3). This is the ONE place the authoring rule (decision D1) lives:
 * to change it, edit assertCanAuthorActivity only.
 *
 * Unlike the content helpers, Administrator is NOT let through by default: Admin is read-only here, so
 * authoring and grading reject Admin explicitly.
 */

/** Activity row plus the owning SubjectId and Topic status; 404 when it does not exist. */
export async function loadActivity(activityId) {
  const row = await queryOne(
    `SELECT a.*, t.SubjectId, t.Status AS TopicStatus
       FROM dbo.Activities a JOIN dbo.Topics t ON t.TopicId = a.TopicId
      WHERE a.ActivityId = @id`,
    { id: activityId },
  );
  if (!row) throw notFound('Activity not found');
  return row;
}

export function assertStudent(user) {
  if (user.RoleName !== 'Student') throw forbidden('Students only');
}

/**
 * Students: Activity Published AND its Topic Published AND the subject is allocated to their batch.
 * Faculty: assigned to the subject in at least one batch (sees drafts). Admin: any.
 * Same 403 wording for every denial so existence of unpublished content is not revealed beyond the 403.
 */
export async function assertCanReadActivity(user, activity) {
  if (user.RoleName !== 'Student') return assertAssignedToSubject(user, activity.SubjectId);
  if (activity.Status !== 'Published' || activity.TopicStatus !== 'Published') throw forbidden('Activity is not available');
  const row = await queryOne(
    `SELECT 1 AS ok FROM dbo.FacultyAssignments WHERE SubjectId = @subjectId AND BatchId = @batchId`,
    { subjectId: activity.SubjectId, batchId: user.BatchId ?? -1 },
  );
  if (!row) throw forbidden('Activity is not available');
}

/** D1 (decided): Faculty assigned to the subject in at least one batch. Administrator is read-only. */
export async function assertCanAuthorActivity(user, subjectId) {
  if (user.RoleName !== 'Faculty') throw forbidden('Only faculty can author activities');
  await assertAssignedToSubject(user, subjectId);
}

/** Grading scope is batch-level: faculty assigned to the STUDENT's batch for the activity's subject. */
export async function assertCanGradeSubmission(user, submission) {
  if (user.RoleName !== 'Faculty') throw forbidden('Only faculty can grade submissions');
  const row = await queryOne(
    `SELECT 1 AS ok
       FROM dbo.Users s
       JOIN dbo.Activities a ON a.ActivityId = @activityId
       JOIN dbo.Topics t ON t.TopicId = a.TopicId
       JOIN dbo.FacultyAssignments fa
         ON fa.BatchId = s.BatchId AND fa.SubjectId = t.SubjectId AND fa.FacultyId = @facultyId
      WHERE s.UserId = @studentId`,
    { activityId: submission.ActivityId, studentId: submission.StudentId, facultyId: user.UserId },
  );
  if (!row) throw forbidden('You are not assigned to this student for this subject');
}

/** Own submissions for students, batch faculty for faculty, any for Administrator (read-only). */
export async function assertCanReadSubmission(user, submission) {
  if (user.RoleName === 'Administrator') return;
  if (user.RoleName === 'Student') {
    if (submission.StudentId !== user.UserId) throw forbidden('Not your submission');
    return;
  }
  await assertCanGradeSubmission(user, submission);
}
