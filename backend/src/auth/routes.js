import { Router } from 'express';
import bcrypt from 'bcryptjs';
import { queryOne } from '../db.js';
import { tooManyRequests, unauthorized } from '../http.js';
import { validate } from '../validate.js';
import { COOKIE_NAME, cookieOptions, requireAuth, signToken } from './middleware.js';

export const authRouter = Router();

const MAX_FAILED_LOGINS = 5;
const LOCKOUT_MS = 15 * 60 * 1000;
// shortcut: failed-login counters live in this process's memory, move to a shared store if the API runs on more than one instance.
const failedLogins = new Map(); // `${ip}|${email}` -> { count, lockedUntil }

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
  // Keyed by address + email so one client cannot lock another person out of their account.
  const attemptKey = `${req.ip}|${email.toLowerCase()}`;
  const attempts = failedLogins.get(attemptKey);
  if (attempts?.lockedUntil > Date.now()) throw tooManyRequests('Too many failed sign-in attempts. Try again later.');
  const user = await queryOne(
    `SELECT u.UserId, u.Name, u.Email, u.PasswordHash, u.Status, u.BatchId, r.RoleName
       FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.Email = @email`,
    { email: email.toLowerCase() },
  );
  // Same message for unknown email and wrong password so accounts cannot be enumerated.
  const ok = user && (await bcrypt.compare(password, user.PasswordHash));
  if (!ok) {
    const count = (attempts?.lockedUntil ? 0 : attempts?.count ?? 0) + 1;
    failedLogins.set(attemptKey, { count, lockedUntil: count >= MAX_FAILED_LOGINS ? Date.now() + LOCKOUT_MS : 0 });
    throw unauthorized('Invalid email or password');
  }
  failedLogins.delete(attemptKey);
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
