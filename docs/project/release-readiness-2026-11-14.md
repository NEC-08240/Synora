# Synora V1 Release Readiness — 14 November 2026

## 1. Scope

This report records the release-candidate evidence for `trial/rc1` at code commit
`e6ebde3` (H1–H5 integration plus database-script hardening; later commits on the branch are documentation only). It does not authorize a production
deployment, database migration, credential rotation, push, pull request, or
merge.

## 2. Git baseline

- Candidate branch: `trial/rc1`.
- Verified code commit: `e6ebde3` — `fix: harden DB_NAME guard ...`; H1–H5 integration was `6b927a4`.
- Relationship to `origin/main`: ahead by the H1–H5 history plus the commits listed in the release PR; `origin/main` has not moved.
- All H1–H5 worktrees were clean at inspection. The candidate worktree was also clean before this documentation update.

## 3. Release-file classification

| Classification | Files | Decision |
|---|---|---|
| Application and automated tests | `backend/**`, `frontend/**` | Include: reviewed V1 implementation and regression coverage. |
| Database implementation and checks | `database/schema.sql`, `database/sandbox_setup.sql`, `database/sandbox_reset.sql`, `database/validate_schema.sql` | Include: SQL Server design, least-privilege sandbox setup, reset procedure, and read-only/rolled-back validation. |
| Operational and technical documentation | `README.md`, `backend/README.md`, `docs/technical/**`, `docs/project/**`, `docs/database/**` | Include: corrected runbook, environment guidance, known limitations, and release evidence. |
| Existing academic diagrams and evidence | `docs/DFD/**`, `docs/dfd.*`, `docs/er-*`, `docs/academic/**`, `docs/tools/**` | Include as already committed evidence only. No DFD or ER redesign is part of this release candidate. |
| Prototype material | `prototypes/scr-03-interactive-learning/index.html` | Include: reviewed prototype update already in the candidate history. |
| Protected local deliverables | root `CLAUDE_HANDOFF.md`, root `Synora_DFD.docx` | Exclude: untracked files on `feature/v1-core-foundation`; preserved untouched and not staged. |
| Environment, credentials and generated dependencies | `.env`, `.env.test`, `node_modules/**`, `frontend/dist/**` | Exclude: local/runtime artifacts. `.env.example` and lockfiles are included intentionally. |

## 4. Backend verification

All results below are from a **fresh clone of `e6ebde3`** (`npm ci`, new disposable databases `CleanEnv_App` / `CleanEnv_Sbx` with dedicated logins, all dropped afterwards), run on 14 November 2026. `SynoraV1`, `SynoraV1_Test` and `SynoraV1_Sandbox` were not used.

`npm run test:ci` (`REQUIRE_SANDBOX_TESTS=1`): **123 passed, 0 failed, 0 skipped**, including the SQL sandbox suite against the disposable sandbox.

## 5. Frontend verification

| Check | Result |
|---|---|
| `npm test` | 7 passed, 0 failed, 0 skipped |
| `npm run build` | Passed |
| `npm run lint` | 0 errors; 2 known Fast Refresh warnings in `src/auth.jsx` |
| Browser smoke (`npm run smoke`, headless Chrome, real API + Vite + SQL Server) | 11/11 steps passed, exit 0 |

Smoke steps: anonymous redirect to login; wrong password rejected; student login and learning hub (SCR-02); lesson opens workspace (SCR-03); Theory/Objectives/Resources tabs; SQL runs in sandbox and result renders; C runner reports not configured; AI tutor reports not configured; student blocked from faculty area; faculty lands on `/manage` and is blocked from student area; no uncaught page errors. The C runner and AI tutor steps verify the *not configured* state only. The smoke test must run before the backend tests, which overwrite demo-user passwords (see `backend/README.md`).

## 6. Database validation

`database/validate_schema.sql` against the fresh database: **157/157 checks passed** (20 tables, 35 foreign keys of which 7 cascade, keys, indexes, check constraints, reference data, 15 rolled-back negative tests). `schema.sql` was run twice and is idempotent. Both scripts now require an explicit `-v DB_NAME=<db>` (no default), reject names with characters other than letters, digits and `_` and any `*_Sandbox` name, halt later batches in plain SSMS, and the validator exits non-zero on failure. An independent Opus review of the first version found these gaps (SSMS without SQLCMD mode, validator exit code, `]` injection, case-sensitive collation, a control-character typo); all were fixed and re-tested. Not guarded: running against `SynoraV1` itself is allowed (additive and idempotent) and remains the documented example. The real `SynoraV1` and `SynoraV1_Sandbox` were not validated or migrated.

## 7. Clean-environment status

Verified from a fresh clone using only the documented steps: install, schema, validation, sandbox setup, application login, `.env.test`, seed, API and frontend start, role-based navigation (smoke). Documented prerequisites: SQL Server with TCP/1433 and mixed mode, `sqlcmd` with Windows authentication (sysadmin) for the sandbox setup and sandbox tests, Node 24, Chrome or Edge for the smoke test.

## 8. External-service limitations

- Gemini Live (planned integration) remains unverified without `GEMINI_API_KEY`.
- C/C++ execution (planned integration) remains unverified without a Docker-hosted Piston-compatible runner and `EXECUTOR_URL`.

## 9. Accepted technical limitations

- Lockout and JWT revocation state are process-local and lost after restart.
- A user can be locked out after 20 bad guesses.
- A long SQL `WAITFOR` can occupy the single sandbox slot.
- `tempdb` is not capped by the application.
- Two faculty sharing a subject block each other's authoring.
- No GitHub Actions workflow runs `test:ci`.

## 9a. Security review status

Opus reviewed the H2 sandbox validator, the H5 follow-ups and the database-target safety changes by reading code and diffs; their findings were fixed with regression tests. This is reasoned review, not penetration testing. The sandbox setup (`database/sandbox_setup.sql`) has been tested only on disposable databases; the real `SynoraV1_Sandbox` still has its old permissions until the owner approves the migration. Demo/sandbox passwords from earlier commits are in local git history and have not been rotated.

## 10. Deferred work

Remaining academic deliverables: DFD finalisation and ER diagram verification against the 20-entity model (existing diagrams preserved, not redesigned here); synopsis PDF/PPTX still reference PostgreSQL and need a manual correction to SQL Server; unimplemented screens SCR-04 to SCR-07 (prototypes live in PR #7, not implemented). Also deferred: DFD/ER redesign, sandbox migration, credential rotation, demo-password rotation, production deployment and live-service enablement are deliberately outside this release candidate.

## 11. Commit and PR procedure

1. Review this report and the candidate diff.
2. Commit only this documentation update on `trial/rc1`.
3. Push only after owner approval.
4. Open a PR from `trial/rc1` to the current `main` only after owner approval, attaching this report and the known limitations.
5. Do not merge until a reviewer accepts the limitations and any required fresh-environment/browser verification.
