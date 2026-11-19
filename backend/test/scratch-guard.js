/**
 * Tests write to the database named in .env.test, so refuse any name that is not clearly disposable.
 * One rule: a scratch database name starts with "SynoraT" (e.g. SynoraT004_App, SynoraT_CI).
 * Real databases (SynoraV1, SynoraV1_Test, SynoraV1_Sandbox) never match.
 */
const SCRATCH_NAME = /^SynoraT/i;

export function assertScratchDb(env) {
  for (const key of ['DB_NAME', 'SANDBOX_DB_NAME']) {
    const name = env[key];
    if (key === 'SANDBOX_DB_NAME' && !name) continue; // sandbox is optional
    if (!name || !SCRATCH_NAME.test(name)) {
      throw new Error(`Refusing to run tests: ${key}=${name ?? '(unset)'} is not a scratch database; names must start with "SynoraT"`);
    }
  }
}
