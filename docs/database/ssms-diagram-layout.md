# SSMS Database Diagram: Placement Guide

The SSMS diagram is the **implementation diagram** of `SynoraV1` (tables, columns, PK/FK lines). It is not the academic ER diagram (`docs/er-diagram-chen.png`). SSMS stores diagrams in `sysdiagrams` in its own binary format, so arrange it by hand in SSMS; nothing here changes the schema.

Steps: SSMS > `SynoraV1` > Database Diagrams > New Database Diagram > add all 20 tables > drag as below > right-click the canvas > *Table View > Standard* (or *Column Names*) > save as `Synora V1 Database Diagram`. Do not use *Arrange Tables*; it tangles the layout.

## Grid (rows top to bottom, tables left to right; about one table-width between columns)

```
Row 1  D1 User Data        Roles ── Users ── Batches
Row 2                              FacultyAssignments      (under Users, between Users and Subjects)
Row 3  D2 Course Content   Subjects ── Topics ── Lessons ── LessonResources
Row 4  D3 Assessment       SqlTaskSpecs   Activities ── QuizQuestions ── QuizOptions
Row 5                      TestCases      (under Activities, left of QuizQuestions)
Row 6  D4 Submissions      PracticeDrafts   Submissions ── SubmissionAnswers
Row 7                      TestCaseResults  (under Submissions)
Row 8  D5 Analytics        LearningActivity   StudentProgress   Recommendations
```

## Why these positions

| Table | Place | Reason |
|---|---|---|
| Users | centre of row 1 | hub: 13 relationships (Roles, Batches, FacultyAssignments, Topics, Activities, PracticeDrafts, Submissions, LearningActivity, StudentProgress, Recommendations) |
| FacultyAssignments | just under Users/Batches | links Batches, Subjects, Users; keeps its three lines short |
| Subjects to LessonResources | one horizontal chain | follows the Subject, Topic, Lesson, Resource hierarchy |
| Activities | below Topics | its parent is Topics; it is the hub of D3 |
| QuizQuestions / QuizOptions | right of Activities | chain Activity, Question, Option |
| TestCases / SqlTaskSpecs | left of Activities | Activity children; leaves the right side free |
| Submissions | below Activities | child of Activities and Users |
| SubmissionAnswers | right of Submissions, under QuizOptions | needs lines to QuizQuestions and QuizOptions (composite FK) |
| TestCaseResults | under Submissions, below TestCases | lines to Submissions and TestCases |
| D5 tables | bottom row | only receive keys from Users, Topics, Lessons, Activities |

Leave a clear gap (about one table height) between the five groups. Expect long lines from `Users` down to D4/D5; that reflects the real foreign keys and is not a schema problem.

## Check after arranging

20 tables visible, 35 relationship lines, no table sitting on a line, no extra tables (`sysdiagrams` is not shown). Do not change any table to tidy the picture.
