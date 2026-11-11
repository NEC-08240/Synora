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

## Out of scope for the November milestone (Phase 5, Dec–Jan)

Activities, quiz/coding submissions, grading, StudentProgress and Recommendations endpoints are not yet defined.
