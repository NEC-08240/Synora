/* =============================================================================
   Synora V1 - Microsoft SQL Server (T-SQL) schema
   Source of truth: docs/database/database-design.md (20 entities, D1-D5)
   Target: SQL Server 2019+ (developed and executed on SQL Server 2022)

   How to run (SQLCMD mode; the target database is REQUIRED, there is no default):
     sqlcmd -S localhost -E -C -b -v DB_NAME=SynoraV1 -i database\schema.sql
   In SSMS enable Query > SQLCMD Mode and add `:setvar DB_NAME <name>` first.
   It creates the database $(DB_NAME) if missing, then the 20 tables,
   constraints and indexes. Use a throwaway name (e.g. SynoraScratch) to
   experiment; never point experiments at SynoraV1 or any *_Sandbox database.
   Re-runnable: every object is created only if it does not already exist, and
   nothing is dropped. It never drops or alters existing data.

   Constraint naming: PK_<Table>, UQ_<Table>_<Cols>, FK_<Child>_<Parent|Role>,
   CK_<Table>_<Rule>, DF_<Table>_<Col>, IX_<Table>_<Cols>, UX_<Table>_<Rule>.
   Delete behaviour: only owned child rows CASCADE (design section 5);
   everything else is NO ACTION.
   ============================================================================= */

:on error exit
SET NOCOUNT ON;
SET QUOTED_IDENTIFIER ON;   -- required by the filtered index (sqlcmd defaults to OFF; SSMS to ON)
GO

IF N'$(DB_NAME)' LIKE N'%[^A-Za-z0-9_]%' OR N'$(DB_NAME)' = N''
   OR N'$(DB_NAME)' LIKE N'%[_]Sandbox%' COLLATE Latin1_General_CI_AS
BEGIN
    RAISERROR(N'DB_NAME missing/invalid (letters, digits, _ only; not a *_Sandbox database). Run in SQLCMD mode with -v DB_NAME=<db>. Stopping.', 16, 1);
    SET NOEXEC ON;  -- plain SSMS ignores :on error exit; this skips every later batch
END
GO

IF DB_ID(N'$(DB_NAME)') IS NULL
    CREATE DATABASE [$(DB_NAME)];
GO

USE [$(DB_NAME)];
GO

/* ------------------------------ D1 User Data ------------------------------ */

IF OBJECT_ID(N'dbo.Roles', N'U') IS NULL
CREATE TABLE dbo.Roles (
    RoleId      INT IDENTITY(1,1) NOT NULL,
    RoleName    NVARCHAR(30)  NOT NULL,
    Description NVARCHAR(255) NULL,
    CONSTRAINT PK_Roles PRIMARY KEY (RoleId),
    CONSTRAINT UQ_Roles_RoleName UNIQUE (RoleName),
    CONSTRAINT CK_Roles_RoleName CHECK (RoleName IN (N'Student', N'Faculty', N'Administrator'))
);
GO

IF OBJECT_ID(N'dbo.Batches', N'U') IS NULL
CREATE TABLE dbo.Batches (
    BatchId      INT IDENTITY(1,1) NOT NULL,
    Name         NVARCHAR(100) NOT NULL,
    AcademicYear NVARCHAR(20)  NOT NULL,
    Status       NVARCHAR(20)  NOT NULL,
    CreatedBy    INT           NOT NULL,   -- FK to Users added below (Users also references Batches)
    CreatedAt    DATETIME2     NOT NULL CONSTRAINT DF_Batches_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Batches PRIMARY KEY (BatchId),
    CONSTRAINT UQ_Batches_Name UNIQUE (Name),
    CONSTRAINT CK_Batches_Status CHECK (Status IN (N'Active', N'Archived'))
);
GO

IF OBJECT_ID(N'dbo.Users', N'U') IS NULL
CREATE TABLE dbo.Users (
    UserId       INT IDENTITY(1,1) NOT NULL,
    RoleId       INT           NOT NULL,
    BatchId      INT           NULL,       -- students only; enforced by backend
    Name         NVARCHAR(100) NOT NULL,
    Email        NVARCHAR(255) NOT NULL,
    PasswordHash NVARCHAR(255) NOT NULL,
    Status       NVARCHAR(20)  NOT NULL CONSTRAINT DF_Users_Status DEFAULT N'Active',
    CreatedAt    DATETIME2     NOT NULL CONSTRAINT DF_Users_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Users PRIMARY KEY (UserId),
    CONSTRAINT UQ_Users_Email UNIQUE (Email),
    CONSTRAINT CK_Users_Status CHECK (Status IN (N'Active', N'Suspended', N'Archived')),
    CONSTRAINT FK_Users_Roles   FOREIGN KEY (RoleId)  REFERENCES dbo.Roles (RoleId),
    CONSTRAINT FK_Users_Batches FOREIGN KEY (BatchId) REFERENCES dbo.Batches (BatchId)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_Batches_Users_CreatedBy')
ALTER TABLE dbo.Batches ADD CONSTRAINT FK_Batches_Users_CreatedBy
    FOREIGN KEY (CreatedBy) REFERENCES dbo.Users (UserId);
GO

/* ---------------------------- D2 Course Content --------------------------- */

IF OBJECT_ID(N'dbo.Subjects', N'U') IS NULL
CREATE TABLE dbo.Subjects (
    SubjectId   INT IDENTITY(1,1) NOT NULL,
    Title       NVARCHAR(150) NOT NULL,
    Description NVARCHAR(MAX) NULL,
    Status      NVARCHAR(20)  NOT NULL,
    CreatedAt   DATETIME2     NOT NULL CONSTRAINT DF_Subjects_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Subjects PRIMARY KEY (SubjectId),
    CONSTRAINT UQ_Subjects_Title UNIQUE (Title),
    CONSTRAINT CK_Subjects_Status CHECK (Status IN (N'Active', N'Archived'))
);
GO

IF OBJECT_ID(N'dbo.Topics', N'U') IS NULL
CREATE TABLE dbo.Topics (
    TopicId    INT IDENTITY(1,1) NOT NULL,
    SubjectId  INT           NOT NULL,
    Title      NVARCHAR(150) NOT NULL,
    OrderIndex INT           NOT NULL,
    Status     NVARCHAR(20)  NOT NULL,
    CreatedBy  INT           NOT NULL,
    CreatedAt  DATETIME2     NOT NULL CONSTRAINT DF_Topics_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Topics PRIMARY KEY (TopicId),
    CONSTRAINT UQ_Topics_Subject_OrderIndex UNIQUE (SubjectId, OrderIndex),
    CONSTRAINT CK_Topics_Status CHECK (Status IN (N'Draft', N'Published', N'Archived')),
    CONSTRAINT FK_Topics_Subjects FOREIGN KEY (SubjectId) REFERENCES dbo.Subjects (SubjectId),
    CONSTRAINT FK_Topics_Users_CreatedBy FOREIGN KEY (CreatedBy) REFERENCES dbo.Users (UserId)
);
GO

IF OBJECT_ID(N'dbo.FacultyAssignments', N'U') IS NULL
CREATE TABLE dbo.FacultyAssignments (
    AssignmentId INT IDENTITY(1,1) NOT NULL,
    BatchId      INT       NOT NULL,
    SubjectId    INT       NOT NULL,
    FacultyId    INT       NOT NULL,       -- must have role Faculty; enforced by backend
    AssignedBy   INT       NOT NULL,
    AssignedAt   DATETIME2 NOT NULL CONSTRAINT DF_FacultyAssignments_AssignedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_FacultyAssignments PRIMARY KEY (AssignmentId),
    CONSTRAINT UQ_FacultyAssignments_Batch_Subject UNIQUE (BatchId, SubjectId),
    CONSTRAINT FK_FacultyAssignments_Batches  FOREIGN KEY (BatchId)    REFERENCES dbo.Batches (BatchId),
    CONSTRAINT FK_FacultyAssignments_Subjects FOREIGN KEY (SubjectId)  REFERENCES dbo.Subjects (SubjectId),
    CONSTRAINT FK_FacultyAssignments_Users_Faculty    FOREIGN KEY (FacultyId)  REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_FacultyAssignments_Users_AssignedBy FOREIGN KEY (AssignedBy) REFERENCES dbo.Users (UserId)
);
GO

IF OBJECT_ID(N'dbo.Lessons', N'U') IS NULL
CREATE TABLE dbo.Lessons (
    LessonId    INT IDENTITY(1,1) NOT NULL,
    TopicId     INT           NOT NULL,
    Title       NVARCHAR(150) NOT NULL,
    ContentBody NVARCHAR(MAX) NULL,
    Objectives  NVARCHAR(MAX) NULL,        -- metadata only (locked decision 8)
    OrderIndex  INT           NOT NULL,
    Status      NVARCHAR(20)  NOT NULL,
    CONSTRAINT PK_Lessons PRIMARY KEY (LessonId),
    CONSTRAINT UQ_Lessons_Topic_OrderIndex UNIQUE (TopicId, OrderIndex),
    CONSTRAINT CK_Lessons_Status CHECK (Status IN (N'Draft', N'Published', N'Archived')),
    CONSTRAINT FK_Lessons_Topics FOREIGN KEY (TopicId) REFERENCES dbo.Topics (TopicId)
);
GO

IF OBJECT_ID(N'dbo.LessonResources', N'U') IS NULL
CREATE TABLE dbo.LessonResources (
    ResourceId   INT IDENTITY(1,1) NOT NULL,
    LessonId     INT           NOT NULL,
    ResourceType NVARCHAR(20)  NOT NULL,
    Title        NVARCHAR(150) NOT NULL,
    Url          NVARCHAR(500) NOT NULL,   -- external URL only; no uploads in V1
    OrderIndex   INT           NOT NULL,
    CONSTRAINT PK_LessonResources PRIMARY KEY (ResourceId),
    CONSTRAINT UQ_LessonResources_Lesson_OrderIndex UNIQUE (LessonId, OrderIndex),
    CONSTRAINT CK_LessonResources_ResourceType CHECK (ResourceType IN (N'Image', N'Video', N'Link')),
    CONSTRAINT FK_LessonResources_Lessons FOREIGN KEY (LessonId) REFERENCES dbo.Lessons (LessonId) ON DELETE CASCADE
);
GO

/* --------------------------- D3 Assessment Data --------------------------- */

IF OBJECT_ID(N'dbo.Activities', N'U') IS NULL
CREATE TABLE dbo.Activities (
    ActivityId   INT IDENTITY(1,1) NOT NULL,
    TopicId      INT           NOT NULL,
    Title        NVARCHAR(150) NOT NULL,
    Instructions NVARCHAR(MAX) NOT NULL,
    ActivityType NVARCHAR(20)  NOT NULL,
    IsGraded     BIT           NOT NULL,
    MaxScore     DECIMAL(5,2)  NULL,
    StarterCode  NVARCHAR(MAX) NULL,
    Hints        NVARCHAR(MAX) NULL,
    TimeLimitMs  INT           NULL,
    Status       NVARCHAR(20)  NOT NULL,
    CreatedBy    INT           NOT NULL,
    CreatedAt    DATETIME2     NOT NULL CONSTRAINT DF_Activities_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Activities PRIMARY KEY (ActivityId),
    CONSTRAINT CK_Activities_ActivityType CHECK (ActivityType IN (N'Practice', N'Quiz', N'Coding', N'SQL', N'Assignment')),
    CONSTRAINT CK_Activities_Status CHECK (Status IN (N'Draft', N'Published', N'Archived')),
    -- IsGraded = 0 is allowed only for Practice activities
    CONSTRAINT CK_Activities_IsGraded CHECK (IsGraded = 1 OR ActivityType = N'Practice'),
    -- MaxScore must be positive when present, and is required when the activity is graded
    CONSTRAINT CK_Activities_MaxScore CHECK (MaxScore IS NULL OR MaxScore > 0),
    CONSTRAINT CK_Activities_GradedHasMaxScore CHECK (IsGraded = 0 OR MaxScore IS NOT NULL),
    CONSTRAINT CK_Activities_TimeLimitMs CHECK (TimeLimitMs IS NULL OR TimeLimitMs > 0),
    CONSTRAINT FK_Activities_Topics FOREIGN KEY (TopicId) REFERENCES dbo.Topics (TopicId),
    CONSTRAINT FK_Activities_Users_CreatedBy FOREIGN KEY (CreatedBy) REFERENCES dbo.Users (UserId)
);
GO

IF OBJECT_ID(N'dbo.QuizQuestions', N'U') IS NULL
CREATE TABLE dbo.QuizQuestions (
    QuestionId   INT IDENTITY(1,1) NOT NULL,
    ActivityId   INT           NOT NULL,
    QuestionText NVARCHAR(MAX) NOT NULL,
    Explanation  NVARCHAR(MAX) NULL,
    Points       DECIMAL(5,2)  NOT NULL,
    OrderIndex   INT           NOT NULL,
    CONSTRAINT PK_QuizQuestions PRIMARY KEY (QuestionId),
    CONSTRAINT UQ_QuizQuestions_Activity_OrderIndex UNIQUE (ActivityId, OrderIndex),
    CONSTRAINT CK_QuizQuestions_Points CHECK (Points > 0),
    CONSTRAINT FK_QuizQuestions_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId) ON DELETE CASCADE
);
GO

IF OBJECT_ID(N'dbo.QuizOptions', N'U') IS NULL
CREATE TABLE dbo.QuizOptions (
    OptionId   INT IDENTITY(1,1) NOT NULL,
    QuestionId INT           NOT NULL,
    OptionText NVARCHAR(MAX) NOT NULL,
    IsCorrect  BIT           NOT NULL,
    OrderIndex INT           NOT NULL,
    CONSTRAINT PK_QuizOptions PRIMARY KEY (OptionId),
    -- target of the composite FK in SubmissionAnswers
    CONSTRAINT UQ_QuizOptions_Question_Option UNIQUE (QuestionId, OptionId),
    CONSTRAINT UQ_QuizOptions_Question_OrderIndex UNIQUE (QuestionId, OrderIndex),
    CONSTRAINT FK_QuizOptions_QuizQuestions FOREIGN KEY (QuestionId) REFERENCES dbo.QuizQuestions (QuestionId) ON DELETE CASCADE
);
GO

IF OBJECT_ID(N'dbo.TestCases', N'U') IS NULL
CREATE TABLE dbo.TestCases (
    TestCaseId     INT IDENTITY(1,1) NOT NULL,
    ActivityId     INT           NOT NULL,
    InputData      NVARCHAR(MAX) NULL,
    ExpectedOutput NVARCHAR(MAX) NOT NULL,
    OrderIndex     INT           NOT NULL,
    CONSTRAINT PK_TestCases PRIMARY KEY (TestCaseId),
    CONSTRAINT UQ_TestCases_Activity_OrderIndex UNIQUE (ActivityId, OrderIndex),
    CONSTRAINT FK_TestCases_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId) ON DELETE CASCADE
);
GO

IF OBJECT_ID(N'dbo.SqlTaskSpecs', N'U') IS NULL
CREATE TABLE dbo.SqlTaskSpecs (
    ActivityId     INT           NOT NULL,   -- 1:1 with an SQL activity (backend rule: ActivityType = 'SQL')
    SetupScript    NVARCHAR(MAX) NOT NULL,
    ExpectedResult NVARCHAR(MAX) NOT NULL,
    CONSTRAINT PK_SqlTaskSpecs PRIMARY KEY (ActivityId),
    CONSTRAINT CK_SqlTaskSpecs_ExpectedResult_Json CHECK (ISJSON(ExpectedResult) = 1),
    CONSTRAINT FK_SqlTaskSpecs_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId) ON DELETE CASCADE
);
GO

/* -------------------------- D4 Submission Data ---------------------------- */

IF OBJECT_ID(N'dbo.PracticeDrafts', N'U') IS NULL
CREATE TABLE dbo.PracticeDrafts (
    DraftId    INT IDENTITY(1,1) NOT NULL,
    StudentId  INT           NOT NULL,
    ActivityId INT           NOT NULL,
    Content    NVARCHAR(MAX) NOT NULL,
    UpdatedAt  DATETIME2     NOT NULL CONSTRAINT DF_PracticeDrafts_UpdatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_PracticeDrafts PRIMARY KEY (DraftId),
    CONSTRAINT UQ_PracticeDrafts_Student_Activity UNIQUE (StudentId, ActivityId),
    CONSTRAINT FK_PracticeDrafts_Users_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_PracticeDrafts_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId)
);
GO

IF OBJECT_ID(N'dbo.Submissions', N'U') IS NULL
CREATE TABLE dbo.Submissions (
    SubmissionId     INT IDENTITY(1,1) NOT NULL,
    StudentId        INT           NOT NULL,
    ActivityId       INT           NOT NULL,
    AttemptNo        INT           NOT NULL,
    SubmittedContent NVARCHAR(MAX) NULL,
    Status           NVARCHAR(20)  NOT NULL,
    Score            DECIMAL(5,2)  NULL,
    Feedback         NVARCHAR(MAX) NULL,
    GradedBy         INT           NULL,      -- NULL = automated grade
    GradedAt         DATETIME2     NULL,
    SubmittedAt      DATETIME2     NOT NULL CONSTRAINT DF_Submissions_SubmittedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Submissions PRIMARY KEY (SubmissionId),
    CONSTRAINT UQ_Submissions_Activity_Student_Attempt UNIQUE (ActivityId, StudentId, AttemptNo),
    CONSTRAINT CK_Submissions_AttemptNo CHECK (AttemptNo > 0),
    CONSTRAINT CK_Submissions_Status CHECK (Status IN (N'Submitted', N'Graded')),
    CONSTRAINT CK_Submissions_Score CHECK (Score IS NULL OR Score >= 0),
    CONSTRAINT CK_Submissions_GradedHasScore CHECK (Status <> N'Graded' OR Score IS NOT NULL),
    CONSTRAINT FK_Submissions_Users_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_Submissions_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId),
    CONSTRAINT FK_Submissions_Users_GradedBy FOREIGN KEY (GradedBy) REFERENCES dbo.Users (UserId)
);
GO

IF OBJECT_ID(N'dbo.SubmissionAnswers', N'U') IS NULL
CREATE TABLE dbo.SubmissionAnswers (
    SubmissionId INT NOT NULL,
    QuestionId   INT NOT NULL,
    OptionId     INT NOT NULL,
    -- one answer per question per attempt (single-answer integrity)
    CONSTRAINT PK_SubmissionAnswers PRIMARY KEY (SubmissionId, QuestionId),
    CONSTRAINT FK_SubmissionAnswers_Submissions FOREIGN KEY (SubmissionId) REFERENCES dbo.Submissions (SubmissionId) ON DELETE CASCADE,
    CONSTRAINT FK_SubmissionAnswers_QuizQuestions FOREIGN KEY (QuestionId) REFERENCES dbo.QuizQuestions (QuestionId),
    -- the chosen option must belong to the same question
    CONSTRAINT FK_SubmissionAnswers_QuizOptions_Question_Option FOREIGN KEY (QuestionId, OptionId)
        REFERENCES dbo.QuizOptions (QuestionId, OptionId)
);
GO

IF OBJECT_ID(N'dbo.TestCaseResults', N'U') IS NULL
CREATE TABLE dbo.TestCaseResults (
    ResultId        INT IDENTITY(1,1) NOT NULL,
    SubmissionId    INT           NOT NULL,
    TestCaseId      INT           NOT NULL,
    Passed          BIT           NOT NULL,
    ActualOutput    NVARCHAR(MAX) NULL,
    ExecutionTimeMs INT           NULL,
    CONSTRAINT PK_TestCaseResults PRIMARY KEY (ResultId),
    CONSTRAINT UQ_TestCaseResults_Submission_TestCase UNIQUE (SubmissionId, TestCaseId),
    CONSTRAINT CK_TestCaseResults_ExecutionTimeMs CHECK (ExecutionTimeMs IS NULL OR ExecutionTimeMs >= 0),
    CONSTRAINT FK_TestCaseResults_Submissions FOREIGN KEY (SubmissionId) REFERENCES dbo.Submissions (SubmissionId) ON DELETE CASCADE,
    -- NO ACTION: avoids multiple cascade paths (SQL Server error 1785)
    CONSTRAINT FK_TestCaseResults_TestCases FOREIGN KEY (TestCaseId) REFERENCES dbo.TestCases (TestCaseId)
);
GO

/* -------------------------- D5 Analytics Data ----------------------------- */

IF OBJECT_ID(N'dbo.LearningActivity', N'U') IS NULL
CREATE TABLE dbo.LearningActivity (
    EventId    BIGINT IDENTITY(1,1) NOT NULL,
    StudentId  INT          NOT NULL,
    EventType  NVARCHAR(30) NOT NULL,
    LessonId   INT          NULL,
    ActivityId INT          NULL,
    OccurredAt DATETIME2    NOT NULL CONSTRAINT DF_LearningActivity_OccurredAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_LearningActivity PRIMARY KEY (EventId),
    CONSTRAINT CK_LearningActivity_EventType CHECK (EventType IN (N'LessonViewed', N'ActivitySubmitted', N'AIQuery', N'TabSwitch')),
    CONSTRAINT CK_LearningActivity_RequiredContext CHECK (
        (EventType <> N'LessonViewed' OR LessonId IS NOT NULL)
        AND (EventType NOT IN (N'ActivitySubmitted', N'TabSwitch') OR ActivityId IS NOT NULL)),
    CONSTRAINT FK_LearningActivity_Users_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_LearningActivity_Lessons FOREIGN KEY (LessonId) REFERENCES dbo.Lessons (LessonId),
    CONSTRAINT FK_LearningActivity_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId)
);
GO

IF OBJECT_ID(N'dbo.StudentProgress', N'U') IS NULL
CREATE TABLE dbo.StudentProgress (
    ProgressId        INT IDENTITY(1,1) NOT NULL,
    StudentId         INT          NOT NULL,
    TopicId           INT          NOT NULL,
    AggregateScorePct DECIMAL(5,2) NULL,
    LastUpdatedAt     DATETIME2    NOT NULL CONSTRAINT DF_StudentProgress_LastUpdatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_StudentProgress PRIMARY KEY (ProgressId),
    CONSTRAINT UQ_StudentProgress_Student_Topic UNIQUE (StudentId, TopicId),
    CONSTRAINT CK_StudentProgress_AggregateScorePct CHECK (AggregateScorePct IS NULL OR AggregateScorePct BETWEEN 0 AND 100),
    CONSTRAINT FK_StudentProgress_Users_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_StudentProgress_Topics FOREIGN KEY (TopicId) REFERENCES dbo.Topics (TopicId)
);
GO

IF OBJECT_ID(N'dbo.Recommendations', N'U') IS NULL
CREATE TABLE dbo.Recommendations (
    RecommendationId INT IDENTITY(1,1) NOT NULL,
    StudentId        INT           NOT NULL,
    TopicId          INT           NOT NULL,
    ActivityId       INT           NULL,
    RuleCode         NVARCHAR(50)  NOT NULL,
    Reason           NVARCHAR(255) NOT NULL,
    CreatedAt        DATETIME2     NOT NULL CONSTRAINT DF_Recommendations_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_Recommendations PRIMARY KEY (RecommendationId),
    CONSTRAINT FK_Recommendations_Users_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users (UserId),
    CONSTRAINT FK_Recommendations_Topics FOREIGN KEY (TopicId) REFERENCES dbo.Topics (TopicId),
    CONSTRAINT FK_Recommendations_Activities FOREIGN KEY (ActivityId) REFERENCES dbo.Activities (ActivityId)
);
GO

/* --------------------------------- Indexes --------------------------------
   Supporting indexes for foreign keys that no UNIQUE constraint already leads.
   (FK columns that lead a UNIQUE constraint are already indexed by it.) */

-- At most one correct option per question (filtered unique index)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_QuizOptions_OneCorrectPerQuestion' AND object_id = OBJECT_ID(N'dbo.QuizOptions'))
CREATE UNIQUE INDEX UX_QuizOptions_OneCorrectPerQuestion ON dbo.QuizOptions (QuestionId) WHERE IsCorrect = 1;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Users_RoleId' AND object_id = OBJECT_ID(N'dbo.Users'))
CREATE INDEX IX_Users_RoleId ON dbo.Users (RoleId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Users_BatchId' AND object_id = OBJECT_ID(N'dbo.Users'))
CREATE INDEX IX_Users_BatchId ON dbo.Users (BatchId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Batches_CreatedBy' AND object_id = OBJECT_ID(N'dbo.Batches'))
CREATE INDEX IX_Batches_CreatedBy ON dbo.Batches (CreatedBy);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_FacultyAssignments_SubjectId' AND object_id = OBJECT_ID(N'dbo.FacultyAssignments'))
CREATE INDEX IX_FacultyAssignments_SubjectId ON dbo.FacultyAssignments (SubjectId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_FacultyAssignments_FacultyId' AND object_id = OBJECT_ID(N'dbo.FacultyAssignments'))
CREATE INDEX IX_FacultyAssignments_FacultyId ON dbo.FacultyAssignments (FacultyId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_FacultyAssignments_AssignedBy' AND object_id = OBJECT_ID(N'dbo.FacultyAssignments'))
CREATE INDEX IX_FacultyAssignments_AssignedBy ON dbo.FacultyAssignments (AssignedBy);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Topics_CreatedBy' AND object_id = OBJECT_ID(N'dbo.Topics'))
CREATE INDEX IX_Topics_CreatedBy ON dbo.Topics (CreatedBy);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Activities_TopicId' AND object_id = OBJECT_ID(N'dbo.Activities'))
CREATE INDEX IX_Activities_TopicId ON dbo.Activities (TopicId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Activities_CreatedBy' AND object_id = OBJECT_ID(N'dbo.Activities'))
CREATE INDEX IX_Activities_CreatedBy ON dbo.Activities (CreatedBy);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_PracticeDrafts_ActivityId' AND object_id = OBJECT_ID(N'dbo.PracticeDrafts'))
CREATE INDEX IX_PracticeDrafts_ActivityId ON dbo.PracticeDrafts (ActivityId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Submissions_StudentId' AND object_id = OBJECT_ID(N'dbo.Submissions'))
CREATE INDEX IX_Submissions_StudentId ON dbo.Submissions (StudentId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Submissions_GradedBy' AND object_id = OBJECT_ID(N'dbo.Submissions'))
CREATE INDEX IX_Submissions_GradedBy ON dbo.Submissions (GradedBy);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_SubmissionAnswers_Question_Option' AND object_id = OBJECT_ID(N'dbo.SubmissionAnswers'))
CREATE INDEX IX_SubmissionAnswers_Question_Option ON dbo.SubmissionAnswers (QuestionId, OptionId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_TestCaseResults_TestCaseId' AND object_id = OBJECT_ID(N'dbo.TestCaseResults'))
CREATE INDEX IX_TestCaseResults_TestCaseId ON dbo.TestCaseResults (TestCaseId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_LearningActivity_Student_OccurredAt' AND object_id = OBJECT_ID(N'dbo.LearningActivity'))
CREATE INDEX IX_LearningActivity_Student_OccurredAt ON dbo.LearningActivity (StudentId, OccurredAt);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_LearningActivity_LessonId' AND object_id = OBJECT_ID(N'dbo.LearningActivity'))
CREATE INDEX IX_LearningActivity_LessonId ON dbo.LearningActivity (LessonId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_LearningActivity_ActivityId' AND object_id = OBJECT_ID(N'dbo.LearningActivity'))
CREATE INDEX IX_LearningActivity_ActivityId ON dbo.LearningActivity (ActivityId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_StudentProgress_TopicId' AND object_id = OBJECT_ID(N'dbo.StudentProgress'))
CREATE INDEX IX_StudentProgress_TopicId ON dbo.StudentProgress (TopicId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Recommendations_StudentId' AND object_id = OBJECT_ID(N'dbo.Recommendations'))
CREATE INDEX IX_Recommendations_StudentId ON dbo.Recommendations (StudentId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Recommendations_TopicId' AND object_id = OBJECT_ID(N'dbo.Recommendations'))
CREATE INDEX IX_Recommendations_TopicId ON dbo.Recommendations (TopicId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Recommendations_ActivityId' AND object_id = OBJECT_ID(N'dbo.Recommendations'))
CREATE INDEX IX_Recommendations_ActivityId ON dbo.Recommendations (ActivityId);
GO

/* ------------------------- Reference data (required) ----------------------
   Roles are fixed (design section 5). The three V1 subjects are seeded
   (design section 8, assumption 2). No other data is inserted. */

INSERT INTO dbo.Roles (RoleName, Description)
SELECT v.RoleName, v.Description
FROM (VALUES
    (N'Student',       N'Learns, practises and submits activities'),
    (N'Faculty',       N'Authors content and grades assigned batches'),
    (N'Administrator', N'Manages users, batches and assignments')
) AS v (RoleName, Description)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Roles r WHERE r.RoleName = v.RoleName);

INSERT INTO dbo.Subjects (Title, Description, Status)
SELECT v.Title, v.Description, N'Active'
FROM (VALUES
    (N'C Programming',   N'Procedural programming fundamentals in C'),
    (N'C++ Programming', N'Object-oriented programming in C++'),
    (N'DBMS/SQL',        N'Relational database concepts and SQL')
) AS v (Title, Description)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Subjects s WHERE s.Title = v.Title);
GO
