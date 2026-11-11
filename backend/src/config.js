import process from 'node:process';

const required = ['DB_SERVER', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'JWT_SECRET'];
const missing = required.filter((k) => !process.env[k]);
if (missing.length) {
  throw new Error(`Missing required environment variables: ${missing.join(', ')} (see backend/.env.example)`);
}
if (process.env.JWT_SECRET.length < 32) {
  throw new Error('JWT_SECRET must be at least 32 characters');
}

export const config = Object.freeze({
  port: Number(process.env.PORT ?? 4000),
  isProduction: process.env.NODE_ENV === 'production',
  db: Object.freeze({
    server: process.env.DB_SERVER,
    port: Number(process.env.DB_PORT ?? 1433),
    database: process.env.DB_NAME,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
  }),
  jwtSecret: process.env.JWT_SECRET,
  jwtTtlSeconds: 8 * 60 * 60,
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
  }),
  corsOrigins: (process.env.CORS_ORIGINS ?? 'http://localhost:5173').split(',').map((s) => s.trim()),
});
