# Merge notes (fix/h5-followup)

- `git show fix/h3-creds:backend/.env.example` line 31 says "database/sandbox_setup.sql line 10 hardcodes it (no sqlcmd variable)".
  That is stale once H2 is merged: setup takes `-v SANDBOX_DB=.. SANDBOX_LOGIN=.. SANDBOX_PASSWORD=..`. When merging, replace
  that comment with: `# Must equal the SANDBOX_PASSWORD passed to sandbox_setup.sql via sqlcmd -v.`
- The H3 `sandbox_setup.sql` default (`synora_sandbox` / a literal password) must not come back in the merge; keep the H2/H5 variable form.
- Setup now refuses a database that has `dbo` user objects and denies `VIEW ANY DATABASE`. Existing sandbox databases that
  hold `dbo` objects must be emptied or recreated before re-running setup.
- Run the reset (`database/sandbox_reset.sql`) from a scheduler nightly; see docs/technical/practice-execution.md.
