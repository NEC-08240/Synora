# Module 3 — Assessment Backend Specification

Status: DRAFT for owner review. Base: release/v1 (22e9349). Scope: backend only, on the **existing** schema (`database/schema.sql:173-347`). No schema change, no new dependency.
Items marked **ASSUMPTION** are my reading, not owner-confirmed. Items in §10 are **not decided**; each has a labelled *proposed default* that implementation tasks must route through one swappable function so the decision never blocks them.

## 1. Scope and locked rules

Covers: authoring Activities (Quiz, Coding, SQL, Assignment, Practice), student reading/draft/submit, auto-grading (Quiz, Coding, SQL), manual grading (Assignment, and override), submission review, `TabSwitch` telemetry.

Locked rules (from owner): single-answer quizzes (PK `SubmissionAnswers(SubmissionId, QuestionId)` schema.sql:303, one-correct-option filtered unique index); hidden test cases are never exposed in any response, error or log; SQL expected result lives in `SqlTaskSpecs`; drafts are server-side in `PracticeDrafts`; AI conversations are never persisted; `TabSwitch` is non-punitive audit telemetry only; similarity is a visual placeholder (no backend); `Activities`↔`SqlTaskSpecs` 1:1; one faculty per subject per batch (`UQ_FacultyAssignments_Batch_Subject`, schema.sql:132); subjects: C, C++, DBMS/SQL.

Roles: Student / Faculty / Administrator. Administrator is **read-only** on assessments (mirrors `app.js:45`, which already rejects Administrator on `/execute`).

## 2. Data model recap (what each column is for)

| Table | Key facts |
|---|---|
| `Activities` :174 | `ActivityType` ∈ Practice/Quiz/Coding/SQL/Assignment; `Status` Draft/Published/Archived; `IsGraded=0` only for Practice (:192); graded ⇒ `MaxScore` NOT NULL (:195); `TimeLimitMs` = **execution** limit for Coding/SQL (database-design.md:187), *not* quiz duration; `CreatedBy` → Users; `StarterCode`, `Hints`, `Instructions` student-visible. Belongs to a Topic → Subject. |
| `QuizQuestions` :203 / `QuizOptions` :218 | `Points>0`; `OrderIndex` unique per parent; `IsCorrect` hidden from students; `Explanation` see §10-D5. |
| `TestCases` :233 | `InputData`, `ExpectedOutput`, `OrderIndex`. **No hidden/visible flag.** |
| `SqlTaskSpecs` :246 | `SetupScript`, `ExpectedResult` (JSON, `ISJSON`=1 only). |
| `PracticeDrafts` :259 | one row per (Student, Activity), upsert; `Content` text. |
| `Submissions` :273 | `AttemptNo`, `Status` Submitted/Graded, `Score`, `Feedback`, `GradedBy` (NULL = auto), `GradedAt`; `Graded ⇒ Score NOT NULL` (:290). |
| `SubmissionAnswers` :298 | (SubmissionId, QuestionId)→OptionId; composite FK guarantees option belongs to the question. |
| `TestCaseResults` :313 | `Passed`, `ActualOutput`, `ExecutionTimeMs` — internal; see §6 leak rule. |
| `LearningActivity` :332 | `EventType` only ActivitySubmitted/TabSwitch carry an `ActivityId`. |

## 3. Access model

All routes sit behind `requireAuth`. Access decisions live in **one module** `backend/src/assessment/access.js` (foundation task) exporting:

- `assertCanReadActivity(user, activity)` — Student: Published activity whose Subject is allocated to the student's batch (via `FacultyAssignments`, same rule as `assertCanReadSubject` in content.js); Faculty: assigned to that subject in ≥1 batch; Admin: any (read-only).
- `assertCanAuthorActivity(user, subjectId, activity?)` — **the only place the open authoring decision (§10-D1) is implemented.** Returns/throws 403.
- `assertCanGradeSubmission(user, submission)` — Faculty assigned (FacultyAssignments) to the **student's batch** for the activity's subject. Admin → 403 (read-only). Batch-level scope, unlike authoring.
- `assertStudent(user)` for student endpoints.

content.js `assert*` helpers are not exported today; foundation task exports/reuses them rather than copying.

## 4. API surface (all under `/api/v1`, camelCase, errors `{error, details?}`)

Router naming: **`assessmentRouter`** in `backend/src/assessment/` — must not be confused with `routes/assignments.js` (`/assignments` = FacultyAssignments). Paths avoid the word "assignments" for this module (the activity type `Assignment` is a value, not a path). Mounted after `/execute`, before the catch-all `contentRouter` (app.js:46).

### 4.1 Authoring (Faculty write; Admin read)
| # | Method & path | Notes |
|---|---|---|
| 1 | `GET /topics/:topicId/activities` | List. Student sees Published only, student projection. |
| 2 | `POST /topics/:topicId/activities` | Create (Draft). Body: type, title, instructions, isGraded, maxScore, starterCode?, hints?, timeLimitMs?. Validates §5 invariants. |
| 3 | `GET /activities/:id` | Student: projection (§6). Faculty/Admin: full authoring view incl. hidden data. |
| 4 | `PATCH /activities/:id` | Edit. Blocked by edit lock (§7.5). |
| 5 | `POST /activities/:id/status` | `{status}` Draft→Published→Archived. Publish validates completeness (§5). |
| 6 | `PUT /activities/:id/questions` | Replace full question+option set (Quiz). One correct option per question (index). |
| 7 | `PUT /activities/:id/test-cases` | Replace test cases (Coding). |
| 8 | `PUT /activities/:id/sql-spec` | Set `setupScript` + `expectedResult` (SQL). |
Replace-style PUTs avoid per-row ordering races and respect the unique `(parent, OrderIndex)` constraints. Delete = `status: Archived` (no hard delete: NO ACTION FKs :305-308, :325).

### 4.2 Student work
| # | Method & path | Notes |
|---|---|---|
| 9 | `GET /activities/:id/draft` | Own draft or `{content: null}`. |
| 10 | `PUT /activities/:id/draft` | Upsert `PracticeDrafts` (UQ :266). `content` ≤ 64 KB. Allowed for Coding/SQL/Assignment/Practice, not Quiz. |
| 11 | `POST /activities/:id/submissions` | Submit (§7). Quiz: `{answers:[{questionId,optionId}]}`; Coding: `{source, language}`; SQL: `{sql}`; Assignment: `{content}`; Practice: not graded (`IsGraded=0`, database-design.md:426). **ASSUMPTION (D6):** returns 400 "not graded"; Practice uses `/execute/*` + draft only. |
| 12 | `GET /activities/:id/submissions/mine` | Own attempts, student projection (§6). |
| 13 | `GET /submissions/:id` | Own (Student) or in-scope (Faculty/Admin). |
| 14 | `POST /activities/:id/events` | `{eventType:'TabSwitch'}` only; rate-limited (§7.7). `ActivitySubmitted` is server-written, never client-sent. |
"Run Tests" for Coding = the existing `POST /execute/code` with the student's own stdin (§10-D2 default) — **no** new endpoint, nothing hidden is executed on the student's behalf.

### 4.3 Faculty review and grading
| # | Method & path | Notes |
|---|---|---|
| 15 | `GET /activities/:id/submissions` | In-scope submissions (batch-level, §3), filter `status`, `studentId`; paged. |
| 16 | `PATCH /submissions/:id/grade` | `{score, feedback?}`; sets Status Graded, `GradedBy`=faculty, `GradedAt`. Works for Assignment, and as override for auto-graded. Validates `0 ≤ score ≤ MaxScore` (no DB check exists). |
| 17 | `GET /submissions/:id/results` | Faculty/Admin only: `TestCaseResults` incl. hidden data. |
**Endpoint count: 17.**

## 5. Activity invariants (validated in backend)

- Quiz: ≥1 question; each question ≥2 options and **exactly one** `IsCorrect` (the filtered unique index only enforces *at most* one, schema.sql ~:385).
- Coding: ≥1 test case; language is `c` or `cpp` (§10-D3); `TimeLimitMs` default from practice config.
- SQL: exactly one `SqlTaskSpecs` row (1:1); `expectedResult` matches §6.2 shape; `setupScript` validated by a dry run in the sandbox on publish.
- Assignment: no auto-grader; `MaxScore` required.
- `MaxScore`: for Quiz must equal Σ `Points` (**ASSUMPTION** — avoids two sources of truth); for Coding = Σ equal per-test weights (`MaxScore/N`, rounded in §6.1); SQL/Assignment: free.
- Publish requires all of the above.

## 6. Grading rules

### 6.1 Coding
For each test case in `OrderIndex`: `runCode({language, source, stdin: InputData})` (practice/code.js). Pass ⇔ exit 0, not timedOut, not compileError, and stdout equals `ExpectedOutput` after normalising `\r\n`→`\n` and trimming trailing whitespace per line and trailing blank lines. `Score = MaxScore × passed/total`, rounded to 2 dp (DECIMAL(5,2)). Runner unavailable (503/502) ⇒ submission stays `Submitted`, 503 to caller, nothing partial written. Writes `TestCaseResults`.

### 6.2 SQL
`runSql({sql: studentSql, setupScript})` returns `{columns, rows, rowCount, truncated, error}` (first recordset only, serial queue). `ExpectedResult` JSON shape: `{"columns":["a","b"],"rows":[[1,"x"],…],"orderMatters":false}`. Compare: column names case-insensitive and in order; values compared with NULL=NULL, numbers numerically, strings exact; if `orderMatters` false rows compared as multisets. `truncated` or `error` ⇒ fail. Score: all-or-nothing `MaxScore`. **Limit:** only the first result set is compared; multi-statement answers are not partially credited.

### 6.3 Quiz
Per question: correct iff chosen option `IsCorrect`. `Score = Σ Points of correct`. Every question must be answered or 400. Option must belong to the question (composite FK is the backstop).

### 6.4 Assignment
Stored `Submitted`; only faculty grading (#16) moves it to `Graded`.

### Hidden-data protection (applies to every endpoint)
- One **projection function per entity** in `backend/src/assessment/project.js`; routes never serialise DB rows directly. Student projections exclude: `IsCorrect`, `Explanation` (until §10-D5 reveals), `InputData`, `ExpectedOutput`, `SetupScript`, `ExpectedResult`, `TestCaseResults.ActualOutput`/stderr, `ExecutionTimeMs` of hidden cases.
- Student feedback for Coding is only `{passed, total, compileError?, timedOut?}`. **Never** per-case output: a program that echoes stdin would leak hidden input.
- Error bodies and logs: grading errors log `err.message` only, never payload, source, stdin or expected values.
- **Sentinel test required:** seed a unique string in every hidden field, exercise every student endpoint (success and error paths), assert the string appears in no body.

## 7. Behaviour details

7.1 **Start attempt.** No in-progress Submission status, start time, deadline or attempt-limit column exists (schema.sql:273-294; due dates excluded, database-design.md:414). "Start" is just `GET /activities/:id` + draft. `AttemptNo` is assigned at submit. The server **cannot enforce** a timer, deadline or "1/3 attempts" shown in the prototype; any such UI is advisory. Gap recorded §9.
7.2 **Double submit.** In one transaction: `SELECT MAX(AttemptNo) … WITH (UPDLOCK, HOLDLOCK)`, insert `AttemptNo+1`. Unique `UQ_Submissions_Activity_Student_Attempt` (:286) is the backstop; violation ⇒ 409.
7.3 **Grading flow.** Insert `Submitted` + `ActivitySubmitted` event in the submit transaction; grade after commit behind a bounded in-process semaphore (size = config, default 4; no new dependency); then update to `Graded`, `GradedBy` NULL. Runner/sandbox busy ⇒ 429 / stays `Submitted`. **Recovery:** rows stuck `Submitted` (crash) for an auto-graded type are re-graded by `POST /submissions/:id/regrade` (faculty, **ASSUMPTION** — adds endpoint #18) or at server start by a sweep of auto types older than 5 min. Foundation task picks one; default = start-up sweep only (no extra endpoint).
7.4 **Score bounds.** `0 ≤ Score ≤ MaxScore` in backend (only `Score ≥ 0` is DB-checked, :289).
7.5 **Edit lock.** Once an Activity is Published or has any Submission, question/option/test-case/spec edits are 409 (FKs :305-308, :325 are NO ACTION, edits would fail or rewrite history). Archive instead.
7.6 **Concurrency (≈30 students).** `runSql` is serial with queue max/wait (sandbox config); grading semaphore bounds code runs; surplus ⇒ 429 with Retry-After, never an unbounded wait.
7.7 **Telemetry.** `TabSwitch` accepted only for Published activities the student may read, ≤ 1 per 5 s per (student, activity) (excess ⇒ 204 dropped silently). Grading and scoring code **must not read** `LearningActivity`.
7.8 **Practice.** Not graded; no submission endpoint use (see #11).

## 8. Implementation task split

| Task | Owns (disjoint) | Depends | Notes |
|---|---|---|---|
| **M3-0 Foundation (sequential, first)** | `backend/src/app.js` (mount), `backend/src/config.js` (semaphore/rate keys), `backend/test/helpers.js` (fixtures), `backend/src/assessment/access.js`, `project.js`, `grader.js` (interface `grade(activity, payload) → {score, results}`), export of content.js `assert*` | — | Everyone else imports from here. |
| M3-1 Authoring | `assessment/activities.js` + `test/assessment-authoring.test.js` | 0 | Endpoints 1-8. |
| M3-2 Student work + submit | `assessment/submissions.js` + `test/assessment-submit.test.js` | 0 | Endpoints 9-14 (events incl.), AttemptNo txn. |
| M3-3 Graders | `assessment/graders/quiz.js`, `code.js`, `sql.js` + `test/assessment-graders.test.js` | 0 | Pure functions on grader interface. |
| M3-4 Faculty review | `assessment/review.js` + `test/assessment-review.test.js` | 0,2 | Endpoints 15-17. |
| M3-5 Hidden-data sentinel + docs | `test/assessment-sentinel.test.js`, **only this task edits** `docs/technical/api-spec.md` | 1-4 | Sentinel runs last. |
M3-1…M3-4 can run in parallel after M3-0. Frontend work is out of scope.

## 9. Conflicts and gaps found (not silently resolved)

1. **Hidden tests vs docs:** database-design.md:22,229,411 (Decision 7) says *all test cases visible*; owner rule says never exposed; `TestCases` has no flag (schema.sql:233-242) and the prototype shows "(Hidden)". Default in D2.
2. **No `language` column** on Activities for Coding (D3).
3. **No deadline/attempt limit/start time/in-progress status** — timer, due date, "1/3 allowed" are unenforceable (7.1).
4. `ExpectedResult` is only `ISJSON` — shape defined here (6.2) and **not** defined in any existing doc.
5. `TimeLimitMs` is execution limit, not quiz duration (database-design.md:187).
6. Authoring vs FacultyAssignments: UQ(Batch,Subject) means two faculty sharing a subject across batches cannot both pass an "assigned in every batch" rule (D1).
7. `QuizOptions` index permits zero correct options; app must require exactly one.
8. `Submissions.Status` has no "InProgress"/"Regrading".
9. `api-spec.md:~83` still says assessment endpoints are undefined — updated by M3-5 only.

## 10. Open decisions (owner) — proposed defaults are NOT chosen

- **D1 Who may author content for a subject taught to several batches by different faculty?**
  - *Option A (subject-level):* faculty may author if assigned to the subject in **at least one** batch.
  - *Option B (creator-owns):* only `Activities.CreatedBy` may edit; others read-only (no schema change). Admin read-only in both.
  Implemented only in `assertCanAuthorActivity`; default for tests: Option A. Today's existing rule (`assertAssignedToSubject`) requires assignment in every batch, which 403s co-teaching faculty — recorded, not changed.
- **D2 Hidden test cases:** proposed default — **every** TestCase is hidden from students; visible examples go in `Instructions`; students use `/execute/code`. Alternative: add `IsHidden` (schema change, needs approval).
- **D3 Coding language:** proposed — student selects `c`/`cpp` at submit; alternative derive from Subject (C vs C++).
- **D4 Attempt limit / deadline:** none enforced (no columns). Alternative: new columns (schema change).
- **D5 Quiz answer reveal:** proposed — never return `IsCorrect`/`Explanation` to students until attempts are exhausted *and* no limit exists ⇒ effectively never to students; faculty only. Alternative: reveal after each submit (leaks answers for retry).
- **D6 Practice submit:** confirm Practice is draft-only (no Submissions rows).

## ASSUMPTION list
1. Quiz `MaxScore` = Σ Points. 2. Coding scoring proportional, SQL all-or-nothing. 3. Practice has no submit endpoint. 4. Recovery by start-up sweep. 5. Sandbox/runner-busy ⇒ 429/503 with row left `Submitted`. 6. TabSwitch rate limit 1/5 s. 7. Semaphore size 4. 8. Replace-style PUT for question/test sets. 9. Endpoint count 17 (18 if regrade endpoint chosen).
