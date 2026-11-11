import { randomBytes } from 'node:crypto';
import { Router } from 'express';
import bcrypt from 'bcryptjs';
import { config } from '../config.js';
import { queryOne } from '../db.js';
import { tooManyRequests, unauthorized } from '../http.js';
import { validate } from '../validate.js';
import { clearFailures, isLockedOut, recordFailure } from './lockout.js';
import { COOKIE_NAME, cookieOptions, requireAuth, revokeToken, signToken } from './middleware.js';

export const authRouter = Router();

// Hash of a random secret at the real cost: an unknown email still pays one bcrypt compare,
// so response time does not reveal which emails exist.
const DUMMY_HASH = bcrypt.hashSync(randomBytes(16).toString('hex'), config.bcryptRounds);

/** Returns false for a null hash (unknown account) after running the same bcrypt work. */
export function verifyPassword(password, hash) {
  return bcrypt.compare(password, hash ?? DUMMY_HASH);
}

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
  const normalizedEmail = email.toLowerCase();
  if (isLockedOut(req.ip, normalizedEmail)) throw tooManyRequests('Too many failed sign-in attempts. Try again later.');
  const user = await queryOne(
    `SELECT u.UserId, u.Name, u.Email, u.PasswordHash, u.Status, u.BatchId, r.RoleName
       FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.Email = @email`,
    { email: normalizedEmail },
  );
  const passwordOk = await verifyPassword(password, user?.PasswordHash);
  // Same message for unknown email and wrong password so accounts cannot be enumerated.
  if (!user || !passwordOk) {
    recordFailure(req.ip, normalizedEmail);
    throw unauthorized('Invalid email or password');
  }
  clearFailures(req.ip, normalizedEmail);
  if (user.Status !== 'Active') throw unauthorized('Account is not active');
  res.cookie(COOKIE_NAME, signToken(user), cookieOptions);
  res.json({ user: publicUser(user) });
});

authRouter.post('/logout', (req, res) => {
  revokeToken(req.cookies?.[COOKIE_NAME]);
  res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: undefined });
  res.status(204).end();
});

authRouter.get('/me', requireAuth, (req, res) => {
  res.json({ user: publicUser(req.user) });
});
