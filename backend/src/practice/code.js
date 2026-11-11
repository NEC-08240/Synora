/**
 * C/C++ execution proxy. Student source is forwarded to an external Piston-compatible runner
 * (containerised gcc/g++ with its own CPU/memory/time limits); nothing is compiled or run here.
 */
import { config } from '../config.js';
import { HttpError } from '../http.js';

const LANGUAGES = { c: { language: 'c', file: 'main.c' }, cpp: { language: 'c++', file: 'main.cpp' } };
const MAX_OUTPUT = 64 * 1024;

export const isCodeRunnerAvailable = () => Boolean(config.practice.executorUrl);

/** @returns {Promise<{stdout,stderr,exitCode,timedOut,compileError,durationMs}>} */
export async function runCode({ language, source, stdin = '' }, { executorUrl = config.practice.executorUrl } = {}) {
  if (!executorUrl) throw new HttpError(503, 'The code runner is not configured on this server');
  const lang = LANGUAGES[language];
  const { runTimeoutMs, compileTimeoutMs } = config.practice;
  const started = Date.now();

  let res;
  try {
    res = await fetch(`${executorUrl}/api/v2/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        language: lang.language,
        version: '*',
        files: [{ name: lang.file, content: source }],
        stdin,
        run_timeout: runTimeoutMs,
        compile_timeout: compileTimeoutMs,
      }),
      signal: AbortSignal.timeout(runTimeoutMs + compileTimeoutMs + 5000),
    });
  } catch {
    throw new HttpError(503, 'The code runner is unreachable');
  }
  if (!res.ok) throw new HttpError(502, `The code runner rejected the request (${res.status})`);
  const data = await res.json();

  const compileError = Boolean(data.compile && data.compile.code !== 0);
  const stage = compileError ? data.compile : data.run ?? {};
  return {
    stdout: clip(stage.stdout ?? ''),
    stderr: clip(stage.stderr ?? ''),
    exitCode: stage.code ?? null,
    timedOut: stage.signal === 'SIGKILL' || stage.status === 'TO',
    compileError,
    durationMs: Date.now() - started,
  };
}

const clip = (s) => (s.length > MAX_OUTPUT ? `${s.slice(0, MAX_OUTPUT)}\n[output truncated]` : s);
