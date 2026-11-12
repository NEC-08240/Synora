import express from 'express';
import cookieParser from 'cookie-parser';
import { config } from './config.js';
import { HttpError } from './http.js';
import { isForeignKeyViolation, isUniqueViolation } from './db.js';
import { authRouter } from './auth/routes.js';
import { requireAuth, requireRole } from './auth/middleware.js';
import { usersRouter } from './routes/users.js';
import { batchesRouter } from './routes/batches.js';
import { assignmentsRouter } from './routes/assignments.js';
import { contentRouter } from './routes/content.js';
import { aiRouter } from './ai/sessions.js';
import { executeRouter } from './practice/routes.js';
import { rateLimit, userOrIpKey } from './rateLimit.js';

export function createApp() {
  const app = express();
  app.disable('x-powered-by');
  if (config.trustProxy !== undefined) app.set('trust proxy', config.trustProxy);
  const executeLimit = rateLimit({ windowMs: 60 * 1000, max: config.rateLimits.execute, keyFn: userOrIpKey });
  const aiSessionLimit = rateLimit({ windowMs: 60 * 1000, max: config.rateLimits.aiSessions, keyFn: userOrIpKey });
  const loginLimit = rateLimit({ windowMs: 60 * 1000, max: config.rateLimits.login, keyFn: (req) => `ip:${req.ip}` });
  app.use(express.json({ limit: '1mb' }));
  app.use(cookieParser());
  app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (origin && config.corsOrigins.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Access-Control-Allow-Credentials', 'true');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
      res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS');
      res.setHeader('Vary', 'Origin');
    }
    if (req.method === 'OPTIONS') return res.status(204).end();
    next();
  });

  app.get('/api/v1/health', (req, res) => res.json({ status: 'ok' }));
  app.post('/api/v1/auth/login', loginLimit); // per-IP, independent of the lockout tracker
  app.use('/api/v1/auth', authRouter);
  app.use('/api/v1/users', requireAuth, usersRouter);
  app.use('/api/v1/batches', requireAuth, batchesRouter);
  app.use('/api/v1/assignments', requireAuth, assignmentsRouter);
  app.use('/api/v1/ai', requireAuth, aiSessionLimit, aiRouter);
  app.use('/api/v1/execute', requireAuth, requireRole('Student', 'Faculty'), executeLimit, executeRouter);
  app.use('/api/v1', requireAuth, contentRouter);

  app.use((req, res) => res.status(404).json({ error: 'Route not found' }));

  // eslint-disable-next-line no-unused-vars
  app.use((err, req, res, next) => {
    if (err instanceof HttpError) {
      return res.status(err.status).json({ error: err.message, details: err.details });
    }
    if (err.type === 'entity.parse.failed') return res.status(400).json({ error: 'Malformed JSON body' });
    if (isUniqueViolation(err)) return res.status(409).json({ error: 'A record with the same unique value already exists' });
    if (isForeignKeyViolation(err)) return res.status(409).json({ error: 'Operation violates a reference to another record' });
    console.error(err);
    res.status(500).json({ error: 'Internal server error' });
  });

  return app;
}
