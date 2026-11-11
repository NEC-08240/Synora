import { Router } from 'express';
import { validate } from '../validate.js';
import { isCodeRunnerAvailable, runCode } from './code.js';
import { isSqlSandboxAvailable, runSql } from './sql.js';

export const executeRouter = Router();

executeRouter.get('/status', (req, res) => {
  res.json({ code: isCodeRunnerAvailable(), sql: isSqlSandboxAvailable() });
});

executeRouter.post('/code', async (req, res, next) => {
  try {
    const body = validate(req.body, {
      language: { type: 'enum', values: ['c', 'cpp'], required: true },
      source: { type: 'string', max: 64 * 1024, required: true },
      stdin: { type: 'string', max: 16 * 1024 },
    });
    res.json(await runCode(body));
  } catch (err) {
    next(err);
  }
});

executeRouter.post('/sql', async (req, res, next) => {
  try {
    const body = validate(req.body, {
      sql: { type: 'string', max: 16 * 1024, required: true },
      setupScript: { type: 'string', max: 64 * 1024 },
    });
    res.json(await runSql(body));
  } catch (err) {
    next(err);
  }
});
