import { tooManyRequests } from './http.js';

const SWEEP_INTERVAL_MS = 60 * 1000;

/**
 * Fixed-window in-memory limiter. `max` requests per `windowMs` per key; the N+1th gets 429 + Retry-After.
 * shortcut: state lives in this process only; move to a shared store before running multiple API instances.
 */
export function rateLimit({ windowMs, max, keyFn = (req) => req.ip, now = () => Date.now() }) {
  const windows = new Map(); // key -> { count, resetAt }

  function sweep() {
    const t = now();
    for (const [key, w] of windows) if (w.resetAt <= t) windows.delete(key);
  }
  // unref so the sweeper never keeps the process alive (tests and graceful shutdown).
  setInterval(sweep, SWEEP_INTERVAL_MS).unref();

  function middleware(req, res, next) {
    const t = now();
    const key = keyFn(req);
    let w = windows.get(key);
    if (!w || w.resetAt <= t) {
      w = { count: 0, resetAt: t + windowMs };
      windows.set(key, w);
    }
    w.count += 1;
    if (w.count > max) {
      res.setHeader('Retry-After', String(Math.max(1, Math.ceil((w.resetAt - t) / 1000))));
      return next(tooManyRequests('Too many requests, slow down and try again shortly'));
    }
    next();
  }

  middleware.sweep = sweep;
  middleware.size = () => windows.size;
  return middleware;
}

/** Key by the authenticated user when available (requireAuth ran first), else by client address. */
export const userOrIpKey = (req) => (req.user ? `user:${req.user.UserId}` : `ip:${req.ip}`);
