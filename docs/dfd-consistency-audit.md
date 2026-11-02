# Synopsis / DFD / Database Consistency Audit

Audited against: `docs/dfd.png` (canonical, source `docs/dfd.svg`), `docs/database/database-design.md`, `docs/academic/synopsis/...Official Synopsis Draft V1.pdf`, `Synora_DFD.docx`, `docs/DFD/DFD.jpeg`.

## Canonical DFD choice

`docs/dfd.png` is a new Level 1 diagram. It keeps the process structure of the whiteboard photo (`docs/DFD/DFD.jpeg`), because it is the only older artifact with a User & Access process, which the schema needs for Administrator batch, enrolment and faculty-assignment flows into D1. Its data stores are the D1-D5 names from `database-design.md` section 2 (the `Synora_DFD.docx` store names).

| Older artifact | Problem | Status |
|---|---|---|
| `docs/DFD/DFD.jpeg` | 4 stores (D3 "Submissions & Grades" mixes assessment and submission data, D4 is analytics), no draft-save flow | Kept, historical |
| `Synora_DFD.docx` | 5 stores right, but processes are the synopsis modules, no Administrator-to-D1 batch flow, no draft-save, inconsistent numbering across Level 1 and 2 | Kept, historical |
| `Hand_Drawable_Level1_DFD.png` | Not present in the repository or working tree | Not found |

## Process mapping

| DFD process | Synopsis module(s) |
|---|---|
| 1.0 User & Access Mgmt | Module 4 (RBAC, batches, enrolment, assignments) |
| 2.0 Course & Content Mgmt | Module 4 (course and assessment authoring) |
| 3.0 Interactive Learning & Practical Sandbox | Modules 1 and 2 |
| 4.0 Assessment & Assignment Mgmt | Module 3 |
| 5.0 Learning Analytics & Recommendation | Module 5 |

## Store and entity coverage (20 of 20)

| Store | Entities | Written by | Read by |
|---|---|---|---|
| D1 | Roles, Users, Batches, FacultyAssignments | 1.0 | 1.0, 2.0 (assignment check) |
| D2 | Subjects, Topics, Lessons, LessonResources | 2.0 | 2.0, 3.0 |
| D3 | Activities, QuizQuestions, QuizOptions, TestCases, SqlTaskSpecs | 2.0 | 3.0, 4.0 |
| D4 | Submissions, SubmissionAnswers, TestCaseResults, PracticeDrafts | 3.0 (drafts, practice runs), 4.0 | 3.0 (restore draft), 4.0, 5.0 |
| D5 | LearningActivity, StudentProgress, Recommendations | 5.0 | 5.0 |

## Locked decisions represented

- Draft-save flow 3.0 to D4 and restore D4 to 3.0 (PracticeDrafts).
- Administrator batch, enrolment and faculty assignment flows into D1 via 1.0.
- Assessment flow: 2.0 authors activities, questions and test cases into D3; 4.0 reads them, runs test cases on the Execution Service, writes results to D4.
- Analytics flow: 3.0 and 4.0 feed 5.0, which writes D5 and reports to Student and Faculty.
- Targeted learning feedback loop: 5.0 to 3.0 "Targeted recommendations".
- AI Service has no store; no transcript persisted (note on diagram).
- Hidden test cases, multi-select and open text are not drawn (out of V1).

## Remaining inconsistencies

1. Synopsis PDF (labelled Draft V1) names PostgreSQL in sections 3.3, 4.1, 6.3, 7.4, 8.1, 9.1. No editable source was found (PDF only). It needs re-export from its source document.
2. PPTX names PostgreSQL on slides 1, 5, 6, 16. It is a binary Office file and was not edited.
3. `CLAUDE_HANDOFF.md` (untracked) still describes the old 15-entity design and PostgreSQL. It is a historical handoff, not modified.
4. `Synora_DFD.docx` and `docs/DFD/DFD.jpeg` are now superseded. Anyone submitting the DFD academically should use `docs/dfd.png`.
5. Synopsis modules do not map one-to-one to DFD processes (table above). The synopsis section 5.6 module-integration wording should be checked against this when the synopsis is re-issued.
6. Level 0 and Level 2 diagrams do not exist in canonical form. Only Level 1 is done.
