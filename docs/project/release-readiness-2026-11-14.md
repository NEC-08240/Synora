# Synora V1 Release Readiness — 14 November 2026

## 1. Scope

This report records the release-candidate evidence for `trial/rc1` at commit
`6b927a4` (the H1–H5 integration). It does not authorize a production
deployment, database migration, credential rotation, push, pull request, or
merge.

## 2. Git baseline

- Candidate branch: `trial/rc1`.
- Candidate commit: `6b927a4` — `merge: H5 per-run connection and validator fixes`.
- Relationship to the checked remote baseline: 55 commits ahead of `origin/main`.
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

On 14 November 2026, `cd backend && npm run test:ci` completed against the configured disposable test/lab environment. The CI configuration requires sandbox prerequisites and the sandbox suite refuses `SynoraV1`, `SynoraV1_Test`, and `SynoraV1_Sandbox` as test targets. No production database or real sandbox migration was run.

## 5. Frontend verification

On 14 November 2026:

| Check | Result |
|---|---|
| `npm test` | 7 passed, 0 failed |
| `npm run build` | Passed |
| `npm run lint` | 0 errors; 2 known Fast Refresh warnings in `src/auth.jsx` |

## 6. Database validation status

`database/validate_schema.sql` is the authoritative validation script. It checks the 20 expected tables, 35 foreign keys, keys, indexes, check constraints and reference data, then runs negative tests in a transaction that is rolled back. This release check did not run it against `SynoraV1` or `SynoraV1_Sandbox`; doing so must be explicitly approved and performed by the database owner.

## 7. Clean-environment status

The candidate has committed package lockfiles and `.env.example` templates. A fully fresh machine installation and browser smoke rerun were not performed in this release pass, because the existing browser smoke requires a local API, SQL Server test database and seeded credentials. That remains a release follow-up, not a passing claim.

## 8. External-service limitations

- Gemini Live remains unverified without `GEMINI_API_KEY`.
- C/C++ execution remains unverified without a Docker-hosted Piston-compatible runner and `EXECUTOR_URL`.
- The browser smoke was not rerun in this pass.

## 9. Accepted technical limitations

- Lockout and JWT revocation state are process-local and lost after restart.
- A user can be locked out after 20 bad guesses.
- A long SQL `WAITFOR` can occupy the single sandbox slot.
- `tempdb` is not capped by the application.
- Two faculty sharing a subject block each other's authoring.
- No GitHub Actions workflow runs `test:ci`.

## 10. Deferred work

DFD/ER redesign, sandbox migration, credential rotation, demo-password rotation, production deployment and live-service enablement are deliberately outside this release candidate.

## 11. Commit and PR procedure

1. Review this report and the candidate diff.
2. Commit only this documentation update on `trial/rc1`.
3. Push only after owner approval.
4. Open a PR from `trial/rc1` to the current `main` only after owner approval, attaching this report and the known limitations.
5. Do not merge until a reviewer accepts the limitations and any required fresh-environment/browser verification.
