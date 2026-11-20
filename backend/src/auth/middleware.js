import { createHash, randomUUID } from 'node:crypto';
import jwt from 'jsonwebtoken';
import { config } from '../config.js';
import { queryOne } from '../db.js';
import { forbidden, unauthorized } from '../http.js';

export const COOKIE_NAME = 'synora_token';
const JWT_ALGORITHM = 'HS256';
const JWT_ISSUER = 'synora';
const JWT_AUDIENCE = 'synora-web';

export const cookieOptions = Object.freeze({
  httpOnly: true,
  sameSite: 'lax',
  secure: config.cookieSecure,
  path: '/',
  maxAge: config.jwtTtlSeconds * 1000,
});

/**
 * Password-version claim: changes whenever the stored hash changes, so a password reset
 * invalidates every token issued before it. Derived from the hash, so no schema change is needed.
 */
export const passwordVersion = (passwordHash) => createHash('sha256').update(passwordHash).digest('hex').slice(0, 16);

// jti -> exp (ms). In-memory: revoked tokens are forgotten on server restart (accepted V1 limitation).
const revokedJtis = new Map();

function pruneRevoked(now = Date.now()) {
  for (const [jti, expiresAt] of revokedJtis) if (expiresAt <= now) revokedJtis.delete(jti);
}

export function signToken(user) {
  return jwt.sign(
    { role: user.RoleName, pv: passwordVersion(user.PasswordHash), jti: randomUUID() },
    config.jwtSecret,
    { subject: String(user.UserId), expiresIn: config.jwtTtlSeconds, algorithm: JWT_ALGORITHM, issuer: JWT_ISSUER, audience: JWT_AUDIENCE },
  );
}

/** Verifies signature, algorithm, issuer, audience and expiry; returns the claims or null. */
export function verifyPayload(token) {
  if (!token) return null;
  try {
    return jwt.verify(token, config.jwtSecret, { algorithms: [JWT_ALGORITHM], issuer: JWT_ISSUER, audience: JWT_AUDIENCE });
  } catch {
    return null;
  }
}

/** Server-side logout: the presented token stops working even though its signature is still valid. */
export function revokeToken(token) {
  const payload = verifyPayload(token);
  if (!payload?.jti) return;
  pruneRevoked();
  revokedJtis.set(payload.jti, payload.exp * 1000);
}

/** Verifies a JWT and re-reads the user; returns null if invalid, revoked, reset, or not Active. */
export async function userFromToken(token) {
  const payload = verifyPayload(token);
  if (!payload || revokedJtis.has(payload.jti)) return null;
  // Re-read the user so suspension, archival and password resets take effect immediately.
  const row = await queryOne(
    `SELECT u.UserId, u.Name, u.Email, u.Status, u.BatchId, u.PasswordHash, r.RoleName
       FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId = u.RoleId
      WHERE u.UserId = @id`,
    { id: Number(payload.sub) },
  );
  if (!row || row.Status !== 'Active' || payload.pv !== passwordVersion(row.PasswordHash)) return null;
  const { PasswordHash, ...user } = row;
  return user;
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
