# Synora V1 — November 2026 Acceptance Report

Prepared 11 November 2026 for the Mid-Term Progress Review; release-candidate evidence refreshed 14 November 2026. Candidate branch `trial/rc1` at `6b927a4`, not pushed.
Task-level detail lives in [execution-tracker.md](execution-tracker.md).

**Verdict: not fully complete.** Everything scheduled through November is built and tested, but two
deliverables have never run against the real external service: the AI tutor (no Gemini key) and
C/C++ execution (no Piston runner). Both are verified only against fakes.

## 1. Gantt tasks completed

| Phase | Scheduled | Status |
|---|---|---|
| 1 Requirement Analysis & SRS | Jul–Aug | Verified (pre-existing) |
| 2 System & Database Design | Aug–Sep | Implemented: schema, ER, DFD, REST contract, AI protocol spec |
| 3 Core Foundation & RBAC | Sep–Oct | Verified: backend, auth, RBAC, user/batch/allocation APIs, login screen |
| 4 Learning & Practical Workspaces, November portion | Oct–Nov | Lesson delivery, hub, workspace and SQL sandbox verified |

## 2. Gantt tasks not completed

| Task | State | Reason |
|---|---|---|
| 4.3 AI tutor, live | Implemented, live check blocked | `GEMINI_API_KEY` not available |
| 4.4 C/C++ execution, live | Implemented, live check blocked | No Piston runner; needs Docker and `EXECUTOR_URL` |
| Admin and faculty screens | APIs verified, no forms | Only a read-only subject list exists at `/manage` |
| Synopsis PDF/PPTX | Still name PostgreSQL | Binary files; the locked decision is SQL Server |

## 3. Implemented features

- Sign in, sign out, role-based landing, route guards for Student, Faculty and Administrator.
- Administrator APIs: create and list users, change status, batches, faculty-to-subject/batch allocation.
- Faculty APIs: create and publish topics and lessons for allocated subjects.
- Student: subjects allocated to their batch, topics, lessons, lesson content with objectives and resources.
- Practice panel: C, C++ and SQL editor with run and output.
- AI tutor pane: session creation, streaming text chat over a WebSocket relay, fallback notice.
- Learning events recorded: `LessonViewed`, `AIQuery`.

## 4. Frontend status

React 19, Vite, Tailwind 4, plain JavaScript. Screens SCR-01, SCR-02, SCR-03 work against the real API.
The editor is a plain textarea. Lesson content renders as plain text. The practice panel is a scratchpad,
not yet tied to activities or submissions.

## 5. Backend status

Node.js and Express, routes under `/api/v1`: health, auth, users, batches, assignments, content, ai, execute.
Input validation and a single JSON error shape on every route. Contract in `docs/technical/api-spec.md`.

## 6. Database status

SQL Server, `SynoraV1` from `database/schema.sql`, unchanged by this work. Seed script `backend/scripts/seed.js`.
Separate `SynoraV1_Sandbox` database and login from `database/sandbox_setup.sql`. Phase 5 tables exist with no routes.

## 7. AI integration status

The browser asks the backend for a single-use session, then opens a WebSocket to the backend, which relays
to Gemini Live. The key stays on the server. No transcript is stored. Without a key the session reports
`available: false` and the pane says so. Text only; audio and video are not wired.

## 8. Practical execution status

- **SQL:** working. Runs only in the sandbox database, in a transaction that is always rolled back.
- **C/C++:** proxy to a Piston-compatible runner with compile and run timeouts. Never run live.

## 9. Test results

| Suite | Command | Result |
|---|---|---|
| Backend API and required sandbox regression suite, disposable test/lab DB | `cd backend && npm run test:ci` | Passed 14 Nov; suite refuses protected real sandbox database names |
| Frontend unit | `cd frontend && npm test` | 7 pass, 0 fail (14 Nov) |
| Browser smoke, headless Chrome | `cd frontend && npm run smoke` | Previously passed 11 steps on 11 Nov; not rerun in this release pass |
| Lint | `npm run lint` | 2 warnings, 0 errors (14 Nov) |
| Build | `npm run build` | Passed (14 Nov) |

Coverage was not measured. There are no React component unit tests; the browser smoke covers the screens. Full release evidence, scope and exclusions are in [release-readiness-2026-11-14.md](release-readiness-2026-11-14.md).

## 10. Security and implementation review

In place: bcrypt hashes; JWT in an HttpOnly, SameSite=Lax cookie; user re-read on every request so a
suspended account is locked out at once; same error for unknown email and wrong password; lockout after
5 failed logins; role checks on every route; parameterised queries; CORS allowlist; WebSocket origin and
cookie checks; 1 MB body limit; lesson content rendered as text; resource links limited to http/https;
secrets only in gitignored `.env` files.

Open:
- No general rate limiting and no security headers (helmet).
- No CSRF token; relies on SameSite=Lax plus the CORS allowlist.
- Login lockout counters and AI sessions are in memory, so single instance only.
- The SQL sandbox isolates schema and data, not CPU or memory inside the SQL Server instance.
- `database/sandbox_setup.sql` and the seed use documented demo passwords. Change them outside a demo.
- No independent code review has been done on this branch.

## 11. Git commits and outstanding PRs

Commits on `feature/v1-core-foundation` ahead of `main`, newest first:

| Commit | Summary |
|---|---|
| (this commit) | docs: tracker refresh, run instructions, this report |
| 412c3c2 | fix: failed-login lockout; headless browser smoke test |
| b15de8f | feat: React frontend, login, hub, workspace, practice panel, AI tutor pane |
| 08541fd | docs: execute endpoints in API spec |
| ac47334 | feat: C/C++ execution proxy and SQL sandbox |
| 513c0bc | test: AI relay test fix |
| 611c2aa | feat: AI tutor session API and Gemini Live relay |
| b263013 | feat: Express backend, JWT auth, RBAC, user/batch allocation, lesson APIs |
| 0d6bd9c | docs: execution tracker |

The branch also carries the earlier schema and ER commits from `docs/canonical-dfd`.
Nothing is pushed and no PR is open. Pushing and opening the PR need the owner's authorisation.

## 12. Remaining December–March work

- December: finish Phase 4 with live AI and C/C++ checks, faculty authoring and admin screens, a code editor component.
- December–January, Phase 5: MCQ, coding and SQL assessments, assignments and submissions, telemetry, analytics, rule-based recommendations.
- January–March, Phases 6–7: integration, hardening (rate limits, headers, shared session store), Docker packaging, final documentation.

## 13. Running and demonstrating

Setup is in the root `README.md` under "Running locally". Demo script, all accounts use the seeded demo password:

1. Open `http://localhost:5173`. You are sent to the login page.
2. Sign in as `student@synora.local`. The hub lists C Programming, C++ Programming and DBMS/SQL.
3. Open C Programming, pick a lesson. Show the Theory, Objectives and Resources tabs.
4. In the practice panel choose SQL and press Run. A result table appears.
5. Choose C. With a Piston runner it prints the output; without one it shows the not-configured notice.
6. Press "Start tutor session". With a Gemini key you can chat; without one it shows the fallback.
7. Sign out, sign in as `faculty@synora.local`. You land on `/manage`, and `/learn` is refused.
8. For administrator workflows, show the API tests: `cd backend && npm test`.
