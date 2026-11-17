# T-001: release/v1 baseline investigation

Date: 2026-11-17. Branch `chore/t001-baseline`, created from `release/v1` at `22e9349`.
VERIFIED means the coordinator ran the command or read the file. UNVERIFIED means a subagent
reported it and it was not re-checked. No secrets are recorded here.

## 1. Subagent status

| Id | Task | Status | Notes |
|---|---|---|---|
| A1 | Branch map | Completed | Counts re-run by coordinator (VERIFIED) |
| A2 | Content audit | Completed | Had no shell. Commit list and stack checks redone by coordinator |
| A3 | Hygiene and secrets scan | Completed | Key points re-checked (VERIFIED); history contents not scanned |
| A4 | Rotation evidence | Completed | Docs re-read (VERIFIED) |
| A5 | Silent-failure scan | Completed | Two items grep-checked; the rest UNVERIFIED. `routes/*.js` and `auth/routes.js` bodies not audited |
| A6 | Baseline run on scratch DBs | Completed | Logs re-read by coordinator (VERIFIED) |

## 2. Branch map (VERIFIED: `git rev-list --left-right --count release/v1...X`; the first number is commits behind release/v1, the second is commits ahead)

| Branch | Head | Behind / ahead | Note |
|---|---|---|---|
| release/v1 | 22e9349 | - | PR #29 to main is open |
| trial/rc1 | 22e9349 | 0 / 0 | Same commit as release/v1 |
| origin/main | 07ec709 | 63 / 0 | Head is the merge of PR #28 (retire agent bridge) |
| main (local) | c8708b5 | 114 / 0 | Stale |
| feature/v1-core-foundation | 1af38dd | 41 / 0 | Fully contained in release/v1 |
| fix/post-release-security | a94fac4 | 0 / 2 | 34ef412 and a94fac4: `sandbox_setup.sql` guards and `backend/scripts/rotate-demo.js`. Not in release/v1 or PR #29 |
| ci/github-actions | dcb3e53 | 0 / 1 | Adds `.github/workflows/ci.yml`. Not in release/v1 or PR #29 |

The purpose of release/v1 is not documented in the repo. Its content is the V1 integration: 63 commits since origin/main (2026-10-05 to 2026-11-14).

## 3. release/v1 contents

- Commits fall into these themes: DB design, schema and ER/DFD docs; Express backend with JWT/RBAC; AI tutor relay; SQL sandbox and C/C++ proxy; login lockout and rate limit; React frontend; H1-H5 hardening merges; DB_NAME guards; release-readiness docs.
- Nothing contradicts the locked stack (VERIFIED by grep for `.ts`/`.tsx` files and the pg/mongodb/firebase/next packages). `@types/react` and `@types/react-dom` are devDependencies (`frontend/package.json:22-23`), which is harmless.
- Agent-bridge material exists only as archived docs in `docs/archive/agent-bridge/`. `relay.js` `bridge()` is the Gemini relay, not the agent bridge.
- `prototypes/` is tracked: static HTML plus PNGs, all under 1 MB. `scratch/` is an empty untracked directory.

## 4. Baseline results (run in this task on scratch DBs `SynoraT001_App` and `SynoraT001_Sandbox`; SQL Server 2022, `localhost\SQL2022`)

| Command | Result | Counts |
|---|---|---|
| `database/schema.sql` (`-v DB_NAME=SynoraT001_App`) | OK | rc=0 |
| `database/sandbox_setup.sql` on `SynoraT001_Sandbox` | OK | rc=0 |
| Backend `npm test` (after `seed:test`) | PASS | 123 tests, 123 pass, 0 fail, 0 skipped (`backend-test.log`) |
| Frontend `npm test` | PASS | 9/9 |
| Frontend `npm run lint` | PASS | 0 errors, 2 warnings (`src/auth.jsx:35,37`, react only-export-components) |
| Frontend `npm run build` | PASS | built in 437 ms |
| `database/validate_schema.sql` | PASS | 157 checks, 157 passed, 0 failed |
| Frontend `npm run smoke` (fresh seed, both servers running) | PASS | 12 checks passed, none failed |

- `test:ci` and `.env.ci` were not run. C runner (Piston) and Gemini were not configured, so the smoke test only confirms they report "not configured".
- The previous results (123 / 9 / 12 / 157 / 0 errors) are reproduced.
- Ordering caveat: after the backend tests the demo passwords no longer match `SEED_PASSWORD`, so smoke needs a fresh seed.
- Cleanup VERIFIED: no `SynoraT001%` database remains, and the other databases on the instance (including SynoraV1, SynoraV1_Test and SynoraV1_Sandbox) are untouched.

## 5. Table count: 20 or 21?

**20 tables.** `tables1.txt` (after `schema.sql`) and `tables2.txt` (end of run) are identical and list:
Activities, Batches, FacultyAssignments, LearningActivity, LessonResources, Lessons, PracticeDrafts, QuizOptions, QuizQuestions, Recommendations, Roles, SqlTaskSpecs, StudentProgress, Subjects, SubmissionAnswers, Submissions, TestCaseResults, TestCases, Topics, Users.
The "21" is a check count, not a table count. The validator's `Table` category has 21 checks: 20 per-table checks plus one `count = 20` check (`database/validate_schema.sql:177-185`). Its "unexpected table" check found nothing.

## 6. Rotation and migration evidence

- **Not proven.** The repo has no evidence that the sandbox migration or the demo-password rotation was executed.
- `docs/project/release-readiness-2026-11-14.md` section 9a says the real `SynoraV1_Sandbox` "still has its old permissions" and that passwords "have not been rotated". Section 10 lists the sandbox migration and both rotations as deferred (VERIFIED).
- The rotation tooling (`backend/scripts/rotate-demo.js`) exists only on `fix/post-release-security`. It needs `ROTATE_CONFIRM=1` and a password of at least 16 characters, and it leaves no audit record.
- I did not check the live DBs, because that was outside this task. A rotation done by hand cannot be seen from the repo.

## 7. Hygiene and silent-failure findings

Hygiene (A3, key points VERIFIED):
- No `.env` file is tracked. `backend/.env.ci` holds only `REQUIRE_SANDBOX_TESTS=1`.
- No hard-coded secrets were found. `config.js` and `seed.js` have no password fallbacks.
- `backend/.env.test` names the real DBs `SynoraV1_Test` and `SynoraV1_Sandbox`. Running tests locally therefore hits them unless overridden.
- Old demo and sandbox passwords are in git history (per section 9a). History contents were not scanned.
- Cosmetic: the header of `database/validate_schema.sql` shows a garbled path.

Silent failures (backend/src):
- HIGH (VERIFIED, grep): the main pool has no `pool.on('error')` (`backend/src/db.js`). There are no `unhandledRejection` or `uncaughtException` handlers; `server.js:14` handles signals only.
- HIGH (UNVERIFIED): the unguarded async upstream handler (`backend/src/ai/relay.js:58-59`) and unguarded `upstream.send` (`relay.js:49,110`).
- MEDIUM (UNVERIFIED): upstream error detail is dropped (`relay.js:75-82`); malformed frames are dropped silently (`relay.js:61-65`); the session is registered before its INSERT (`sessions.js:158-164`); runner failures are collapsed (`practice/code.js:35-46`); sandbox cleanup failures are logged and ignored (`practice/sql.js:44-56,350-379`).
- LOW: NaN fallbacks in config, a swallowed ECANCEL, and no error handling in shutdown.

## 8. CI status

`release/v1` has no workflow (VERIFIED: `.github` holds only CODEOWNERS and templates), and the readiness doc says no workflow runs `test:ci`. The workflow on `ci/github-actions` (dcb3e53) runs frontend lint/test/build and backend `seed:test` + `npm test` against a disposable SQL Server in Docker with schema validation. It skips the SQL sandbox suite. It was not run.

## 9. Risks

1. No CI protects PR #29. The CI branch and the post-release-security branch are not part of it.
2. Credentials and sandbox permissions on the live DBs are unchanged, and the old passwords are in git history.
3. The main DB pool has no error handler, so one stray pool error can crash the API.
4. `.env.test` points at real DB names, so a local test run can reset demo passwords.
5. Piston and Gemini paths were not exercised against real services.

## 10. Recommendation

**release/v1 is a safe base: YES, with fixes.** All verified checks pass (backend 123/123, frontend 9/9, validation 157/157, smoke 12/12, 20 tables, lint 0 errors), and scope matches the locked stack. Before treating it as a release:
- merge `fix/post-release-security` and `ci/github-actions`;
- add the pool-error and process-level handlers, and review `relay.js`;
- run the sandbox migration and the demo-password rotation (neither is proven to have happened);
- decide what to do about the old passwords in git history.
