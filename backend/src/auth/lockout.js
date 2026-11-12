/**
 * Failed-sign-in tracking with three scopes: (ip, email) pairs, a per-email counter, and a per-IP counter.
 *
 * Tradeoff: the per-email scope lets an attacker deliberately lock a known victim out for LOCK_MS
 * (the "slow a known victim" attack). Each lock is short (LOCK_MS), but an attacker can renew it with one
 * failure per window, so a known victim can be kept out of sign-in for as long as the attacker keeps trying.
 * We accept that because the alternative (no per-email scope) lets an attacker rotate IPs to brute-force one
 * password indefinitely.
 * The per-IP scope can likewise lock out a shared classroom NAT after 30 failures across all accounts.
 *
 * shortcut: in-process memory only; move to a shared store before running multiple API instances.
 */
export const LOCK_MS = 15 * 60 * 1000;
/** Quiet period after the last failure (or the end of a lock) before counts start again from zero. */
const WINDOW_MS = LOCK_MS;
export const LOCKOUT_LIMITS = Object.freeze({ pair: 5, email: 20, ip: 30 });
export const MAX_TRACKED = 10000;
/** Locked entries are kept past MAX_TRACKED (so rotating IPs cannot evict a lock) up to this hard bound. */
const MAX_LOCKED_TRACKED = MAX_TRACKED * 2;
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
  if (failures.size > MAX_TRACKED) evict(now);
}

/**
 * Frees room without letting rotating-IP junk push out a victim's counters: drops oldest single-failure
 * unlocked entries first (what an attacker's spray creates), then oldest unlocked entries, and only past the
 * hard bound the oldest locked ones. Trims to 90% so the O(n) scan is amortised.
 */
function evict(now) {
  const target = Math.floor(MAX_TRACKED * 0.9);
  const passes = [(e) => e.lockedUntil <= now && e.count <= 1, (e) => e.lockedUntil <= now];
  for (const eligible of passes) {
    for (const [key, entry] of failures) {
      if (failures.size <= target) return;
      if (eligible(entry)) failures.delete(key);
    }
  }
  for (const key of failures.keys()) {
    if (failures.size <= MAX_LOCKED_TRACKED) return;
    failures.delete(key);
  }
}

/**
 * Atomically (no await) checks the lock and reserves this attempt as a failure in every scope. Callers MUST
 * call this before any async work, so N parallel guesses cannot all pass the lock check before the first
 * result is known. Returns false when locked. After a correct password call `refundAttempt`; otherwise the
 * reservation simply stands as the recorded failure.
 */
export function beginAttempt(ip, email, now = Date.now()) {
  if (isLockedOut(ip, email, now)) return false;
  recordFailure(ip, email, now);
  return true;
}

/** Undoes the per-IP part of a reservation after a correct password (pair/email are cleared separately). */
export function refundAttempt(ip) {
  const key = `ip:${ip}`;
  const entry = failures.get(key);
  if (!entry) return;
  const count = Math.max(0, entry.count - 1);
  failures.set(key, { ...entry, count, lockedUntil: count < LOCKOUT_LIMITS.ip ? 0 : entry.lockedUntil });
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
