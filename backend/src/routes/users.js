import { Router } from 'express';
import bcrypt from 'bcryptjs';
import { query, queryOne } from '../db.js';
import { badRequest, notFound } from '../http.js';
import { idParam, validate } from '../validate.js';
import { requireRole } from '../auth/middleware.js';
import { publicUser } from '../auth/routes.js';

export const usersRouter = Router();
usersRouter.use(requireRole('Administrator'));

const ROLES = ['Student', 'Faculty', 'Administrator'];
const STATUSES = ['Active', 'Suspended', 'Archived'];
const BCRYPT_ROUNDS = 10;
const MIN_PASSWORD = 8;

const SELECT_USER = `
  SELECT u.UserId, u.Name, u.Email, u.Status, u.BatchId, u.CreatedAt, r.RoleName
    FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId`;

const toDto = (u) => ({ ...publicUser(u), status: u.Status, createdAt: u.CreatedAt });

function checkPassword(password) {
  if (password !== undefined && password.length < MIN_PASSWORD) {
    throw badRequest('Validation failed', { password: `must be at least ${MIN_PASSWORD} characters` });
  }
}

usersRouter.get('/', async (req, res) => {
  const rows = await query(`${SELECT_USER} ORDER BY u.UserId`);
  res.json({ users: rows.map(toDto) });
});

usersRouter.post('/', async (req, res) => {
  const body = validate(req.body, {
    name: { type: 'string', required: true, max: 100 },
    email: { type: 'string', required: true, max: 255 },
    password: { type: 'string', required: true, max: 200 },
    role: { type: 'enum', required: true, values: ROLES },
    batchId: { type: 'int', min: 1 },
  });
  checkPassword(body.password);
  if (!body.email.includes('@')) throw badRequest('Validation failed', { email: 'must be an email address' });
  // Locked decision: only students belong to a batch (Users.BatchId nullable; enforced by backend).
  if (body.role !== 'Student' && body.batchId) {
    throw badRequest('Validation failed', { batchId: 'only students can belong to a batch' });
  }

  const hash = await bcrypt.hash(body.password, BCRYPT_ROUNDS);
  const inserted = await queryOne(
    `INSERT INTO dbo.Users (RoleId, BatchId, Name, Email, PasswordHash)
     OUTPUT INSERTED.UserId
     SELECT RoleId, @batchId, @name, @email, @hash FROM dbo.Roles WHERE RoleName = @role`,
    { batchId: body.batchId ?? null, name: body.name, email: body.email.toLowerCase(), hash, role: body.role },
  );
  const user = await queryOne(`${SELECT_USER} WHERE u.UserId = @id`, { id: inserted.UserId });
  res.status(201).json({ user: toDto(user) });
});

usersRouter.patch('/:id', async (req, res) => {
  const id = idParam(req.params.id);
  const body = validate(req.body, {
    name: { type: 'string', max: 100 },
    status: { type: 'enum', values: STATUSES },
    batchId: { type: 'int', min: 1 },
    password: { type: 'string', max: 200 },
  });
  checkPassword(body.password);
  const existing = await queryOne(`${SELECT_USER} WHERE u.UserId = @id`, { id });
  if (!existing) throw notFound('User not found');
  if (body.batchId && existing.RoleName !== 'Student') {
    throw badRequest('Validation failed', { batchId: 'only students can belong to a batch' });
  }
  const hash = body.password ? await bcrypt.hash(body.password, BCRYPT_ROUNDS) : null;
  const setBatch = Object.hasOwn(body, 'batchId') ? 1 : 0; // batchId: null clears the batch
  await query(
    `UPDATE dbo.Users SET
        Name = COALESCE(@name, Name),
        Status = COALESCE(@status, Status),
        BatchId = CASE WHEN @setBatch = 1 THEN @batchId ELSE BatchId END,
        PasswordHash = COALESCE(@hash, PasswordHash)
      WHERE UserId = @id`,
    { id, name: body.name ?? null, status: body.status ?? null, setBatch, batchId: body.batchId ?? null, hash },
  );
  const user = await queryOne(`${SELECT_USER} WHERE u.UserId = @id`, { id });
  res.json({ user: toDto(user) });
});
