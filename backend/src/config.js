import process from 'node:process';

const required = ['DB_SERVER', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'JWT_SECRET'];
const missing = required.filter((k) => !process.env[k]);
if (missing.length) {
  throw new Error(`Missing required environment variables: ${missing.join(', ')} (see backend/.env.example)`);
}

/** Throws unless the JWT secret is long enough and is not the .env.example placeholder. */
export function validateJwtSecret(secret) {
  if (secret.length < 32) throw new Error('JWT_SECRET must be at least 32 characters');
  if (/^change[_-]me/i.test(secret)) throw new Error('JWT_SECRET is still the placeholder from .env.example; generate a real secret');
  return secret;
}
validateJwtSecret(process.env.JWT_SECRET);

/** Boolean env var: unset/empty -> false, 'true'/'false' only; anything else throws. */
export function parseBooleanEnv(raw, name) {
  if (raw === undefined || raw === '' || raw === 'false') return false;
  if (raw === 'true') return true;
  throw new Error(`${name} must be "true" or "false"`);
}

/** Non-negative integer env var; unset/empty -> fallback; anything else throws at startup. */
export function parseIntEnv(raw, fallback, name) {
  if (raw === undefined || raw === '') return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0) throw new Error(`${name} must be a non-negative integer`);
  return n;
}

/** Integer env var that must be at least 1; unset/empty -> fallback. */
export function parsePositiveIntEnv(raw, fallback, name) {
  const n = parseIntEnv(raw, fallback, name);
  if (n < 1) throw new Error(`${name} must be at least 1`);
  return n;
}

/** DB_TRUST_SERVER_CERT only exists for a local self-signed SQL Server; never on in production. */
export function parseTrustServerCertificate(raw, isProduction) {
  const trust = parseBooleanEnv(raw, 'DB_TRUST_SERVER_CERT');
  if (trust && isProduction) throw new Error('DB_TRUST_SERVER_CERT must not be true when NODE_ENV=production');
  return trust;
}

/** TRUST_PROXY: X-Forwarded-For hop count; unset/empty means proxy headers are ignored. */
export function parseTrustProxy(raw) {
  if (raw === undefined || raw === '') return undefined;
  return parseIntEnv(raw, undefined, 'TRUST_PROXY');
}

/** Behind a reverse proxy every client shares its IP unless TRUST_PROXY says how many hops to trust, which breaks per-IP rate limits and lockout. */
export function requireTrustProxyInProduction(trustProxy, isProduction) {
  if (isProduction && trustProxy === undefined) {
    throw new Error('TRUST_PROXY must be set when NODE_ENV=production (number of proxy hops; 0 if there is no proxy)');
  }
  return trustProxy;
}

const isProduction = process.env.NODE_ENV === 'production';

// Values above 1 are unsafe: runs share the sbx schema, so one run's uncommitted DDL blocks another's leak
// sweep and catalog reads. Refuse at startup unless SANDBOX_ALLOW_PARALLEL=1 (then warn).
function sandboxConcurrency() {
  const n = parsePositiveIntEnv(process.env.SANDBOX_CONCURRENCY, 1, 'SANDBOX_CONCURRENCY');
  if (n > 1) {
    if (process.env.SANDBOX_ALLOW_PARALLEL !== '1') {
      throw new Error('SANDBOX_CONCURRENCY > 1 is unsafe (shared sbx schema); set SANDBOX_ALLOW_PARALLEL=1 to override');
    }
    console.warn('SANDBOX_CONCURRENCY > 1 with SANDBOX_ALLOW_PARALLEL=1: runs can block each other on sbx locks');
  }
  return n;
}

export const config = Object.freeze({
  port: Number(process.env.PORT ?? 4000),
  isProduction,
  // Secure cookie flag is always on in production; COOKIE_SECURE=true lets an HTTPS staging setup opt in.
  cookieSecure: isProduction || parseBooleanEnv(process.env.COOKIE_SECURE, 'COOKIE_SECURE'),
  trustProxy: requireTrustProxyInProduction(parseTrustProxy(process.env.TRUST_PROXY), isProduction),
  db: Object.freeze({
    server: process.env.DB_SERVER,
    port: Number(process.env.DB_PORT ?? 1433),
    database: process.env.DB_NAME,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    trustServerCertificate: parseTrustServerCertificate(process.env.DB_TRUST_SERVER_CERT, isProduction),
  }),
  jwtSecret: process.env.JWT_SECRET,
  jwtTtlSeconds: 8 * 60 * 60,
  bcryptRounds: 10, // mirrors the cost used for stored hashes in routes/users.js
  // Requests per minute per user (or per IP when anonymous).
  rateLimits: Object.freeze({
    execute: parseIntEnv(process.env.RATE_LIMIT_EXECUTE_PER_MIN, 30, 'RATE_LIMIT_EXECUTE_PER_MIN'),
    aiSessions: parseIntEnv(process.env.RATE_LIMIT_AI_PER_MIN, 10, 'RATE_LIMIT_AI_PER_MIN'),
    login: parseIntEnv(process.env.RATE_LIMIT_LOGIN_PER_MIN, 20, 'RATE_LIMIT_LOGIN_PER_MIN'),
  }),
  ai: Object.freeze({
    // Optional: without a key the AI tutor reports itself unavailable instead of failing silently.
    apiKey: process.env.GEMINI_API_KEY ?? '',
    model: process.env.GEMINI_MODEL ?? 'gemini-2.0-flash-live-001',
    sessionTtlSeconds: 5 * 60,
  }),
  practice: Object.freeze({
    // Piston-compatible executor (https://github.com/engineer-man/piston). Empty = code runner unavailable.
    executorUrl: (process.env.EXECUTOR_URL ?? '').replace(/\/$/, ''),
    runTimeoutMs: Number(process.env.EXECUTOR_RUN_TIMEOUT_MS ?? 3000),
    compileTimeoutMs: Number(process.env.EXECUTOR_COMPILE_TIMEOUT_MS ?? 10000),
    // Separate sandbox database + low-privilege login for student SQL. Never the app DB (handoff section 9.3).
    sandboxDb: process.env.SANDBOX_DB_NAME
      ? Object.freeze({
          server: process.env.SANDBOX_DB_SERVER ?? process.env.DB_SERVER,
          port: Number(process.env.SANDBOX_DB_PORT ?? process.env.DB_PORT ?? 1433),
          database: process.env.SANDBOX_DB_NAME,
          user: process.env.SANDBOX_DB_USER,
          password: process.env.SANDBOX_DB_PASSWORD,
        })
      : null,
    sqlTimeoutMs: 5000,
    maxRows: 200,
    // Students share the sbx schema, so sandbox runs are serial by default. Values above 1 are
    // unsupported: the leak detector would see another run's uncommitted objects.
    sandboxConcurrency: sandboxConcurrency(),
    // Requests waiting for a sandbox slot; beyond this they get 429.
    sandboxQueueMax: parseIntEnv(process.env.SANDBOX_QUEUE_MAX, 8, 'SANDBOX_QUEUE_MAX'),
  }),
  corsOrigins: (process.env.CORS_ORIGINS ?? 'http://localhost:5173').split(',').map((s) => s.trim()),
});
