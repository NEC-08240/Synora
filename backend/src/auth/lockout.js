/**
 * Failed-sign-in tracking with three scopes: (ip, email) pairs, a per-email counter, and a per-IP counter.
 *
 * Tradeoff: the per-email scope lets an attacker deliberately lock a known victim out for LOCK_MS
 * (the "slow a known victim" attack). We accept that because it is short, never permanent, and the
 * alternative (no per-email scope) lets an attacker rotate IPs to brute-force one password indefinitely.
 * The per-IP scope can likewise lock out a shared classroom NAT after 30 failures across all accounts.
 *
 * shortcut: in-process memory only; move to a shared store before running multiple API instances.
 */
export const LOCK_MS = 15 * 60 * 1000;
/** Quiet period after the last failure (or the end of a lock) before counts start again from zero. */
const WINDOW_MS = LOCK_MS;
export const LOCKOUT_LIMITS = Object.freeze({ pair: 5, email: 20, ip: 30 });
const MAX_TRACKED = 10000;
const SWEEP_MS = 60 * 1000;

const failures = new Map(); // scopeKey -> { count, lastFailureAt, lockedUntil }

function scopes(ip, email) {
  return [
    [`pair:${ip}|${email}`, LOCKOUT_LIMITS.pair],
    [`email:${email}`, LOCKOUT_LIMITS.email],
    [`ip:${ip}`, LOCKOUT_LIMITS.ip],
  ];
}

export function isLockedOut(ip, email, now = Date.now()) {
  return scopes(ip, email).some(([key]) => (failures.get(key)?.lockedUntil ?? 0) > now);
}

/**
 * Counts a failure in every scope. A lock does not clear the count: after it expires the next failure
 * re-locks at once, unless the account has been quiet for WINDOW_MS past the end of the lock.
 */
export function recordFailure(ip, email, now = Date.now()) {
  for (const [key, limit] of scopes(ip, email)) {
    const prev = failures.get(key);
    const quietSince = Math.max(prev?.lastFailureAt ?? 0, prev?.lockedUntil ?? 0);
    const fresh = !prev || now - quietSince > WINDOW_MS;
    const count = (fresh ? 0 : prev.count) + 1;
    const lockedUntil = count >= limit ? now + LOCK_MS : (prev?.lockedUntil ?? 0);
    failures.delete(key); // re-insert so Map order tracks recency for eviction
    failures.set(key, { count, lastFailureAt: now, lockedUntil });
  }
  while (failures.size > MAX_TRACKED) failures.delete(failures.keys().next().value);
}

/** Successful sign-in clears this pair and this email; the per-IP counter is left alone. */
export function clearFailures(ip, email) {
  failures.delete(`pair:${ip}|${email}`);
  failures.delete(`email:${email}`);
}

/** Drops entries whose quiet period has ended; they carry no information any more. */
export function sweepLockouts(now = Date.now()) {
  for (const [key, entry] of failures) {
    if (now - Math.max(entry.lastFailureAt, entry.lockedUntil) > WINDOW_MS) failures.delete(key);
  }
}

export const trackedCount = () => failures.size;

setInterval(() => sweepLockouts(), SWEEP_MS).unref();
