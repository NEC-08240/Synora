# Synora V1 — Execution Tracker

Target: **Mid-Term Progress Review, November 2026**. Source schedule: synopsis §8.1 Gantt (Iterative & Incremental SDLC).
Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED (code + tests written) · VERIFIED (tests run and passing, manually checked).

Branch: `feature/v1-core-foundation` (from `docs/canonical-dfd` + merged `origin/main`). Not pushed.
Last full run, 11 Nov 2026: backend 28/28, frontend unit 3/3, browser smoke 11/11, lint and build clean.
Acceptance report: [november-report.md](november-report.md).

## Phase summary

| # | Gantt phase | Scheduled | Status | Notes |
|---|-------------|-----------|--------|-------|
| 1 | Requirement Analysis & SRS | Jul–Aug 2026 | VERIFIED | Synopsis, scope, V1 exclusions exist. |
| 2 | System & Database Design | Aug–Sep 2026 | IMPLEMENTED | DB design, ER, DFD, schema.sql, REST contract and AI protocol spec exist. Synopsis PDF/PPTX still say PostgreSQL; superseded by the locked SQL Server decision. |
| 3 | Core Foundation & RBAC | Sep–Oct 2026 | VERIFIED | Backend, auth, RBAC, user/batch/allocation APIs and login screen. Admin and faculty management have APIs but no forms yet. |
| 4 | Learning & Practical Workspaces | Oct–Dec 2026 | IN PROGRESS | November portion built. Live AI and live C/C++ runs are BLOCKED on external configuration. |
| — | Mid-Term Guide Review | Nov 2026 | IMPLEMENTED | Demo steps and acceptance report written. Two live checks remain blocked. |
| 5 | Assessment, Telemetry & Recommendations | Dec 2026–Jan 2027 | NOT STARTED | Out of scope for this run. Schema already covers it. |
| 6–7 | Integration, Hardening, Final | Jan–Mar 2027 | NOT STARTED | Out of scope. |

## Task detail

| Task | Period | Status | Files | Tests | Deps / blockers |
|------|--------|--------|-------|-------|-----------------|
| 2.1 REST API contract | Aug–Sep | IMPLEMENTED | docs/technical/api-spec.md | n/a (document; not audited line by line against the routes) | — |
| 2.2 WebSocket / AI protocol spec | Aug–Sep | IMPLEMENTED | docs/technical/ai-session-protocol.md | n/a (document) | — |
| 3.1 Backend scaffold (Express, config, mssql pool, error handling) | Sep–Oct | VERIFIED | backend/src/{app,server,config,db,http,validate}.js | backend suite 28 pass; server starts | Node 24, SQL Server local |
| 3.2 Authentication (login, JWT HTTP-only cookie, logout, /me, failed-login lockout) | Sep–Oct | VERIFIED | backend/src/auth/{routes,middleware}.js | backend/test/auth.test.js 10 pass | 3.1 |
| 3.3 RBAC middleware (requireAuth, requireRole) | Sep–Oct | VERIFIED | backend/src/auth/middleware.js | role-boundary cases in auth, admin, content, practice tests | 3.2 |
| 3.4 User management (admin create, list, status) | Sep–Oct | VERIFIED (API) | backend/src/routes/users.js | backend/test/admin.test.js 5 pass | 3.3. No admin screen yet |
| 3.5 Batches + FacultyAssignments (subject/batch allocation) | Sep–Oct | VERIFIED (API) | backend/src/routes/{batches,assignments}.js | backend/test/admin.test.js | 3.3. No admin screen yet |
| 3.6 Seed data (roles, subjects, topics, lessons, demo users) | Sep–Oct | VERIFIED | backend/scripts/seed.js | used by every test run and the demo | database/schema.sql |
| 3.7 Frontend scaffold (Vite, React, Tailwind tokens, router, auth context) | Sep–Oct | VERIFIED | frontend/ (vite.config.js, src/api.js, src/auth.jsx, src/App.jsx, src/index.css) | frontend/test/api.test.js 3 pass; lint; build; browser smoke | — |
| 3.8 SCR-01 Auth & Gateway (real login) | Sep–Oct | VERIFIED | frontend/src/pages/Login.jsx | browser smoke: redirect, wrong password, role-based landing | 3.2, 3.7 |
| 4.1 Lessons/Topics API (faculty CRUD, student read, LessonViewed event) | Oct–Nov | VERIFIED | backend/src/routes/content.js | backend/test/content.test.js 5 pass | 3.3 |
| 4.2 SCR-02 Student Learning Hub + SCR-03 Workspace (lesson nav + content) | Oct–Nov | VERIFIED | frontend/src/pages/{Hub,Workspace,Manage}.jsx, components/Shell.jsx | browser smoke: hub, subject expand, lesson open, three tabs | 4.1 |
| 4.3 AI session: backend-mediated Gemini Live config, WS relay, AIQuery event, no transcript persistence | Nov | IMPLEMENTED | backend/src/ai/{sessions,relay}.js, frontend/src/components/TutorPanel.jsx | backend/test/ai.test.js 4 pass (fake Gemini upstream); browser smoke shows the not-configured fallback | BLOCKED for live verify: GEMINI_API_KEY |
| 4.4 C/C++ execution proxy (Piston-compatible executor, limits, timeouts) | Nov | IMPLEMENTED | backend/src/practice/{code,routes}.js, docs/technical/practice-execution.md | backend/test/practice.test.js (fake Piston runner) | BLOCKED for live verify: EXECUTOR_URL and a Piston container |
| 4.5 SQL sandbox (separate DB + low-priv login, SetupScript, rollback-only) | Nov | VERIFIED | backend/src/practice/sql.js, database/sandbox_setup.sql | backend/test/practice.test.js (real SynoraV1_Sandbox DB); browser smoke renders the result table | result compare vs ExpectedResult deferred to Assessment (Dec) |
| 4.6 SCR-03 practice panel (editor, run, output) | Nov | VERIFIED for SQL | frontend/src/components/PracticePanel.jsx | browser smoke: SQL run end to end; C shows the not-configured notice | C/C++ output path unverified until 4.4 is live |
| R.1 Run/demo instructions + known limitations | Nov | IMPLEMENTED | README.md, docs/project/november-report.md, frontend/test/smoke.e2e.mjs | steps were followed on this machine on 11 Nov | — |

## Decisions log

- 2026-11-10: No app code existed on any branch; starting Phase 3 from zero on top of the locked schema in `database/schema.sql`.
- 2026-11-10: Branch created from `docs/canonical-dfd` (carries schema + DB docs) and `origin/main` merged in (clean).
- 2026-11-10: Phase 5 (assessment engines, telemetry, recommendations) deliberately not started; tables exist but no routes.
- 2026-11-10: AI goes through a backend WebSocket relay so the Gemini key never reaches the browser. Text modality only for now.
- 2026-11-11: C/C++ runs go to a Piston-compatible runner over HTTP. No compiler is built or bundled.
- 2026-11-11: Student SQL runs in `SynoraV1_Sandbox` under its own login, inside a transaction that is always rolled back.
- 2026-11-11: Frontend scripts call tools through `node node_modules/...` because the `&` in the folder path breaks npm shims on Windows.
- 2026-11-11: Browser smoke test drives headless Chrome over the DevTools protocol, so no test framework dependency was added.
- 2026-11-11: Login locks an address + email pair for 15 minutes after 5 failures. Counters are in memory, single instance only.
