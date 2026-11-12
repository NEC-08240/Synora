/** Why sandbox tests cannot run here. Under REQUIRE_SANDBOX_TESTS=1 any problem is a failure, not a skip. */
export function sandboxProblems({ labReason, adminAvailable }) {
  return [labReason, adminAvailable ? false : 'sqlcmd with Windows auth (sysadmin) unavailable'].filter(Boolean);
}

export const isRequired = (env = process.env) => ['1', 'true'].includes(String(env.REQUIRE_SANDBOX_TESTS ?? '').toLowerCase());
