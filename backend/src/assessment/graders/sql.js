import { HttpError, badRequest } from '../../http.js';

const MAX_SQL_CHARS = 64 * 1024;

function norm(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return `n:${v ? 1 : 0}`;
  if (typeof v === 'number') return `n:${Math.round(v * 1e6) / 1e6}`;
  if (v instanceof Date) return `s:${v.toISOString()}`;
  return `s:${v}`;
}

/** Spec 6.2. expected = parsed ExpectedResult; student = {columns, rows: objects}. */
export function resultsMatch(expected, student) {
  const cols = expected.columns;
  if (cols.length !== student.columns.length) return false;
  if (!cols.every((c, i) => String(c).toLowerCase() === String(student.columns[i]).toLowerCase())) return false;
  if (expected.rows.length !== student.rows.length) return false;
  const exp = expected.rows.map((r) => r.map(norm).join('\u0001'));
  // shortcut: rows are objects keyed by name, so duplicate result columns collapse; M3-1 rejects those at publish.
  const stu = student.rows.map((r) => student.columns.map((c) => norm(r[c])).join('\u0001'));
  if (!expected.orderMatters) { exp.sort(); stu.sort(); }
  return exp.every((r, i) => r === stu[i]);
}

function parseExpected(spec) {
  let e;
  try { e = JSON.parse(spec?.ExpectedResult); } catch { e = null; }
  if (!e || !Array.isArray(e.columns) || !Array.isArray(e.rows) || !e.rows.every(Array.isArray)) throw new HttpError(500, 'Activity is not gradable');
  return e;
}

/** SQL grader: all-or-nothing MaxScore; sandbox error or truncated result fails. */
export async function grade(activity, payload, { runSql = async (r) => (await import('../../practice/sql.js')).runSql(r) } = {}) {
  const sql = payload?.sql;
  if (typeof sql !== 'string' || !sql.trim()) throw badRequest('sql is required');
  if (sql.length > MAX_SQL_CHARS) throw badRequest('sql is too large');
  const expected = parseExpected(activity.sqlSpec);

  let out;
  try {
    out = await runSql({ sql, setupScript: activity.sqlSpec.SetupScript ?? '' });
  } catch (err) {
    if (err instanceof HttpError) throw err;
    console.error('sql grader sandbox failure:', err.message);
    throw new HttpError(503, 'SQL sandbox unavailable');
  }
  const passed = !out.error && !out.truncated && resultsMatch(expected, out);
  return { score: passed ? Number(activity.MaxScore) : 0, passed: passed ? 1 : 0, total: 1, results: [{ passed }] };
}
