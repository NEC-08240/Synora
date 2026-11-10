import { Router } from 'express';
import bcrypt from 'bcryptjs';
import { queryOne } from '../db.js';
import { unauthorized } from '../http.js';
import { validate } from '../validate.js';
import { COOKIE_NAME, cookieOptions, requireAuth, signToken } from './middleware.js';

export const authRouter = Router();

export const publicUser = (u) => ({
  userId: u.UserId,
  name: u.Name,
  email: u.Email,
  role: u.RoleName,
  batchId: u.BatchId ?? null,
});

authRouter.post('/login', async (req, res) => {
  const { email, password } = validate(req.body, {
    email: { type: 'string', required: true, max: 255 },
    password: { type: 'string', required: true, max: 200 },
  });
  const user = await queryOne(
    `SELECT u.UserId, u.Name, u.Email, u.PasswordHash, u.Status, u.BatchId, r.RoleName
       FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.Email = @email`,
    { email: email.toLowerCase() },
  );
  // Same message for unknown email and wrong password so accounts cannot be enumerated.
  const ok = user && (await bcrypt.compare(password, user.PasswordHash));
  if (!ok) throw unauthorized('Invalid email or password');
  if (user.Status !== 'Active') throw unauthorized('Account is not active');
  res.cookie(COOKIE_NAME, signToken(user), cookieOptions);
  res.json({ user: publicUser(user) });
});

authRouter.post('/logout', (req, res) => {
  res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: undefined });
  res.status(204).end();
});

authRouter.get('/me', requireAuth, (req, res) => {
  res.json({ user: publicUser(req.user) });
});
