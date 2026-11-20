import { Router } from 'express';
import { query, queryOne } from '../db.js';
import { notFound } from '../http.js';
import { idParam, validate } from '../validate.js';
import { requireRole } from '../auth/middleware.js';

export const batchesRouter = Router();

const SELECT_BATCH = `
  SELECT b.*, (SELECT COUNT(*) FROM dbo.Users u WHERE u.BatchId = b.BatchId) AS StudentCount
    FROM dbo.Batches b`;

const toDto = (b) => ({
  batchId: b.BatchId,
  name: b.Name,
  academicYear: b.AcademicYear,
  status: b.Status,
  createdBy: b.CreatedBy,
  createdAt: b.CreatedAt,
  studentCount: b.StudentCount,
});

batchesRouter.get('/', requireRole('Administrator', 'Faculty'), async (req, res) => {
  const rows = await query(`${SELECT_BATCH} ORDER BY b.AcademicYear DESC, b.Name`);
  res.json({ batches: rows.map(toDto) });
});

batchesRouter.post('/', requireRole('Administrator'), async (req, res) => {
  const body = validate(req.body, {
    name: { type: 'string', required: true, max: 100 },
    academicYear: { type: 'string', required: true, max: 20 },
  });
  const inserted = await queryOne(
    `INSERT INTO dbo.Batches (Name, AcademicYear, Status, CreatedBy) OUTPUT INSERTED.BatchId
     VALUES (@name, @year, N'Active', @by)`,
    { name: body.name, year: body.academicYear, by: req.user.UserId },
  );
  const batch = await queryOne(`${SELECT_BATCH} WHERE b.BatchId = @id`, { id: inserted.BatchId });
  res.status(201).json({ batch: toDto(batch) });
});

batchesRouter.patch('/:id', requireRole('Administrator'), async (req, res) => {
  const id = idParam(req.params.id);
  const body = validate(req.body, {
    name: { type: 'string', max: 100 },
    academicYear: { type: 'string', max: 20 },
    status: { type: 'enum', values: ['Active', 'Archived'] },
  });
  const rows = await query(
    `UPDATE dbo.Batches SET Name = COALESCE(@name, Name), AcademicYear = COALESCE(@year, AcademicYear),
        Status = COALESCE(@status, Status) OUTPUT INSERTED.BatchId WHERE BatchId = @id`,
    { id, name: body.name ?? null, year: body.academicYear ?? null, status: body.status ?? null },
  );
  if (!rows.length) throw notFound('Batch not found');
  const batch = await queryOne(`${SELECT_BATCH} WHERE b.BatchId = @id`, { id });
  res.json({ batch: toDto(batch) });
});
