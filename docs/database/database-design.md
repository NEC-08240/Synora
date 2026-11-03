# Synora Database Design (Microsoft SQL Server)

## Overview
This document defines the V1 relational schema for Synora Live Smart Edification on **Microsoft SQL Server**, the official V1 database engine. It implements the owner-locked decisions for V1 and is the source for the DFD data-store mapping, the ER diagram, and the T-SQL DDL in `database/schema.sql`.

Scope: C Programming, C++ Programming, and DBMS/SQL, with roles Student, Faculty, and Administrator. The schema is a clean V1 academic schema, not an enterprise LMS.

Status: **design locked; ER diagram and SQL Server DDL created.**

---

## 1. Locked Decisions Applied

| # | Decision | Effect on schema |
|---|---|---|
| 1 | Student belongs to ONE batch | `Users.BatchId` (nullable, Students only). No BatchEnrollments table. |
| 2 | Administrator creates/manages batches, enrols students, assigns faculty | Batches and FacultyAssignments are written only by Administrator role. |
| 3 | A batch can have multiple faculty; each Subject within a Batch has one Faculty in V1 | `FacultyAssignments` with `UNIQUE(BatchId, SubjectId)`. |
| 4 | No Course entity; hierarchy is Subject → Topic → Lesson | No Courses table. |
| 5 | No multi-select questions | Quiz questions are single-answer. |
| 6 | No open-text / short-answer responses | No TextResponse column. |
| 7 | No hidden test cases | No IsHidden column. |
| 8 | Lesson objectives are lesson metadata only | `Lessons.Objectives` column. No Objectives entity. |
| 9 | Tab-switch telemetry is kept, non-punitive | Event type `TabSwitch` in LearningActivity. Audit only. |
| 10 | AI transcripts are not persisted | No transcript or conversation entity. AI queries are logged as an event with no content. |
| 11 | Practical drafts stored on backend | `PracticeDrafts` table. |
| 12 | SQL expected results stored as JSON | `SqlTaskSpecs.ExpectedResult` (JSON). No separate result entity. |
| 13 | Canonical DFD uses the same D1–D5 mapping | Section 2 is the mapping. DFD must be updated to match (see section 9). |
| 14 | SQL Server is the V1 engine | All references use Microsoft SQL Server. |

---

## 2. DFD Data Store Mapping

Store names follow the Synora data-store names used in `Synora_DFD.docx`: D1 User Data, D2 Course Content, D3 Assessment Data, D4 Submission Data, D5 Analytics Data.

| DFD Data Store | Database Entities |
|---|---|
| **D1 User Data** | Roles, Users, Batches, FacultyAssignments |
| **D2 Course Content** | Subjects, Topics, Lessons, LessonResources |
| **D3 Assessment Data** | Activities, QuizQuestions, QuizOptions, TestCases, SqlTaskSpecs |
| **D4 Submission Data** | Submissions, SubmissionAnswers, TestCaseResults, PracticeDrafts |
| **D5 Analytics Data** | LearningActivity, StudentProgress, Recommendations |
| *(no store — external)* | AI Service: no persisted data. Only LearningActivity `AIQuery` events (no content) reach D5. |

Assumption: PracticeDrafts is student work in progress, so it sits with Submission Data (D4). The DFD should show a "save draft" flow into D4 if it does not already.

---

## 3. Entity List (20)

1. Roles
2. Users
3. Batches
4. FacultyAssignments
5. Subjects
6. Topics
7. Lessons
8. LessonResources
9. Activities
10. QuizQuestions
11. QuizOptions
12. TestCases
13. SqlTaskSpecs
14. PracticeDrafts
15. Submissions
16. SubmissionAnswers
17. TestCaseResults
18. LearningActivity
19. StudentProgress
20. Recommendations

Removed from the previous design: Assessments (replaced by Activities), SubjectEnrollments, AILogs. Added: Batches, FacultyAssignments, LessonResources, SqlTaskSpecs, PracticeDrafts, LearningActivity, Recommendations.

---

## 4. Entity Definitions

Conventions: all primary keys are `INT IDENTITY` unless noted. Timestamps are `DATETIME2`. Soft deletion uses a `Status` column (FR4.7). Hard deletes are blocked by `NO ACTION` foreign keys except for owned child rows (section 5).

### 4.1 D1: User Data

#### Roles
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| RoleId | INT | PK | Role identifier. |
| RoleName | NVARCHAR(30) | UNIQUE, NOT NULL, CHECK in ('Student','Faculty','Administrator') | RBAC role. |
| Description | NVARCHAR(255) | NULL | Role summary. |

#### Users
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| UserId | INT | PK | User identifier. |
| RoleId | INT | FK → Roles, NOT NULL | Role for RBAC. |
| BatchId | INT | FK → Batches, NULL | The student's single batch. NULL for Faculty and Administrator. Enforced by backend. |
| Name | NVARCHAR(100) | NOT NULL | Full name. |
| Email | NVARCHAR(255) | UNIQUE, NOT NULL | Login identifier. |
| PasswordHash | NVARCHAR(255) | NOT NULL | Hashed password. |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Active','Suspended','Archived'), default 'Active' | Soft-delete and access state. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

#### Batches
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| BatchId | INT | PK | Batch identifier. |
| Name | NVARCHAR(100) | UNIQUE, NOT NULL | Batch name. |
| AcademicYear | NVARCHAR(20) | NOT NULL | e.g. "2026-27". |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Active','Archived') | Soft delete. |
| CreatedBy | INT | FK → Users, NOT NULL | Administrator who created the batch. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

#### FacultyAssignments
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| AssignmentId | INT | PK | Assignment identifier. |
| BatchId | INT | FK → Batches, NOT NULL | The batch. |
| SubjectId | INT | FK → Subjects, NOT NULL | The subject taught to that batch. |
| FacultyId | INT | FK → Users, NOT NULL | The assigned faculty member (must have role Faculty; enforced by backend). |
| AssignedBy | INT | FK → Users, NOT NULL | Administrator who made the assignment. |
| AssignedAt | DATETIME2 | NOT NULL | Assignment time. |

Constraint: `UNIQUE(BatchId, SubjectId)`. Each batch has one faculty per subject in V1.

### 4.2 D2: Course Content

#### Subjects
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| SubjectId | INT | PK | Subject identifier. |
| Title | NVARCHAR(150) | UNIQUE, NOT NULL | "C Programming", "C++ Programming", "DBMS/SQL" (V1 set). |
| Description | NVARCHAR(MAX) | NULL | Overview. |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Active','Archived') | Soft delete. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

#### Topics
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| TopicId | INT | PK | Topic identifier. |
| SubjectId | INT | FK → Subjects, NOT NULL | Parent subject. |
| Title | NVARCHAR(150) | NOT NULL | Topic name. |
| OrderIndex | INT | NOT NULL | Position in subject. |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Draft','Published','Archived') | Students see Published only. |
| CreatedBy | INT | FK → Users, NOT NULL | Faculty author. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

Constraint: `UNIQUE(SubjectId, OrderIndex)`.

#### Lessons
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| LessonId | INT | PK | Lesson identifier. |
| TopicId | INT | FK → Topics, NOT NULL | Parent topic. |
| Title | NVARCHAR(150) | NOT NULL | Lesson name. |
| ContentBody | NVARCHAR(MAX) | NULL | Instructional text, including code examples. |
| Objectives | NVARCHAR(MAX) | NULL | Learning objectives, as lesson metadata (Decision 8). |
| OrderIndex | INT | NOT NULL | Position in topic. |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Draft','Published','Archived') | Publication state. |

Constraint: `UNIQUE(TopicId, OrderIndex)`.

#### LessonResources
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| ResourceId | INT | PK | Resource identifier. |
| LessonId | INT | FK → Lessons, NOT NULL, owned (cascade) | Parent lesson. |
| ResourceType | NVARCHAR(20) | NOT NULL, CHECK in ('Image','Video','Link') | Media type. |
| Title | NVARCHAR(150) | NOT NULL | Display label. |
| Url | NVARCHAR(500) | NOT NULL | External URL. No file uploads in V1. |
| OrderIndex | INT | NOT NULL | Position in lesson. |

Constraint: `UNIQUE(LessonId, OrderIndex)`.

### 4.3 D3: Assessment Data

#### Activities
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| ActivityId | INT | PK | Activity identifier. |
| TopicId | INT | FK → Topics, NOT NULL | Parent topic. |
| Title | NVARCHAR(150) | NOT NULL | Activity name. |
| Instructions | NVARCHAR(MAX) | NOT NULL | Problem statement. |
| ActivityType | NVARCHAR(20) | NOT NULL, CHECK in ('Practice','Quiz','Coding','SQL','Assignment') | Kind of activity. |
| IsGraded | BIT | NOT NULL, CHECK (IsGraded = 0 only when ActivityType = 'Practice') | Whether the activity affects grades. |
| MaxScore | DECIMAL(5,2) | NULL, CHECK (MaxScore > 0) when IsGraded = 1 | Maximum points. |
| StarterCode | NVARCHAR(MAX) | NULL | Starter template for Coding, SQL, and Assignment. |
| Hints | NVARCHAR(MAX) | NULL | Guided hints (§5.2). |
| TimeLimitMs | INT | NULL, CHECK (> 0) | Execution time limit for Coding and SQL (FR2.5). |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Draft','Published','Archived') | Students see Published only. |
| CreatedBy | INT | FK → Users, NOT NULL | Faculty author. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

Output-size limit (FR2.5) is backend configuration, not a column.

#### QuizQuestions
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| QuestionId | INT | PK | Question identifier. |
| ActivityId | INT | FK → Activities, NOT NULL, owned (cascade) | Parent quiz activity. |
| QuestionText | NVARCHAR(MAX) | NOT NULL | Prompt. |
| Explanation | NVARCHAR(MAX) | NULL | Feedback after submission. |
| Points | DECIMAL(5,2) | NOT NULL, CHECK (> 0) | Points for a correct answer. |
| OrderIndex | INT | NOT NULL | Position in quiz. |

Constraint: `UNIQUE(ActivityId, OrderIndex)`. Single-answer only (Decision 5).

#### QuizOptions
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| OptionId | INT | PK | Option identifier. |
| QuestionId | INT | FK → QuizQuestions, NOT NULL, owned (cascade) | Parent question. |
| OptionText | NVARCHAR(MAX) | NOT NULL | Choice text. |
| IsCorrect | BIT | NOT NULL | 1 for the correct choice. |
| OrderIndex | INT | NOT NULL | Display order. |

Constraints:
- `UNIQUE(QuestionId, OptionId)`. This is the target of the composite FK in SubmissionAnswers, so an answer can reference only an option belonging to its own question.
- Filtered unique index on `(QuestionId) WHERE IsCorrect = 1`. At most one correct option per question.
- Backend rule: a question must have exactly one correct option before its activity can be Published. SQL Server cannot express "at least one" declaratively without a trigger.

#### TestCases
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| TestCaseId | INT | PK | Test identifier. |
| ActivityId | INT | FK → Activities, NOT NULL, owned (cascade) | Parent coding activity. |
| InputData | NVARCHAR(MAX) | NULL | STDIN. |
| ExpectedOutput | NVARCHAR(MAX) | NOT NULL | Expected STDOUT. |
| OrderIndex | INT | NOT NULL | Display order. |

Constraint: `UNIQUE(ActivityId, OrderIndex)`. All test cases are visible to students (Decision 7).

#### SqlTaskSpecs
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| ActivityId | INT | PK, FK → Activities, owned (cascade) | One-to-one with an SQL activity. |
| SetupScript | NVARCHAR(MAX) | NOT NULL | Sandbox schema and seed data. Runs only in the isolated SQL validator (handoff §9.3). |
| ExpectedResult | NVARCHAR(MAX) | NOT NULL, CHECK (ISJSON(ExpectedResult) = 1) | Expected result set as JSON (Decision 12). |

Backend rule: only activities with ActivityType = 'SQL' may have a row here.

### 4.4 D4: Submission Data

#### PracticeDrafts
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| DraftId | INT | PK | Draft identifier. |
| StudentId | INT | FK → Users, NOT NULL | Owner. |
| ActivityId | INT | FK → Activities, NOT NULL | Activity being worked on. |
| Content | NVARCHAR(MAX) | NOT NULL | Current code or SQL text. |
| UpdatedAt | DATETIME2 | NOT NULL | Last save time. |

Constraint: `UNIQUE(StudentId, ActivityId)`. One current draft per student per activity. Saving a draft never creates a Submission.

#### Submissions
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| SubmissionId | INT | PK | Submission identifier. |
| StudentId | INT | FK → Users, NOT NULL | Submitting student. |
| ActivityId | INT | FK → Activities, NOT NULL | Activity attempted. |
| AttemptNo | INT | NOT NULL, CHECK (> 0) | Attempt number for this student and activity (FR3.3). |
| SubmittedContent | NVARCHAR(MAX) | NULL | Code or SQL text. NULL for Quiz. |
| Status | NVARCHAR(20) | NOT NULL, CHECK in ('Submitted','Graded') | Grading state. |
| Score | DECIMAL(5,2) | NULL, CHECK (Score >= 0), required when Status = 'Graded' | Final score (auto or manual). |
| Feedback | NVARCHAR(MAX) | NULL | Faculty feedback. |
| GradedBy | INT | FK → Users, NULL | Faculty grader. NULL = automated grade. |
| GradedAt | DATETIME2 | NULL | Grading time. |
| SubmittedAt | DATETIME2 | NOT NULL | Submission time. |

Constraints:
- `UNIQUE(ActivityId, StudentId, AttemptNo)`. The backend assigns the next number inside a transaction; the constraint guards against races.
- Students cannot write Score, Feedback, GradedBy, or GradedAt (backend RBAC, NFR Security).
- Backend rule: GradedBy must be the faculty member assigned (FacultyAssignments) to the student's batch and the activity's subject.

#### SubmissionAnswers
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| SubmissionId | INT | PK (composite), FK → Submissions, owned (cascade) | Parent submission. |
| QuestionId | INT | PK (composite), FK → QuizQuestions, NOT NULL | Question answered. |
| OptionId | INT | NOT NULL, composite FK (QuestionId, OptionId) → QuizOptions(QuestionId, OptionId) | Single chosen option. |

Constraints:
- Primary key `(SubmissionId, QuestionId)`. One answer per question per attempt (single-answer integrity).
- The composite FK guarantees the chosen option belongs to the same question.
- No surrogate key, no TextResponse (Decision 6).

#### TestCaseResults
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| ResultId | INT | PK | Result identifier. |
| SubmissionId | INT | FK → Submissions, NOT NULL, owned (cascade) | Parent submission. |
| TestCaseId | INT | FK → TestCases, NOT NULL, NO ACTION | Test evaluated. |
| Passed | BIT | NOT NULL | 1 if output matched. |
| ActualOutput | NVARCHAR(MAX) | NULL | Captured STDOUT, truncated to the output-size limit. |
| ExecutionTimeMs | INT | NULL, CHECK (>= 0) | Measured execution time. |

Constraint: `UNIQUE(SubmissionId, TestCaseId)`.

### 4.5 D5: Analytics Data

#### LearningActivity
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| EventId | BIGINT | PK | Event identifier. |
| StudentId | INT | FK → Users, NOT NULL | Student concerned. |
| EventType | NVARCHAR(30) | NOT NULL, CHECK in ('LessonViewed','ActivitySubmitted','AIQuery','TabSwitch') | Event kind. |
| LessonId | INT | FK → Lessons, NULL | Set for LessonViewed; optional context for AIQuery. |
| ActivityId | INT | FK → Activities, NULL | Set for ActivitySubmitted and TabSwitch. |
| OccurredAt | DATETIME2 | NOT NULL | Event time. |

Constraints:
- CHECK: LessonViewed requires LessonId; ActivitySubmitted and TabSwitch require ActivityId.
- Students cannot insert or update these rows directly; the backend writes them.
- TabSwitch events are non-punitive audit telemetry (FR3.6, §5.3). They never change scores, lock submissions, or fail students.
- AIQuery events record only that a query happened, with its lesson context. The table has no content column (Decision 10).

#### StudentProgress
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| ProgressId | INT | PK | Progress identifier. |
| StudentId | INT | FK → Users, NOT NULL | Student. |
| TopicId | INT | FK → Topics, NOT NULL | Topic measured. |
| AggregateScorePct | DECIMAL(5,2) | NULL, CHECK (0 to 100) | Aggregate topic score from graded submissions (FR5.2). |
| LastUpdatedAt | DATETIME2 | NOT NULL | Last recalculation. |

Constraint: `UNIQUE(StudentId, TopicId)`. Weak-topic identification (FR5.3) compares AggregateScorePct to a system threshold kept in backend configuration.

#### Recommendations
| Attribute | Data Type | Key/Constraint | Description |
|---|---|---|---|
| RecommendationId | INT | PK | Recommendation identifier. |
| StudentId | INT | FK → Users, NOT NULL | Student advised. |
| TopicId | INT | FK → Topics, NOT NULL | Weak topic. |
| ActivityId | INT | FK → Activities, NULL | Suggested practice activity. |
| RuleCode | NVARCHAR(50) | NOT NULL | System rule that produced the suggestion. |
| Reason | NVARCHAR(255) | NOT NULL | Human-readable explanation. |
| CreatedAt | DATETIME2 | NOT NULL | Creation time. |

---

## 5. Integrity and Cascade Behaviour (SQL Server)

**Policy:** Only owned child rows cascade. Everything else is `NO ACTION`, so history cannot be deleted by accident. Retirement uses `Status` (FR4.7).

| Parent → Child | Delete behaviour | Reason |
|---|---|---|
| Lessons → LessonResources | CASCADE | Owned resource. |
| Activities → QuizQuestions | CASCADE | Owned quiz content. |
| Activities → TestCases | CASCADE | Owned test cases. |
| Activities → SqlTaskSpecs | CASCADE | Owned SQL spec. |
| QuizQuestions → QuizOptions | CASCADE | Owned options. |
| Submissions → SubmissionAnswers | CASCADE | Owned answers. |
| Submissions → TestCaseResults | CASCADE | Owned results. |
| QuizQuestions → SubmissionAnswers | NO ACTION | Preserve attempt history. |
| QuizOptions → SubmissionAnswers | NO ACTION | Preserve attempt history. |
| TestCases → TestCaseResults | **NO ACTION** | Avoids multiple cascade paths to TestCaseResults (SQL Server error 1785). |
| Activities → Submissions, PracticeDrafts, Recommendations, LearningActivity | NO ACTION | Preserve history; archive instead. |
| Topics → Lessons, Activities, StudentProgress, Recommendations | NO ACTION | Archive instead. |
| Subjects → Topics, FacultyAssignments | NO ACTION | Archive instead. |
| Batches → Users, FacultyAssignments | NO ACTION | Archive instead. |
| Users → any child | NO ACTION | Suspend or archive instead. |
| Roles → Users | NO ACTION | Roles are fixed. |

Multiple cascade paths check: each table is reachable by cascade through at most one path. TestCaseResults is reached only via Submissions, and Submissions is reached only via NO ACTION links. SubmissionAnswers is reached only via Submissions. QuizOptions is reached only via QuizQuestions. This satisfies the SQL Server rule.

---

## 6. Relationships and Cardinality

| Relationship | Cardinality | Notes |
|---|---|---|
| Roles → Users | 1 : N | Each user has one role. |
| Batches → Users (students) | 1 : N (optional) | A student has at most one batch (Decision 1). |
| Batches ↔ Subjects ↔ Users (faculty) | N : N via FacultyAssignments | One faculty per (batch, subject). A faculty member may hold many. |
| Subjects → Topics | 1 : N | |
| Topics → Lessons | 1 : N | |
| Lessons → LessonResources | 1 : N | Owned. |
| Topics → Activities | 1 : N | |
| Activities → QuizQuestions | 1 : N | Quiz only. |
| QuizQuestions → QuizOptions | 1 : N | Exactly one correct option (filtered unique index plus publish rule). |
| Activities → TestCases | 1 : N | Coding only. |
| Activities → SqlTaskSpecs | 1 : 0..1 | SQL only. |
| Users (student) → PracticeDrafts | 1 : N | One per activity (unique). |
| Activities → PracticeDrafts | 1 : N | |
| Users (student) → Submissions | 1 : N | |
| Activities → Submissions | 1 : N | Attempt numbers unique per student per activity. |
| Users (faculty) → Submissions (GradedBy) | 1 : N, optional | NULL means automated grade. |
| Submissions → SubmissionAnswers | 1 : N | Quiz only. |
| QuizQuestions → SubmissionAnswers | 1 : N | Composite key with OptionId. |
| Submissions → TestCaseResults | 1 : N | Coding only. |
| TestCases → TestCaseResults | 1 : N | |
| Users (student) → LearningActivity | 1 : N | |
| Lessons / Activities → LearningActivity | 1 : N, optional | Context for the event type. |
| Users (student) → StudentProgress | 1 : N | One row per topic (unique). |
| Topics → StudentProgress | 1 : N | |
| Users (student) → Recommendations | 1 : N | |
| Topics → Recommendations | 1 : N | |
| Activities → Recommendations | 1 : N, optional | Suggested practice. |

---

## 7. Entities Deliberately Excluded

| Candidate | Status | Reason |
|---|---|---|
| Courses | Excluded | Decision 4. Subject → Topic → Lesson only. |
| BatchEnrollments | Excluded | Decision 1. `Users.BatchId`. |
| SubjectEnrollments | Excluded | Students join through batches. |
| AILogs / conversation transcript | Excluded | Decision 10. AI content is ephemeral. AI queries are recorded as event rows with no content. |
| Objectives | Excluded | Decision 8. Column on Lessons. |
| TextResponse / short-answer | Excluded | Decision 6. |
| Multi-select answer table | Excluded | Decision 5. |
| Hidden test cases | Excluded | Decision 7. |
| Expected-result table | Excluded | Decision 12. JSON in SqlTaskSpecs. |
| Rubric table | Excluded | Not in the synopsis. Revisit only if confirmed. |
| Due dates, reminders | Excluded | Not in the synopsis. |
| Lesson-level progress | Excluded | FR5.2 requires topic-level performance. |
| Audit log table for admin actions | Excluded | Not in the synopsis. |
| Microservice databases, auth/token tables | Excluded | Out of scope for V1. |

---

## 8. Open Assumptions (flagged, not blockers unless noted)

1. **Faculty authoring scope.** Topics and Activities are shared across batches. A faculty member may author content for a subject if they hold at least one FacultyAssignments row for that subject. Grading and monitoring are limited to their assigned batch. *Needs owner confirmation.*
2. **Subjects are maintained by the Administrator.** The three V1 subjects are seeded. The Administrator can archive them but cannot add new subjects without a scope change.
3. **PracticeDrafts belongs to Submission Data (D4).** The canonical DFD (`docs/dfd.png`) shows the draft-save flow from 3.0 into D4.
4. **Attempts for Practice activities.** Practice submissions are kept in Submissions for attempt tracking (§5.2). They are not graded (`IsGraded = 0`).

---

## 9. Required Companion Changes

- **DFD canonical export** (done): `docs/dfd.png` (source `docs/dfd.svg`) uses D1-D5 from section 2. Older artifacts (`docs/DFD/DFD.jpeg`, `Synora_DFD.docx`) are kept as historical and are superseded. See `docs/dfd-consistency-audit.md`.
- **Synopsis PDF** names PostgreSQL in §3.3, §4.1, §6.3, §7.4, §8.1, §9.1. The PDF is binary and cannot be edited in place.
- **Synopsis PPTX** (`docs/academic/SYNORA Live Smart Edification PPT.pptx`) names PostgreSQL on slides 1, 5, 6, and 16.
- **README.md** and the SCR-03 prototype SQL option label (done): now Microsoft SQL Server / T-SQL.
- **CLAUDE_HANDOFF.md** §9.1 still lists the old 15-entity design.

---

## 10. ER Diagram

Created (owner-approved). Files:

- `docs/er-diagram.png` is the rendered diagram, grouped by data store D1-D5.
- `docs/er-diagram.svg` is the vector version for printing.
- `docs/er-diagram.mmd` is the editable source (Mermaid `erDiagram` text, the single source of entities, columns and relationships).
- `docs/tools/gen_er.py` regenerates the SVG from the `.mmd`. `docs/tools/check_er.py` verifies the `.mmd` against sections 2 and 4 of this file.
- `docs/er-consistency-audit.md` records the Database / DFD / ER audit.
- `docs/er-diagram-academic.{mmd,svg,png}` is a simplified presentation variant for the guide (keys and main attributes only), built by `docs/tools/gen_er_academic.py` and checked by `docs/tools/check_er_academic.py`; audit in `docs/er-academic-consistency-audit.md`.
- `docs/er-diagram-chen.{svg,png,json}` is the **Chen-notation ER diagram for the report and presentation** (rectangles = entities, ovals = attributes, diamonds = relationships, 1/N cardinalities), built by `docs/tools/gen_er_chen.py` and checked by `docs/tools/check_er_chen.py`; audit in `docs/er-chen-consistency-audit.md`. The earlier `er-diagram-academic.*` is a table-style variant and is kept.
- `docs/database/ssms-diagram-layout.md` gives the manual table placement for the SSMS Database Diagram (implementation diagram).

The ER diagram introduces no schema change. If this file changes, update the `.mmd` and re-run both tools.

## 11. SQL Server Implementation

- `database/schema.sql` creates database `SynoraV1`, the 20 tables, constraints and indexes, plus the 3 roles and 3 subjects (re-runnable, non-destructive).
- `database/validate_schema.sql` checks the live database against this design and runs rolled-back negative tests.
- `docs/tools/check_sql_schema.py` compares live columns, types and nullability with section 4.
- `docs/database/ssms-setup.md` is the SSMS procedure; `docs/database/sql-server-consistency-audit.md` records the audit.

Every CHECK in the DDL comes from this document. Rules that need other rows (student has role Student, faculty has role Faculty, SQL spec only for SQL activities, `Users.BatchId` only for students) stay in the backend, as stated in sections 5 and 8.
