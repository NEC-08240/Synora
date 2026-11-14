/* =============================================================================
   Synora V1 - schema validation (read-only checks + rolled-back negative tests)
   Run AFTER database/schema.sql against the SAME database; the target is required:
     sqlcmd -S localhost -E -C -b -v DB_NAME=<db> -i databasealidate_schema.sql

   Part 1 compares the live catalog with the locked design: tables, PKs, FKs
   (with ON DELETE action), UNIQUE constraints, CHECK constraints, indexes, and
   flags any unexpected object.
   Part 2 runs negative tests inside a transaction that is always rolled back,
   so no test data is left behind.

   Output: one row per failed check, then a PASS/FAIL summary.
   ============================================================================= */

:on error exit
SET NOCOUNT ON;
SET QUOTED_IDENTIFIER ON;
GO

IF N'$(DB_NAME)' LIKE N'%[^A-Za-z0-9_]%' OR N'$(DB_NAME)' = N''
   OR N'$(DB_NAME)' LIKE N'%[_]Sandbox%' COLLATE Latin1_General_CI_AS
BEGIN
    RAISERROR(N'DB_NAME missing/invalid (letters, digits, _ only; not a *_Sandbox database). Run in SQLCMD mode with -v DB_NAME=<db>. Stopping.', 16, 1);
    SET NOEXEC ON;  -- plain SSMS ignores :on error exit; this skips every later batch
END
GO

USE [$(DB_NAME)];
GO

IF OBJECT_ID(N'tempdb..#Result') IS NOT NULL DROP TABLE #Result;
CREATE TABLE #Result (Category NVARCHAR(30), Item NVARCHAR(200), Passed BIT, Detail NVARCHAR(400) NULL);

/* ------------------------------ Expected sets ----------------------------- */

DECLARE @Tables TABLE (Name SYSNAME PRIMARY KEY);
INSERT @Tables VALUES
 (N'Roles'),(N'Users'),(N'Batches'),(N'FacultyAssignments'),
 (N'Subjects'),(N'Topics'),(N'Lessons'),(N'LessonResources'),
 (N'Activities'),(N'QuizQuestions'),(N'QuizOptions'),(N'TestCases'),(N'SqlTaskSpecs'),
 (N'Submissions'),(N'SubmissionAnswers'),(N'TestCaseResults'),(N'PracticeDrafts'),
 (N'LearningActivity'),(N'StudentProgress'),(N'Recommendations');

-- Primary keys: table, ordered key columns
DECLARE @PKs TABLE (TableName SYSNAME PRIMARY KEY, KeyCols NVARCHAR(200));
INSERT @PKs VALUES
 (N'Roles',N'RoleId'),(N'Users',N'UserId'),(N'Batches',N'BatchId'),(N'FacultyAssignments',N'AssignmentId'),
 (N'Subjects',N'SubjectId'),(N'Topics',N'TopicId'),(N'Lessons',N'LessonId'),(N'LessonResources',N'ResourceId'),
 (N'Activities',N'ActivityId'),(N'QuizQuestions',N'QuestionId'),(N'QuizOptions',N'OptionId'),
 (N'TestCases',N'TestCaseId'),(N'SqlTaskSpecs',N'ActivityId'),
 (N'Submissions',N'SubmissionId'),(N'SubmissionAnswers',N'SubmissionId,QuestionId'),
 (N'TestCaseResults',N'ResultId'),(N'PracticeDrafts',N'DraftId'),
 (N'LearningActivity',N'EventId'),(N'StudentProgress',N'ProgressId'),(N'Recommendations',N'RecommendationId');

-- Foreign keys: name, child table, child cols, parent table, parent cols, delete action
DECLARE @FKs TABLE (Name SYSNAME PRIMARY KEY, ChildTable SYSNAME, ChildCols NVARCHAR(100),
                    ParentTable SYSNAME, ParentCols NVARCHAR(100), OnDelete NVARCHAR(20));
INSERT @FKs VALUES
 (N'FK_Users_Roles',N'Users',N'RoleId',N'Roles',N'RoleId',N'NO_ACTION'),
 (N'FK_Users_Batches',N'Users',N'BatchId',N'Batches',N'BatchId',N'NO_ACTION'),
 (N'FK_Batches_Users_CreatedBy',N'Batches',N'CreatedBy',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_Topics_Subjects',N'Topics',N'SubjectId',N'Subjects',N'SubjectId',N'NO_ACTION'),
 (N'FK_Topics_Users_CreatedBy',N'Topics',N'CreatedBy',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_FacultyAssignments_Batches',N'FacultyAssignments',N'BatchId',N'Batches',N'BatchId',N'NO_ACTION'),
 (N'FK_FacultyAssignments_Subjects',N'FacultyAssignments',N'SubjectId',N'Subjects',N'SubjectId',N'NO_ACTION'),
 (N'FK_FacultyAssignments_Users_Faculty',N'FacultyAssignments',N'FacultyId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_FacultyAssignments_Users_AssignedBy',N'FacultyAssignments',N'AssignedBy',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_Lessons_Topics',N'Lessons',N'TopicId',N'Topics',N'TopicId',N'NO_ACTION'),
 (N'FK_LessonResources_Lessons',N'LessonResources',N'LessonId',N'Lessons',N'LessonId',N'CASCADE'),
 (N'FK_Activities_Topics',N'Activities',N'TopicId',N'Topics',N'TopicId',N'NO_ACTION'),
 (N'FK_Activities_Users_CreatedBy',N'Activities',N'CreatedBy',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_QuizQuestions_Activities',N'QuizQuestions',N'ActivityId',N'Activities',N'ActivityId',N'CASCADE'),
 (N'FK_QuizOptions_QuizQuestions',N'QuizOptions',N'QuestionId',N'QuizQuestions',N'QuestionId',N'CASCADE'),
 (N'FK_TestCases_Activities',N'TestCases',N'ActivityId',N'Activities',N'ActivityId',N'CASCADE'),
 (N'FK_SqlTaskSpecs_Activities',N'SqlTaskSpecs',N'ActivityId',N'Activities',N'ActivityId',N'CASCADE'),
 (N'FK_PracticeDrafts_Users_Student',N'PracticeDrafts',N'StudentId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_PracticeDrafts_Activities',N'PracticeDrafts',N'ActivityId',N'Activities',N'ActivityId',N'NO_ACTION'),
 (N'FK_Submissions_Users_Student',N'Submissions',N'StudentId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_Submissions_Activities',N'Submissions',N'ActivityId',N'Activities',N'ActivityId',N'NO_ACTION'),
 (N'FK_Submissions_Users_GradedBy',N'Submissions',N'GradedBy',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_SubmissionAnswers_Submissions',N'SubmissionAnswers',N'SubmissionId',N'Submissions',N'SubmissionId',N'CASCADE'),
 (N'FK_SubmissionAnswers_QuizQuestions',N'SubmissionAnswers',N'QuestionId',N'QuizQuestions',N'QuestionId',N'NO_ACTION'),
 (N'FK_SubmissionAnswers_QuizOptions_Question_Option',N'SubmissionAnswers',N'QuestionId,OptionId',N'QuizOptions',N'QuestionId,OptionId',N'NO_ACTION'),
 (N'FK_TestCaseResults_Submissions',N'TestCaseResults',N'SubmissionId',N'Submissions',N'SubmissionId',N'CASCADE'),
 (N'FK_TestCaseResults_TestCases',N'TestCaseResults',N'TestCaseId',N'TestCases',N'TestCaseId',N'NO_ACTION'),
 (N'FK_LearningActivity_Users_Student',N'LearningActivity',N'StudentId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_LearningActivity_Lessons',N'LearningActivity',N'LessonId',N'Lessons',N'LessonId',N'NO_ACTION'),
 (N'FK_LearningActivity_Activities',N'LearningActivity',N'ActivityId',N'Activities',N'ActivityId',N'NO_ACTION'),
 (N'FK_StudentProgress_Users_Student',N'StudentProgress',N'StudentId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_StudentProgress_Topics',N'StudentProgress',N'TopicId',N'Topics',N'TopicId',N'NO_ACTION'),
 (N'FK_Recommendations_Users_Student',N'Recommendations',N'StudentId',N'Users',N'UserId',N'NO_ACTION'),
 (N'FK_Recommendations_Topics',N'Recommendations',N'TopicId',N'Topics',N'TopicId',N'NO_ACTION'),
 (N'FK_Recommendations_Activities',N'Recommendations',N'ActivityId',N'Activities',N'ActivityId',N'NO_ACTION');

-- UNIQUE constraints: name, table, ordered columns
DECLARE @UQs TABLE (Name SYSNAME PRIMARY KEY, TableName SYSNAME, KeyCols NVARCHAR(200));
INSERT @UQs VALUES
 (N'UQ_Roles_RoleName',N'Roles',N'RoleName'),
 (N'UQ_Batches_Name',N'Batches',N'Name'),
 (N'UQ_Users_Email',N'Users',N'Email'),
 (N'UQ_Subjects_Title',N'Subjects',N'Title'),
 (N'UQ_Topics_Subject_OrderIndex',N'Topics',N'SubjectId,OrderIndex'),
 (N'UQ_FacultyAssignments_Batch_Subject',N'FacultyAssignments',N'BatchId,SubjectId'),
 (N'UQ_Lessons_Topic_OrderIndex',N'Lessons',N'TopicId,OrderIndex'),
 (N'UQ_LessonResources_Lesson_OrderIndex',N'LessonResources',N'LessonId,OrderIndex'),
 (N'UQ_QuizQuestions_Activity_OrderIndex',N'QuizQuestions',N'ActivityId,OrderIndex'),
 (N'UQ_QuizOptions_Question_Option',N'QuizOptions',N'QuestionId,OptionId'),
 (N'UQ_QuizOptions_Question_OrderIndex',N'QuizOptions',N'QuestionId,OrderIndex'),
 (N'UQ_TestCases_Activity_OrderIndex',N'TestCases',N'ActivityId,OrderIndex'),
 (N'UQ_PracticeDrafts_Student_Activity',N'PracticeDrafts',N'StudentId,ActivityId'),
 (N'UQ_Submissions_Activity_Student_Attempt',N'Submissions',N'ActivityId,StudentId,AttemptNo'),
 (N'UQ_TestCaseResults_Submission_TestCase',N'TestCaseResults',N'SubmissionId,TestCaseId'),
 (N'UQ_StudentProgress_Student_Topic',N'StudentProgress',N'StudentId,TopicId');

DECLARE @CKs TABLE (Name SYSNAME PRIMARY KEY, TableName SYSNAME);
INSERT @CKs VALUES
 (N'CK_Roles_RoleName',N'Roles'),(N'CK_Batches_Status',N'Batches'),(N'CK_Users_Status',N'Users'),
 (N'CK_Subjects_Status',N'Subjects'),(N'CK_Topics_Status',N'Topics'),(N'CK_Lessons_Status',N'Lessons'),
 (N'CK_LessonResources_ResourceType',N'LessonResources'),
 (N'CK_Activities_ActivityType',N'Activities'),(N'CK_Activities_Status',N'Activities'),
 (N'CK_Activities_IsGraded',N'Activities'),(N'CK_Activities_MaxScore',N'Activities'),
 (N'CK_Activities_GradedHasMaxScore',N'Activities'),(N'CK_Activities_TimeLimitMs',N'Activities'),
 (N'CK_QuizQuestions_Points',N'QuizQuestions'),(N'CK_SqlTaskSpecs_ExpectedResult_Json',N'SqlTaskSpecs'),
 (N'CK_Submissions_AttemptNo',N'Submissions'),(N'CK_Submissions_Status',N'Submissions'),
 (N'CK_Submissions_Score',N'Submissions'),(N'CK_Submissions_GradedHasScore',N'Submissions'),
 (N'CK_TestCaseResults_ExecutionTimeMs',N'TestCaseResults'),
 (N'CK_LearningActivity_EventType',N'LearningActivity'),(N'CK_LearningActivity_RequiredContext',N'LearningActivity'),
 (N'CK_StudentProgress_AggregateScorePct',N'StudentProgress');

-- Non-constraint indexes: name, table, is_unique, has filter
DECLARE @IXs TABLE (Name SYSNAME PRIMARY KEY, TableName SYSNAME, IsUnique BIT, IsFiltered BIT);
INSERT @IXs VALUES
 (N'UX_QuizOptions_OneCorrectPerQuestion',N'QuizOptions',1,1),
 (N'IX_Users_RoleId',N'Users',0,0),(N'IX_Users_BatchId',N'Users',0,0),(N'IX_Batches_CreatedBy',N'Batches',0,0),
 (N'IX_FacultyAssignments_SubjectId',N'FacultyAssignments',0,0),(N'IX_FacultyAssignments_FacultyId',N'FacultyAssignments',0,0),
 (N'IX_FacultyAssignments_AssignedBy',N'FacultyAssignments',0,0),(N'IX_Topics_CreatedBy',N'Topics',0,0),
 (N'IX_Activities_TopicId',N'Activities',0,0),(N'IX_Activities_CreatedBy',N'Activities',0,0),
 (N'IX_PracticeDrafts_ActivityId',N'PracticeDrafts',0,0),
 (N'IX_Submissions_StudentId',N'Submissions',0,0),(N'IX_Submissions_GradedBy',N'Submissions',0,0),
 (N'IX_SubmissionAnswers_Question_Option',N'SubmissionAnswers',0,0),(N'IX_TestCaseResults_TestCaseId',N'TestCaseResults',0,0),
 (N'IX_LearningActivity_Student_OccurredAt',N'LearningActivity',0,0),(N'IX_LearningActivity_LessonId',N'LearningActivity',0,0),
 (N'IX_LearningActivity_ActivityId',N'LearningActivity',0,0),(N'IX_StudentProgress_TopicId',N'StudentProgress',0,0),
 (N'IX_Recommendations_StudentId',N'Recommendations',0,0),(N'IX_Recommendations_TopicId',N'Recommendations',0,0),
 (N'IX_Recommendations_ActivityId',N'Recommendations',0,0);

/* ------------------------------ Actual catalog ---------------------------- */

-- ordered, comma-joined column list of a key/index
DECLARE @ActualKeys TABLE (ObjName SYSNAME, TableName SYSNAME, KeyType CHAR(2), KeyCols NVARCHAR(200));
INSERT @ActualKeys
SELECT kc.name, t.name, kc.type,
       STRING_AGG(c.name, N',') WITHIN GROUP (ORDER BY ic.key_ordinal)
FROM sys.key_constraints kc
JOIN sys.tables t ON t.object_id = kc.parent_object_id
JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE t.schema_id = SCHEMA_ID(N'dbo')
GROUP BY kc.name, t.name, kc.type;

DECLARE @ActualFKs TABLE (Name SYSNAME, ChildTable SYSNAME, ChildCols NVARCHAR(100),
                          ParentTable SYSNAME, ParentCols NVARCHAR(100), OnDelete NVARCHAR(20));
INSERT @ActualFKs
SELECT fk.name, ct.name, STRING_AGG(cc.name, N',') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
       pt.name, STRING_AGG(pc.name, N',') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
       fk.delete_referential_action_desc
FROM sys.foreign_keys fk
JOIN sys.tables ct ON ct.object_id = fk.parent_object_id
JOIN sys.tables pt ON pt.object_id = fk.referenced_object_id
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns cc ON cc.object_id = fkc.parent_object_id AND cc.column_id = fkc.parent_column_id
JOIN sys.columns pc ON pc.object_id = fkc.referenced_object_id AND pc.column_id = fkc.referenced_column_id
WHERE ct.schema_id = SCHEMA_ID(N'dbo')
GROUP BY fk.name, ct.name, pt.name, fk.delete_referential_action_desc;

/* --------------------------------- Checks --------------------------------- */

-- Tables: exactly the 20 expected, nothing else
INSERT #Result
SELECT N'Table', e.Name, CASE WHEN t.name IS NULL THEN 0 ELSE 1 END, NULL
FROM @Tables e LEFT JOIN sys.tables t ON t.name = e.Name AND t.schema_id = SCHEMA_ID(N'dbo');
INSERT #Result
SELECT N'Table', t.name, 0, N'unexpected table'
FROM sys.tables t WHERE t.schema_id = SCHEMA_ID(N'dbo') AND t.name NOT IN (SELECT Name FROM @Tables);
INSERT #Result VALUES (N'Table', N'count = 20', CASE WHEN (SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo')) = 20 THEN 1 ELSE 0 END, NULL);

-- Primary keys (name PK_<Table>, exact columns)
INSERT #Result
SELECT N'PrimaryKey', e.TableName, CASE WHEN a.ObjName = N'PK_' + e.TableName AND a.KeyCols = e.KeyCols THEN 1 ELSE 0 END,
       N'expected ' + e.KeyCols + N', found ' + ISNULL(a.KeyCols, N'none')
FROM @PKs e LEFT JOIN @ActualKeys a ON a.TableName = e.TableName AND a.KeyType = 'PK';

-- Foreign keys: columns, referenced columns and delete action; plus unexpected FKs
INSERT #Result
SELECT N'ForeignKey', e.Name,
       CASE WHEN a.Name IS NOT NULL AND a.ChildTable = e.ChildTable AND a.ChildCols = e.ChildCols
             AND a.ParentTable = e.ParentTable AND a.ParentCols = e.ParentCols AND a.OnDelete = e.OnDelete THEN 1 ELSE 0 END,
       CASE WHEN a.Name IS NULL THEN N'missing'
            ELSE N'expected ' + e.ChildCols + N'->' + e.ParentTable + N'(' + e.ParentCols + N') ' + e.OnDelete
               + N'; found ' + a.ChildCols + N'->' + a.ParentTable + N'(' + a.ParentCols + N') ' + a.OnDelete END
FROM @FKs e LEFT JOIN @ActualFKs a ON a.Name = e.Name;
INSERT #Result SELECT N'ForeignKey', Name, 0, N'unexpected foreign key' FROM @ActualFKs WHERE Name NOT IN (SELECT Name FROM @FKs);
INSERT #Result VALUES (N'ForeignKey', N'count = 35', CASE WHEN (SELECT COUNT(*) FROM @ActualFKs) = 35 THEN 1 ELSE 0 END, NULL);

-- Unique constraints
INSERT #Result
SELECT N'Unique', e.Name, CASE WHEN a.ObjName IS NOT NULL AND a.TableName = e.TableName AND a.KeyCols = e.KeyCols THEN 1 ELSE 0 END,
       N'expected ' + e.KeyCols + N', found ' + ISNULL(a.KeyCols, N'missing')
FROM @UQs e LEFT JOIN @ActualKeys a ON a.ObjName = e.Name AND a.KeyType = 'UQ';
INSERT #Result SELECT N'Unique', ObjName, 0, N'unexpected unique constraint'
FROM @ActualKeys WHERE KeyType = 'UQ' AND ObjName NOT IN (SELECT Name FROM @UQs);

-- Check constraints (enabled and trusted)
INSERT #Result
SELECT N'Check', e.Name, CASE WHEN c.name IS NOT NULL AND OBJECT_NAME(c.parent_object_id) = e.TableName
                              AND c.is_disabled = 0 AND c.is_not_trusted = 0 THEN 1 ELSE 0 END,
       CASE WHEN c.name IS NULL THEN N'missing' ELSE NULL END
FROM @CKs e LEFT JOIN sys.check_constraints c ON c.name = e.Name;
INSERT #Result SELECT N'Check', c.name, 0, N'unexpected check constraint'
FROM sys.check_constraints c WHERE c.name NOT IN (SELECT Name FROM @CKs);

-- Supporting + filtered indexes
INSERT #Result
SELECT N'Index', e.Name, CASE WHEN i.name IS NOT NULL AND OBJECT_NAME(i.object_id) = e.TableName
                              AND i.is_unique = e.IsUnique AND i.has_filter = e.IsFiltered THEN 1 ELSE 0 END,
       CASE WHEN i.name IS NULL THEN N'missing' ELSE NULL END
FROM @IXs e LEFT JOIN sys.indexes i ON i.name = e.Name AND i.object_id = OBJECT_ID(N'dbo.' + e.TableName);
INSERT #Result
SELECT N'Index', i.name, 0, N'unexpected index'
FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id AND t.schema_id = SCHEMA_ID(N'dbo')
WHERE i.name IS NOT NULL AND i.is_primary_key = 0 AND i.is_unique_constraint = 0
  AND i.name NOT IN (SELECT Name FROM @IXs);
INSERT #Result
SELECT N'Index', N'UX_QuizOptions_OneCorrectPerQuestion filter', CASE WHEN i.filter_definition LIKE N'%IsCorrect%=%1%' THEN 1 ELSE 0 END, i.filter_definition
FROM sys.indexes i WHERE i.name = N'UX_QuizOptions_OneCorrectPerQuestion' AND i.object_id = OBJECT_ID(N'dbo.QuizOptions');

-- No cascade path may reach the same table twice (SQL Server 1785 rule)
INSERT #Result
SELECT N'CascadePaths', N'no table cascades from Users or Batches', CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END, NULL
FROM @ActualFKs WHERE OnDelete = N'CASCADE' AND ParentTable IN (N'Users', N'Batches', N'Roles', N'Subjects', N'Topics');

-- Reference data
INSERT #Result VALUES (N'ReferenceData', N'Roles = Student, Faculty, Administrator',
    CASE WHEN (SELECT COUNT(*) FROM dbo.Roles WHERE RoleName IN (N'Student', N'Faculty', N'Administrator')) = 3
          AND (SELECT COUNT(*) FROM dbo.Roles) = 3 THEN 1 ELSE 0 END, NULL);
INSERT #Result VALUES (N'ReferenceData', N'Subjects seeded (C, C++, DBMS/SQL)',
    CASE WHEN (SELECT COUNT(*) FROM dbo.Subjects WHERE Title IN (N'C Programming', N'C++ Programming', N'DBMS/SQL')) = 3 THEN 1 ELSE 0 END, NULL);

/* ----------------- Part 2: negative tests (always rolled back) ------------- */
-- Each test inserts fixtures and then attempts one violating statement that MUST fail.
-- Everything runs inside one transaction that is rolled back at the end.

DECLARE @Role INT = (SELECT RoleId FROM dbo.Roles WHERE RoleName = N'Student');
DECLARE @RoleFaculty INT = (SELECT RoleId FROM dbo.Roles WHERE RoleName = N'Faculty');
DECLARE @Subject INT = (SELECT TOP 1 SubjectId FROM dbo.Subjects ORDER BY SubjectId);
DECLARE @Subject2 INT = (SELECT TOP 1 SubjectId FROM dbo.Subjects ORDER BY SubjectId DESC);
DECLARE @Err INT, @Tag NVARCHAR(200);

-- table variable: survives the ROLLBACK, unlike #Result
DECLARE @Neg TABLE (Category NVARCHAR(30), Item NVARCHAR(200), Passed BIT, Detail NVARCHAR(400) NULL);
BEGIN TRAN;
BEGIN TRY
    INSERT dbo.Users (RoleId, Name, Email, PasswordHash) VALUES (@RoleFaculty, N'T Faculty', N'vt-fac@test.invalid', N'x');
    DECLARE @Fac INT = SCOPE_IDENTITY();
    INSERT dbo.Batches (Name, AcademicYear, Status, CreatedBy) VALUES (N'VT Batch', N'2026', N'Active', @Fac);
    DECLARE @Batch INT = SCOPE_IDENTITY();
    INSERT dbo.Users (RoleId, BatchId, Name, Email, PasswordHash) VALUES (@Role, @Batch, N'T Student', N'vt-stu@test.invalid', N'x');
    DECLARE @Stu INT = SCOPE_IDENTITY();
    INSERT dbo.Topics (SubjectId, Title, OrderIndex, Status, CreatedBy) VALUES (@Subject, N'VT Topic', 1, N'Published', @Fac);
    DECLARE @Topic INT = SCOPE_IDENTITY();
    INSERT dbo.Activities (TopicId, Title, Instructions, ActivityType, IsGraded, MaxScore, Status, CreatedBy)
        VALUES (@Topic, N'VT Quiz', N'i', N'Quiz', 1, 10, N'Published', @Fac);
    DECLARE @Act INT = SCOPE_IDENTITY();
    INSERT dbo.QuizQuestions (ActivityId, QuestionText, Points, OrderIndex) VALUES (@Act, N'Q1', 5, 1);
    DECLARE @Q1 INT = SCOPE_IDENTITY();
    INSERT dbo.QuizQuestions (ActivityId, QuestionText, Points, OrderIndex) VALUES (@Act, N'Q2', 5, 2);
    DECLARE @Q2 INT = SCOPE_IDENTITY();
    INSERT dbo.QuizOptions (QuestionId, OptionText, IsCorrect, OrderIndex) VALUES (@Q1, N'A', 1, 1);
    DECLARE @Opt1 INT = SCOPE_IDENTITY();
    INSERT dbo.QuizOptions (QuestionId, OptionText, IsCorrect, OrderIndex) VALUES (@Q2, N'B', 1, 1);
    DECLARE @Opt2 INT = SCOPE_IDENTITY();
    INSERT dbo.Submissions (StudentId, ActivityId, AttemptNo, Status) VALUES (@Stu, @Act, 1, N'Submitted');
    DECLARE @Sub INT = SCOPE_IDENTITY();
    INSERT dbo.FacultyAssignments (BatchId, SubjectId, FacultyId, AssignedBy) VALUES (@Batch, @Subject, @Fac, @Fac);
    INSERT dbo.StudentProgress (StudentId, TopicId) VALUES (@Stu, @Topic);

    -- positive control: a valid answer must succeed
    BEGIN TRY
        INSERT dbo.SubmissionAnswers (SubmissionId, QuestionId, OptionId) VALUES (@Sub, @Q1, @Opt1);
        INSERT @Neg VALUES (N'NegativeTest', N'valid answer accepted', 1, NULL);
    END TRY
    BEGIN CATCH
        INSERT @Neg VALUES (N'NegativeTest', N'valid answer accepted', 0, ERROR_MESSAGE());
    END CATCH;

    -- each statement below must raise the named error; capture whether it did
    DECLARE @Tests TABLE (Id INT IDENTITY, Tag NVARCHAR(200), Sql NVARCHAR(MAX));
    INSERT @Tests (Tag, Sql) VALUES
     (N'option of another question rejected (composite FK)',
      N'INSERT dbo.SubmissionAnswers (SubmissionId,QuestionId,OptionId) VALUES (' + CAST(@Sub AS NVARCHAR(20)) + N',' + CAST(@Q2 AS NVARCHAR(20)) + N',' + CAST(@Opt1 AS NVARCHAR(20)) + N')'),
     (N'second answer to same question rejected (PK)',
      N'INSERT dbo.SubmissionAnswers (SubmissionId,QuestionId,OptionId) VALUES (' + CAST(@Sub AS NVARCHAR(20)) + N',' + CAST(@Q1 AS NVARCHAR(20)) + N',' + CAST(@Opt1 AS NVARCHAR(20)) + N')'),
     (N'duplicate (activity, student, attempt) rejected',
      N'INSERT dbo.Submissions (StudentId,ActivityId,AttemptNo,Status) VALUES (' + CAST(@Stu AS NVARCHAR(20)) + N',' + CAST(@Act AS NVARCHAR(20)) + N',1,N''Submitted'')'),
     (N'duplicate (student, topic) progress rejected',
      N'INSERT dbo.StudentProgress (StudentId,TopicId) VALUES (' + CAST(@Stu AS NVARCHAR(20)) + N',' + CAST(@Topic AS NVARCHAR(20)) + N')'),
     (N'duplicate (batch, subject) faculty assignment rejected',
      N'INSERT dbo.FacultyAssignments (BatchId,SubjectId,FacultyId,AssignedBy) VALUES (' + CAST(@Batch AS NVARCHAR(20)) + N',' + CAST(@Subject AS NVARCHAR(20)) + N',' + CAST(@Fac AS NVARCHAR(20)) + N',' + CAST(@Fac AS NVARCHAR(20)) + N')'),
     (N'second correct option for a question rejected (filtered index)',
      N'INSERT dbo.QuizOptions (QuestionId,OptionText,IsCorrect,OrderIndex) VALUES (' + CAST(@Q1 AS NVARCHAR(20)) + N',N''C'',1,2)'),
     (N'deleting a Topic that has Activities rejected (NO ACTION)',
      N'DELETE dbo.Topics WHERE TopicId = ' + CAST(@Topic AS NVARCHAR(20))),
     (N'graded activity without MaxScore rejected (CHECK)',
      N'INSERT dbo.Activities (TopicId,Title,Instructions,ActivityType,IsGraded,Status,CreatedBy) VALUES (' + CAST(@Topic AS NVARCHAR(20)) + N',N''x'',N''i'',N''Quiz'',1,N''Draft'',' + CAST(@Fac AS NVARCHAR(20)) + N')'),
     (N'ungraded non-Practice activity rejected (CHECK)',
      N'INSERT dbo.Activities (TopicId,Title,Instructions,ActivityType,IsGraded,Status,CreatedBy) VALUES (' + CAST(@Topic AS NVARCHAR(20)) + N',N''x'',N''i'',N''Quiz'',0,N''Draft'',' + CAST(@Fac AS NVARCHAR(20)) + N')'),
     (N'invalid role name rejected (CHECK)',
      N'INSERT dbo.Roles (RoleName) VALUES (N''Hacker'')'),
     (N'non-JSON SQL expected result rejected (CHECK)',
      N'INSERT dbo.SqlTaskSpecs (ActivityId,SetupScript,ExpectedResult) VALUES (' + CAST(@Act AS NVARCHAR(20)) + N',N''s'',N''not json'')'),
     (N'duplicate email rejected',
      N'INSERT dbo.Users (RoleId,Name,Email,PasswordHash) VALUES (' + CAST(@Role AS NVARCHAR(20)) + N',N''d'',N''vt-stu@test.invalid'',N''x'')');

    DECLARE @i INT = 1, @n INT = (SELECT COUNT(*) FROM @Tests), @sql NVARCHAR(MAX);
    WHILE @i <= @n
    BEGIN
        SELECT @Tag = Tag, @sql = Sql FROM @Tests WHERE Id = @i;
        SET @Err = 0;
        BEGIN TRY
            SAVE TRANSACTION sp_test;
            EXEC (@sql);
            ROLLBACK TRANSACTION sp_test;   -- statement succeeded: the rule did not fire
        END TRY
        BEGIN CATCH
            SET @Err = ERROR_NUMBER();
            IF XACT_STATE() = 1 ROLLBACK TRANSACTION sp_test;
        END CATCH;
        INSERT @Neg VALUES (N'NegativeTest', @Tag, CASE WHEN @Err IN (547, 2601, 2627) THEN 1 ELSE 0 END,
                               CASE WHEN @Err = 0 THEN N'statement was accepted' ELSE N'error ' + CAST(@Err AS NVARCHAR(10)) END);
        SET @i += 1;
    END;

    -- cascade test: deleting a Submission removes its answers
    DELETE dbo.Submissions WHERE SubmissionId = @Sub;
    INSERT @Neg VALUES (N'NegativeTest', N'deleting a Submission cascades to its answers',
        CASE WHEN NOT EXISTS (SELECT 1 FROM dbo.SubmissionAnswers WHERE SubmissionId = @Sub) THEN 1 ELSE 0 END, NULL);
END TRY
BEGIN CATCH
    INSERT @Neg VALUES (N'NegativeTest', N'fixture setup', 0, ERROR_MESSAGE());
END CATCH;
IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;   -- leave no test data behind
INSERT #Result SELECT * FROM @Neg;

INSERT #Result VALUES (N'NegativeTest', N'no test data persisted',
    CASE WHEN NOT EXISTS (SELECT 1 FROM dbo.Users WHERE Email LIKE N'vt-%@test.invalid') THEN 1 ELSE 0 END, NULL);

/* --------------------------------- Report --------------------------------- */

SELECT Category, Item, Detail FROM #Result WHERE Passed = 0 ORDER BY Category, Item;

SELECT Category, COUNT(*) AS Checks, SUM(CAST(Passed AS INT)) AS Passed, COUNT(*) - SUM(CAST(Passed AS INT)) AS Failed
FROM #Result GROUP BY Category ORDER BY Category;

SELECT CASE WHEN EXISTS (SELECT 1 FROM #Result WHERE Passed = 0) THEN N'FAIL' ELSE N'PASS' END AS Overall,
       COUNT(*) AS TotalChecks FROM #Result;
GO

IF EXISTS (SELECT 1 FROM #Result WHERE Passed = 0) THROW 50002, N'Schema validation FAILED (see failures above)', 1;  -- non-zero sqlcmd exit with -b
GO
