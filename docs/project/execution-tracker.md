# Synora V1 — Execution Tracker

Target: **Mid-Term Progress Review, November 2026**. Source schedule: synopsis §8.1 Gantt (Iterative & Incremental SDLC).
Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED (code + tests written) · VERIFIED (tests run and passing, manually checked).

Branch: `feature/v1-core-foundation` (from `docs/canonical-dfd` + merged `origin/main`).

## Phase summary

| # | Gantt phase | Scheduled | Status | Notes |
|---|-------------|-----------|--------|-------|
| 1 | Requirement Analysis & SRS | Jul–Aug 2026 | VERIFIED | Synopsis, scope, V1 exclusions exist. |
| 2 | System & Database Design | Aug–Sep 2026 | IN PROGRESS | DB design, ER, DFD, schema.sql done. Missing: REST API contract, WebSocket protocol spec (this branch adds them). Synopsis says PostgreSQL; superseded by locked SQL Server decision. |
| 3 | Core Foundation & RBAC | Sep–Oct 2026 | IN PROGRESS | No application code existed before 10 Nov 2026. |
| 4 | Learning & Practical Workspaces | Oct–Dec 2026 | NOT STARTED | November portion: lesson delivery, AI session/WebSocket, C/C++ proxy, SQL sandbox. |
| — | Mid-Term Guide Review | Nov 2026 | NOT STARTED | Demo + acceptance report. |
| 5 | Assessment, Telemetry & Recommendations | Dec 2026–Jan 2027 | NOT STARTED | Out of scope for this run. Schema already covers it. |
| 6–7 | Integration, Hardening, Final | Jan–Mar 2027 | NOT STARTED | Out of scope. |

## Task detail

| Task | Period | Status | Files | Tests | Deps / blockers |
|------|--------|--------|-------|-------|-----------------|
| 2.1 REST API contract | Aug–Sep | NOT STARTED | docs/technical/api-spec.md | n/a | — |
| 2.2 WebSocket / AI protocol spec | Aug–Sep | NOT STARTED | docs/technical/ai-session-protocol.md | n/a | — |
| 3.1 Backend scaffold (Express, config, mssql pool, error handling) | Sep–Oct | NOT STARTED | backend/ | backend tests | node 24, SQL Server local |
| 3.2 Authentication (login, JWT HTTP-only cookie, logout, /me) | Sep–Oct | NOT STARTED | backend/src/auth | auth.test.js | 3.1 |
| 3.3 RBAC middleware (requireRole) | Sep–Oct | NOT STARTED | backend/src/middleware | rbac.test.js | 3.2 |
| 3.4 User management (admin CRUD, status) | Sep–Oct | NOT STARTED | backend/src/routes/users.js | users.test.js | 3.3 |
| 3.5 Batches + FacultyAssignments (subject/batch allocation) | Sep–Oct | NOT STARTED | backend/src/routes/{batches,assignments}.js | tests | 3.3 |
| 3.6 Seed data (roles, subjects, topics, demo users) | Sep–Oct | NOT STARTED | database/seed.sql | validate_schema.sql | schema.sql |
| 3.7 Frontend scaffold (Vite, React, Tailwind tokens, router, auth context) | Sep–Oct | IMPLEMENTED | frontend/ (vite.config.js, src/api.js, src/auth.jsx, src/App.jsx, src/index.css) | frontend/test/api.test.js 3 pass; oxlint clean; vite build ok; login + subjects via dev proxy (curl) | — |
| 3.8 SCR-01 Auth & Gateway (real login) | Sep–Oct | IMPLEMENTED | frontend/src/pages/Login.jsx | builds; login API verified via dev proxy; not yet clicked through in a browser | 3.2, 3.7 |
| 4.1 Lessons/Topics API (faculty CRUD, student read, LessonViewed event) | Oct–Nov | NOT STARTED | backend/src/routes/{subjects,lessons}.js | tests | 3.3 |
| 4.2 SCR-02 Student Learning Hub + SCR-03 Workspace (lesson nav + content) | Oct–Nov | IMPLEMENTED | frontend/src/pages/Hub.jsx, Workspace.jsx, Manage.jsx, components/Shell.jsx, TutorPanel.jsx | builds; not yet clicked through in a browser | 4.1 |
| 4.3 AI session: backend-mediated Gemini Live config, WS relay, AIQuery event, no transcript persistence | Nov | IMPLEMENTED | backend/src/ai/{sessions,relay}.js, wired in app.js/server.js | backend/test/ai.test.js (4 pass, fake Gemini upstream) | GEMINI_API_KEY (live verify blocked without it) |
| 4.4 C/C++ execution proxy (Piston-compatible executor, limits, timeouts) | Nov | IMPLEMENTED | backend/src/practice/{code,routes}.js, docs/technical/practice-execution.md | backend/test/practice.test.js (fake Piston runner) | EXECUTOR_URL; live run blocked until a Piston container is available |
| 4.5 SQL sandbox (separate DB + low-priv login, SetupScript, rollback-only) | Nov | VERIFIED | backend/src/practice/sql.js, database/sandbox_setup.sql | backend/test/practice.test.js (real SynoraV1_Sandbox DB) | result compare vs ExpectedResult deferred to Assessment (Dec) |
| 4.6 SCR-03 practice panel (editor, run, output) | Nov | IMPLEMENTED | frontend/src/components/PracticePanel.jsx | SQL run verified through dev proxy (curl); C/C++ blocked without Piston; not yet clicked through in a browser | 4.4, 4.5 |
| R.1 Run/demo instructions + known limitations | Nov | NOT STARTED | README.md, docs/project/november-report.md | — | all above |

## Decisions log

- 2026-11-10: No app code existed on any branch; starting Phase 3 from zero on top of the locked schema in `database/schema.sql`.
- 2026-11-10: Branch created from `docs/canonical-dfd` (carries schema + DB docs) and `origin/main` merged in (clean).
- 2026-11-10: Phase 5 (assessment engines, telemetry, recommendations) deliberately not started; tables exist but no routes.
