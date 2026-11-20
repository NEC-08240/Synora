import { Router } from 'express';
import { query, queryOne } from '../db.js';
import { badRequest, notFound } from '../http.js';
import { idParam, validate } from '../validate.js';
import { requireRole } from '../auth/middleware.js';

/** FacultyAssignments: which faculty member teaches which subject to which batch (UNIQUE BatchId+SubjectId). */
export const assignmentsRouter = Router();

const SELECT = `
  SELECT fa.AssignmentId, fa.BatchId, b.Name AS BatchName, fa.SubjectId, s.Title AS SubjectTitle,
         fa.FacultyId, f.Name AS FacultyName, fa.AssignedBy, fa.AssignedAt
    FROM dbo.FacultyAssignments fa
    JOIN dbo.Batches b ON b.BatchId = fa.BatchId
    JOIN dbo.Subjects s ON s.SubjectId = fa.SubjectId
    JOIN dbo.Users f ON f.UserId = fa.FacultyId`;

const toDto = (a) => ({
  assignmentId: a.AssignmentId,
  batchId: a.BatchId,
  batchName: a.BatchName,
  subjectId: a.SubjectId,
  subjectTitle: a.SubjectTitle,
  facultyId: a.FacultyId,
  facultyName: a.FacultyName,
  assignedBy: a.AssignedBy,
  assignedAt: a.AssignedAt,
});

// Admin sees all; faculty sees only their own allocations.
assignmentsRouter.get('/', requireRole('Administrator', 'Faculty'), async (req, res) => {
  const mine = req.user.RoleName === 'Faculty';
  const rows = await query(`${SELECT} ${mine ? 'WHERE fa.FacultyId = @me' : ''} ORDER BY b.Name, s.Title`, {
    me: req.user.UserId,
  });
  res.json({ assignments: rows.map(toDto) });
});

assignmentsRouter.post('/', requireRole('Administrator'), async (req, res) => {
  const body = validate(req.body, {
    batchId: { type: 'int', required: true, min: 1 },
    subjectId: { type: 'int', required: true, min: 1 },
    facultyId: { type: 'int', required: true, min: 1 },
  });
  const faculty = await queryOne(
    `SELECT u.UserId FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.UserId = @id AND r.RoleName = N'Faculty' AND u.Status = N'Active'`,
    { id: body.facultyId },
  );
  if (!faculty) throw badRequest('Validation failed', { facultyId: 'must be an active Faculty user' });
  const inserted = await queryOne(
    `INSERT INTO dbo.FacultyAssignments (BatchId, SubjectId, FacultyId, AssignedBy) OUTPUT INSERTED.AssignmentId
     VALUES (@batchId, @subjectId, @facultyId, @by)`,
    { ...body, by: req.user.UserId },
  );
  const row = await queryOne(`${SELECT} WHERE fa.AssignmentId = @id`, { id: inserted.AssignmentId });
  res.status(201).json({ assignment: toDto(row) });
});

assignmentsRouter.delete('/:id', requireRole('Administrator'), async (req, res) => {
  const id = idParam(req.params.id);
  const rows = await query(`DELETE dbo.FacultyAssignments OUTPUT DELETED.AssignmentId WHERE AssignmentId = @id`, { id });
  if (!rows.length) throw notFound('Assignment not found');
  res.status(204).end();
});
