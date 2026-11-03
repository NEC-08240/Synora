# SQL Server Consistency Audit

Chain checked: database design, ER (technical and academic), DFD, SQL Server DDL.
Files: `docs/database/database-design.md`, `docs/er-diagram.mmd`, `docs/er-diagram-academic.mmd`, `docs/dfd.png`, `database/schema.sql`.

## What was actually run

| Kind | Done? | Detail |
|---|---|---|
| Static check of DDL against design | Yes | `docs/tools/check_sql_schema.py` reads `database-design.md` section 4 and the live catalog. |
| Execution on a real SQL Server | Yes | SQL Server 2022 Developer, instance `localhost\SQL2022`, in a throwaway database `SynoraV1_ScratchTest` created from `database/schema.sql` with the name substituted, then dropped. |
| Re-run (idempotence) | Yes | `schema.sql` run twice with no errors and identical counts. |
| `validate_schema.sql` | Yes | 157 checks, all PASS (against the scratch database). It was also shown to fail when the filtered index was dropped. |
| Run in SSMS itself | **No** | Scripts were run with `sqlcmd`. They use plain T-SQL and `GO` batches, so SSMS should behave the same, but SSMS was not used. |
| `SynoraV1` on the owner's server | **No** | Not created; the owner runs `ssms-setup.md`. |

## Results

| Check | Design | ER | DDL (live) | Result |
|---|---|---|---|---|
| Entities / tables | 20 | 20 | 20 | Match; no extra tables |
| D1-D5 mapping | section 2 | store bands | table list in `schema.sql` section headers | Match (D1 4, D2 4, D3 5, D4 4, D5 3) |
| Table names | section 4 | same | same | Match |
| Columns, order, types, nullability | section 4 | same | 123 columns | Match (`check_sql_schema.py`: OK) |
| Primary keys | 20 | 20 | 20 (names `PK_<Table>`) | Match; `SubmissionAnswers` is composite `(SubmissionId, QuestionId)` |
| Foreign keys / relationships | 35 | 35 | 35 | Match by name, columns, parent and delete action |
| ON DELETE | section 5 | n/a | 7 CASCADE, 28 NO ACTION | Match section 5 |
| UNIQUE constraints | section 4 | notes | 16 | Match, including the locked ones below |
| CHECK constraints | section 4 | notes | 23 | Match; all enabled and trusted |
| Supporting indexes | n/a | n/a | 1 filtered unique + 21 FK indexes | Present |

### Locked integrity rules

| Rule | Implemented as | Tested by negative test |
|---|---|---|
| Option must belong to the question | `UQ_QuizOptions_Question_Option` + composite FK `FK_SubmissionAnswers_QuizOptions_Question_Option` | Yes, rejected |
| One answer per question per attempt | PK `(SubmissionId, QuestionId)` | Yes, rejected |
| At most one correct option per question | filtered unique index `UX_QuizOptions_OneCorrectPerQuestion` (`WHERE IsCorrect = 1`) | Yes, rejected |
| `UNIQUE(ActivityId, StudentId, AttemptNo)` | `UQ_Submissions_Activity_Student_Attempt` | Yes, rejected |
| `UNIQUE(StudentId, TopicId)` progress | `UQ_StudentProgress_Student_Topic` | Yes, rejected |
| `UNIQUE(BatchId, SubjectId)` faculty assignment | `UQ_FacultyAssignments_Batch_Subject` | Yes, rejected |
| NO ACTION where locked | e.g. Topic with Activities cannot be deleted | Yes, rejected |
| Owned children cascade | Submission delete removes its answers | Yes |
| SQL expected result is JSON | `CK_SqlTaskSpecs_ExpectedResult_Json` (`ISJSON`) | Yes, rejected |
| Graded needs `MaxScore`; non-Practice must be graded | `CK_Activities_GradedHasMaxScore`, `CK_Activities_IsGraded` | Yes, rejected |
| No multiple cascade paths | `TestCaseResults -> TestCases` is NO ACTION; SQL Server accepted the schema (no error 1785) | Checked in catalog |

### Rules left to the backend (not enforceable by plain constraints)

Per design sections 5 and 8: a student's `BatchId` only for role Student; `FacultyAssignments.FacultyId` must be a Faculty user; `SqlTaskSpecs` only for SQL activities; a quiz question needs at least one option and exactly one correct option; `Submissions.AttemptNo` sequencing; lesson/topic published-state visibility.

## SQL Server compatibility notes

- Types used: `INT`, `BIGINT`, `BIT`, `DECIMAL(5,2)`, `NVARCHAR(n/MAX)`, `DATETIME2`. No PostgreSQL syntax.
- The filtered index needs `SET QUOTED_IDENTIFIER ON`. SSMS has it on by default; the script sets it explicitly (the first test run with `sqlcmd` failed without it, error 1934, and was fixed).
- `Users` and `Batches` reference each other, so `Batches.CreatedBy` is added by `ALTER TABLE` after `Users` exists.
- Defaults use `SYSUTCDATETIME()` (UTC).

## Contradictions found

None. No entity, column, relationship or cardinality was added, removed or changed.

## PostgreSQL references

| Location | Status |
|---|---|
| `README.md`, `prototypes/scr-03-interactive-learning/index.html` | Already corrected earlier on this branch (SQL Server / T-SQL) |
| `docs/database/database-design.md` section 9 | Describes the stale external documents; intentional |
| `docs/dfd-consistency-audit.md`, `docs/er-consistency-audit.md` | Historical audit notes about the same external documents; intentional |
| `docs/academic/` synopsis PDF and PPTX | Binary, no editable source in the repo; not modified |
| `CLAUDE_HANDOFF.md` (untracked) | Historical; its text marks PostgreSQL as superseded; not modified |
| `.claude/worktrees/retire-agent-bridge/...` | Untracked agent worktree copy of the prototype; not part of the repo |

## Remaining owner items

1. Re-export the synopsis PDF and PPTX from their editable sources with Microsoft SQL Server and no Draft label.
2. Run `database/schema.sql` and `database/validate_schema.sql` in SSMS on the real instance, then build and save the Database Diagram (`ssms-setup.md`).
