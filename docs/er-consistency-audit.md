# ER Consistency Audit (Database Design / DFD / ER Diagram)

Scope: `docs/database/database-design.md` (source of truth), `docs/dfd.png` (`docs/dfd.svg`), `docs/er-diagram.png` (`docs/er-diagram.mmd`).

## Method

- `python docs/tools/check_er.py` compares every entity, attribute name and order, data type, and PK/FK tag in the `.mmd` against the section 4 tables, and checks store membership against section 2. Result: 20/20 entities, all attributes match, OK.
- Relationships in the `.mmd` (35) were compared by hand to section 6 (26 rows) and the section 5 cascade table.
- Store labels and entity placement were compared with the DFD data stores D1-D5.

## Results

| Check | Result |
|---|---|
| Entity coverage, database vs ER | 20 of 20, no extras, no omissions |
| Attributes, types, PK/FK tags | Match (automated) |
| D1-D5 mapping, database vs ER | Match: ER bands are D1 (4), D2 (4), D3 (5), D4 (4), D5 (3) |
| D1-D5 naming, database vs DFD vs ER | Identical: User Data, Course Content, Assessment Data, Submission Data, Analytics Data |
| Cardinalities vs section 6 | All 26 rows present with the same direction and optionality (e.g. Batches 0..1 to Users, Activities 1 to 0..1 SqlTaskSpecs, GradedBy optional, LearningActivity and Recommendations activity links optional) |
| Extra ER relationships | Audit/ownership FKs defined in section 4 columns but not tabulated in section 6: Users to Batches (CreatedBy), Users to FacultyAssignments (FacultyId, AssignedBy), Users to Topics and Activities (CreatedBy). Batches and Subjects to FacultyAssignments are the decomposed N:N row of section 6 |
| Cascade behaviour (section 5) | Owned children labelled "owns (cascade)": LessonResources, QuizQuestions, QuizOptions, TestCases, SqlTaskSpecs, SubmissionAnswers, TestCaseResults. All other edges are NO ACTION. TestCases to TestCaseResults is correctly not cascading |
| Locked decisions | No BatchEnrollments, Course, hidden-test, open-text or transcript entity is present. Student has at most one batch via `Users.BatchId` |
| DFD to ER, flows | D4 holds PracticeDrafts (draft save flow 3.0 to D4), D5 holds Recommendations (5.0 to 3.0 feedback loop), D3 holds TestCases and SqlTaskSpecs (4.0 and 3.0 read). Each DFD store has the same entities as the ER band |

## Findings

1. No contradiction between the three artifacts; the schema was not changed.
2. The DFD is process-level, so it cannot be compared entity by entity. It is compared at the data-store level only.
3. Section 6 omits the audit FKs listed above, which section 4 defines. They are drawn in the ER diagram and are consistent with section 4. Optional follow-up: add them to section 6 (not done here; no schema or content change).
4. Dashed lines in the ER diagram mark ownership and audit FKs to Users.

## Remaining documentation inconsistencies (not in scope here)

- Synopsis PDF names PostgreSQL (sections 3.3, 4.1, 6.3, 7.4, 8.1, 9.1) and is still marked Draft. It is binary; the editable source is not in the repository.
- Synopsis PPTX names PostgreSQL on slides 1, 5, 6 and 16.
- `CLAUDE_HANDOFF.md` (untracked) still lists the old 15-entity design and PostgreSQL.
- `docs/dfd-consistency-audit.md` mentions PostgreSQL only as a historical reference.

## Readiness

The foundation is ready for SQL DDL. All open items above are documentation only.
