# Synora V1 REST API Contract

Base URL: `/api/v1`. All request and response bodies are JSON. Implemented in `backend/src`.

## Conventions

- **Auth**: `POST /auth/login` sets an `HttpOnly; SameSite=Lax` cookie `synora_token` (JWT, 8 h). Every other route except `/health` requires it. The user row is re-read on each request, so a `Suspended`/`Archived` user is locked out immediately.
- **Roles**: `Student`, `Faculty`, `Administrator`. Routes list the roles allowed; others get `403`.
- **Errors**: `{ "error": "<message>", "details"?: { "<field>": "<problem>" } }`.
  `400` validation, `401` not signed in, `403` wrong role / not allocated, `404` not found or not visible to this role, `409` uniqueness or FK conflict, `500` unexpected.
- **Ids** are positive integers. Timestamps are ISO-8601 UTC strings. Response objects use camelCase versions of the schema columns (`UserId` → `userId`).
- **Visibility**: students only ever see `Published` topics and lessons, and only for subjects allocated to their batch (`FacultyAssignments`). Faculty see subjects they are allocated to. Admin sees everything.

## Health

| Method | Path | Roles | Response |
|---|---|---|---|
| GET | `/health` | public | `{ status: "ok" }` |

## Auth

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{ email, password }` | `200 { user }` + cookie; `401` on bad credentials (same message for unknown email and wrong password); `429` after 5 failed attempts for the same address + email, for 15 minutes |
| POST | `/auth/logout` | – | `204`, clears cookie |
| GET | `/auth/me` | – | `200 { user }` |

`user` = `{ userId, name, email, role, status, batchId, createdAt }` (never includes the password hash).

## Users (Administrator)

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/users` | – | `{ users: [user] }` |
| POST | `/users` | `{ name, email, password (≥8), role, batchId? }` | `201 { user }`. Email lower-cased, must be unique. Only `Student` may have `batchId`. |
| PATCH | `/users/:id` | `{ name?, status?, batchId? (null clears), password? }` | `200 { user }`; `status` ∈ Active/Suspended/Archived |

## Batches

| Method | Path | Roles | Body / Response |
|---|---|---|---|
| GET | `/batches` | Admin, Faculty | `{ batches: [{ batchId, name, academicYear, status, studentCount }] }` |
| POST | `/batches` | Admin | `{ name, academicYear }` → `201 { batch }` |
| PATCH | `/batches/:id` | Admin | `{ name?, academicYear?, status? }` |

## Faculty allocations (`FacultyAssignments`)

| Method | Path | Roles | Body / Response |
|---|---|---|---|
| GET | `/assignments` | Admin (all), Faculty (own) | `{ assignments: [{ assignmentId, batchId, batchName, subjectId, subjectTitle, facultyId, facultyName, assignedAt }] }` |
| POST | `/assignments` | Admin | `{ batchId, subjectId, facultyId }` → `201 { assignment }`. `facultyId` must be an Active Faculty user. One faculty per (batch, subject) → `409`. |
| DELETE | `/assignments/:id` | Admin | `204` |

## Learning content

| Method | Path | Roles | Body / Response |
|---|---|---|---|
| GET | `/subjects` | all | `{ subjects: [{ subjectId, code, title, description, status }] }` filtered by visibility rule |
| GET | `/subjects/:id/topics` | all | `{ topics: [{ topicId, subjectId, title, orderIndex, status, lessonCount }] }`; `403` if subject not visible |
| POST | `/subjects/:id/topics` | Faculty (allocated), Admin | `{ title, orderIndex }` → `201 { topic }` (status `Draft`) |
| PATCH | `/topics/:id` | Faculty (allocated), Admin | `{ title?, orderIndex?, status? }` |
| GET | `/topics/:id/lessons` | all | `{ lessons: [{ lessonId, topicId, title, objectives, orderIndex, status }] }` |
| GET | `/lessons/:id` | all | `{ lesson: { …, contentBody, resources: [{ resourceId, resourceType, title, url, orderIndex }] } }`. For students, inserts a `LearningActivity` row `LessonViewed`. |
| POST | `/topics/:id/lessons` | Faculty (allocated), Admin | `{ title, contentBody, objectives?, orderIndex }` → `201 { lesson }` |
| PATCH | `/lessons/:id` | Faculty (allocated), Admin | `{ title?, contentBody?, objectives?, orderIndex?, status? }` |
| POST | `/lessons/:id/resources` | Faculty (allocated), Admin | `{ resourceType (Image/Video/Link), title, url (http/https), orderIndex }` → `201 { resource }` |

## AI tutor session (see `ai-session-protocol.md`)

| Method | Path | Roles | Response |
|---|---|---|---|
| POST | `/ai/sessions` | Student | `201 { sessionId, wsPath, expiresAt, context }` – authorizes a relayed Gemini Live session. Records a `LearningActivity` `AIQuery` event. Transcripts are never persisted. |

## Practical execution (see `practice-execution.md`)

| Method | Path | Roles | Body / Response |
|---|---|---|---|
| GET | `/execute/status` | Student, Faculty | → `{ code, sql }` runner availability |
| POST | `/execute/code` | Student, Faculty | `{ language: "c"\|"cpp", source, stdin? }` → `{ stdout, stderr, exitCode, timedOut, compileError, durationMs }` via a Piston-compatible runner (503 if unconfigured) |
| POST | `/execute/sql` | Student, Faculty | `{ sql, setupScript? }` → `{ columns, rows, rowCount, truncated, error }` run in `SynoraV1_Sandbox` inside a rolled-back transaction, never `SynoraV1`. See docs/technical/practice-execution.md |

## Assessment (Module 3, see `assessment-spec.md`)

Router `backend/src/assessment/`. All routes need a session. Administrator is read-only. Students only reach `Published` activities under a `Published` topic for subjects allocated to their batch; anything else is `404`.

| # | Method | Path | Roles | Notes |
|---|---|---|---|---|
| 1 | GET | `/topics/:topicId/activities` | all | Student: Published only, student projection |
| 2 | POST | `/topics/:topicId/activities` | Faculty | Create as Draft. Faculty authors if assigned to the subject in at least one batch (D1) |
| 3 | GET | `/activities/:id` | all | Student projection hides `isCorrect`, `explanation`, test cases and expected results; Faculty/Admin get the authoring view |
| 4 | PATCH | `/activities/:id` | Faculty | `409` once Published or submitted to |
| 5 | POST | `/activities/:id/status` | Faculty | `{status}` Draft, Published, Archived; publish re-validates completeness |
| 6 | PUT | `/activities/:id/questions` | Faculty | Quiz: replaces the whole set; exactly one correct option per question |
| 7 | PUT | `/activities/:id/test-cases` | Faculty | Coding: replaces the set; every case is hidden from students (D2) |
| 8 | PUT | `/activities/:id/sql-spec` | Faculty | SQL: `setupScript` and expected result |
| 9 | GET | `/activities/:id/draft` | Student | Own draft or `{ content: null }` |
| 10 | PUT | `/activities/:id/draft` | Student | `content` at most 64 KB; not for Quiz |
| 11 | POST | `/activities/:id/submissions` | Student | Quiz `{answers}`, Coding `{source}`, SQL `{sql}`, Assignment `{content}`; at most 1 MB. Practice returns `400` "not graded" (D6). Quiz, Coding and SQL return the finished grade with `201` |
| 12 | GET | `/activities/:id/submissions/mine` | Student | Own attempts, student projection |
| 13 | GET | `/submissions/:id` | Student, Faculty, Admin | Student asking for a missing or someone else's submission gets `404`, never `403` |
| 14 | POST | `/activities/:id/events` | Student | `{ eventType: "TabSwitch" }` only; more than 1 per 5 s per student and activity is dropped with `204` |
| 15 | GET | `/activities/:id/submissions` | Faculty, Admin | In-scope submissions; query `status`, `studentId`, `limit` (1-100, default 50), `offset` |
| 16 | PATCH | `/submissions/:id/grade` | Faculty | `{ score, feedback? }`, `0 <= score <= maxScore`, feedback at most 8000 chars |
| 17 | GET | `/submissions/:id/results` | Faculty, Admin | Per-test-case results including hidden data |

**Limits (`400` when exceeded):** at most 50 questions, 10 options per question, 50 test cases, 20,000 characters per authoring text field, execution time limit at most 600,000 ms, max score at most 999.99.

**Student projection rule:** students never receive `isCorrect`, `explanation`, test-case input or expected output, the SQL expected result, or per-case output. Coding feedback is only `{ passed, total, compileError?, timedOut? }`. `setupScript` is student-visible.

**Overload and failure rules:** grading runs behind a bounded queue. When it is full the caller gets `429`, a runner or sandbox that is unavailable or fails gives `503`, and in both cases nothing is written, so the student retries. A per-student submit rate limit (`RATE_LIMIT_SUBMIT_PER_MIN`, default 10) also returns `429` with `Retry-After`. No attempt limit and no deadline exist in V1 (D4); a double submit that collides on the attempt number returns `409`.

## Out of scope for the November milestone (Phase 5, Dec–Jan)

StudentProgress and Recommendations endpoints are not yet defined.
