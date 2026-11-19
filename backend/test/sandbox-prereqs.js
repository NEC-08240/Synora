/** Why sandbox tests cannot run here. Under REQUIRE_SANDBOX_TESTS=1 any problem is a failure, not a skip. */
export function sandboxProblems({ labReason, adminAvailable }) {
  return [labReason, adminAvailable ? false : 'sysadmin access unavailable (sqlcmd -E or SANDBOX_ADMIN_USER)'].filter(Boolean);
}

export const isRequired = (env = process.env) => ['1', 'true'].includes(String(env.REQUIRE_SANDBOX_TESTS ?? '').toLowerCase());
