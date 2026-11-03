# Synora V1: SQL Server Setup in SSMS

Requires SQL Server 2019 or later (developed and run on SQL Server 2022) and SQL Server Management Studio.

## 1. Create the database

`database/schema.sql` creates the database `SynoraV1` itself if it does not exist. To create it by hand instead:

1. Connect to your instance in SSMS.
2. Right-click **Databases > New Database...**, name it `SynoraV1`, click OK.

## 2. Run the schema

1. **File > Open > File...** and open `database/schema.sql`.
2. Press **F5** (Execute). It switches to `SynoraV1`, creates the 20 tables, constraints and indexes, and inserts the 3 roles and 3 subjects.
3. Messages should show no errors. Running it again is safe: existing objects are skipped and nothing is dropped.

## 3. Run the validation

1. Open `database/validate_schema.sql` and make sure the database dropdown shows `SynoraV1`.
2. Press **F5**.
3. Expected result: the first result grid (failures) is empty, the second shows every category with `Failed = 0`, and the last row says `PASS`.

The negative tests run inside a transaction that is rolled back, so no test data remains.

## 4. Confirm tables and relationships

In Object Explorer, refresh **SynoraV1 > Tables**: 20 tables. Or run:

```sql
SELECT COUNT(*) AS Tables      FROM sys.tables;        -- 20
SELECT COUNT(*) AS ForeignKeys FROM sys.foreign_keys;  -- 35
```

## 5. Create the Database Diagram

1. Expand **SynoraV1**, right-click **Database Diagrams > New Database Diagram**.
2. If SSMS asks to create diagram support objects, click **Yes**.
3. In the Add Table dialog, select all 20 tables (click the first, Shift+click the last), click **Add**, then **Close**.
4. Use right-click on the canvas > **Arrange Tables** (or arrange by D1-D5 groups by hand): D1 Roles, Users, Batches, FacultyAssignments; D2 Subjects, Topics, Lessons, LessonResources; D3 Activities, QuizQuestions, QuizOptions, TestCases, SqlTaskSpecs; D4 Submissions, SubmissionAnswers, TestCaseResults, PracticeDrafts; D5 LearningActivity, StudentProgress, Recommendations.
5. Check that all 35 relationship lines appear (35 foreign keys).

## 6. Save the diagram

1. Press **Ctrl+S** and name it `Synora_V1_Diagram`. The diagram is stored inside the database.
2. For the report, right-click the canvas > **Copy Diagram to Clipboard** (or use a screenshot) and paste into the document.

The SSMS diagram is the implementation-level view. The design-level views remain `docs/er-diagram.png` and `docs/er-diagram-academic.png`.
