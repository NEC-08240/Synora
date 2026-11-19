import { HttpError, badRequest } from '../../http.js';

const MAX_SOURCE_CHARS = 64 * 1024;

/** Spec 6.1: CRLF -> LF, trailing whitespace per line, trailing blank lines dropped. */
export function normalizeOutput(text) {
  return String(text ?? '').replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/[ \t]+$/, '')).join('\n').replace(/\n+$/, '');
}

/**
 * Code grader: each hidden test case runs once with its stdin. Per-case TimeLimitMs is NOT enforced
 * (runCode has no per-call timeout; the runner's global limit applies). Hidden data stays in `results`
 * (internal/faculty); only passed/total/compileError/timedOut are student-safe.
 */
export async function grade(activity, payload, { runCode = async (r) => (await import('../../practice/code.js')).runCode(r) } = {}) {
  const source = payload?.source;
  if (typeof source !== 'string' || !source.trim()) throw badRequest('source is required');
  if (source.length > MAX_SOURCE_CHARS) throw badRequest('source is too large');
  const cases = [...(activity.testCases ?? [])].sort((a, b) => a.OrderIndex - b.OrderIndex);
  if (!['c', 'cpp'].includes(activity.language) || cases.length === 0) throw new HttpError(500, 'Activity is not gradable');

  const results = [];
  let timedOut = false;
  for (const tc of cases) {
    let run;
    try {
      run = await runCode({ language: activity.language, source, stdin: tc.InputData ?? '' });
    } catch (err) {
      if (err instanceof HttpError && err.status === 429) throw err;
      console.error('code grader runner failure:', err.message);
      throw new HttpError(503, 'Code runner unavailable');
    }
    if (run.exitCode == null && !run.timedOut && !run.compileError) throw new HttpError(503, 'Code runner returned no result');
    if (run.compileError) {
      return {
        score: 0, passed: 0, total: cases.length, compileError: true, timedOut: false,
        results: cases.map((c) => ({ testCaseId: c.TestCaseId, passed: false, actualOutput: '', executionTimeMs: 0 })),
      };
    }
    if (run.timedOut) timedOut = true;
    const passed = run.exitCode === 0 && !run.timedOut && normalizeOutput(run.stdout) === normalizeOutput(tc.ExpectedOutput);
    results.push({ testCaseId: tc.TestCaseId, passed, actualOutput: run.stdout ?? '', executionTimeMs: run.durationMs ?? 0 });
  }
  const passed = results.filter((r) => r.passed).length;
  const score = Math.round((Number(activity.MaxScore) * passed / cases.length) * 100) / 100;
  return { score, passed, total: cases.length, compileError: false, timedOut, results };
}
