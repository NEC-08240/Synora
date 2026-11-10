import jwt from 'jsonwebtoken';
import { config } from '../config.js';
import { queryOne } from '../db.js';
import { forbidden, unauthorized } from '../http.js';

export const COOKIE_NAME = 'synora_token';

export const cookieOptions = Object.freeze({
  httpOnly: true,
  sameSite: 'lax',
  secure: config.isProduction,
  path: '/',
  maxAge: config.jwtTtlSeconds * 1000,
});

export function signToken(user) {
  return jwt.sign({ sub: String(user.UserId), role: user.RoleName }, config.jwtSecret, {
    expiresIn: config.jwtTtlSeconds,
  });
}

/** Verifies a JWT and re-reads the user; returns null if invalid or not Active. */
export async function userFromToken(token) {
  if (!token) return null;
  let payload;
  try {
    payload = jwt.verify(token, config.jwtSecret);
  } catch {
    return null;
  }
  // Re-read the user so suspension/archival takes effect immediately, not at token expiry.
  const user = await queryOne(
    `SELECT u.UserId, u.Name, u.Email, u.Status, u.BatchId, r.RoleName
       FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.UserId = @id`,
    { id: Number(payload.sub) },
  );
  return user && user.Status === 'Active' ? user : null;
}

/** Loads the current user from the cookie; 401 if absent, invalid, or not Active. */
export async function requireAuth(req, res, next) {
  const user = await userFromToken(req.cookies?.[COOKIE_NAME]);
  if (!user) return next(unauthorized('Session expired, invalid, or account not active'));
  req.user = user;
  next();
}

/** requireRole('Administrator', 'Faculty') -> 403 unless req.user has one of the roles. */
export function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.user) return next(unauthorized());
    if (!roles.includes(req.user.RoleName)) return next(forbidden(`Requires role: ${roles.join(' or ')}`));
    next();
  };
}
