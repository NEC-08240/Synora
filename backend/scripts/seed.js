/**
 * Idempotent development seed: reference data (Roles, Subjects), one demo batch,
 * one demo user per role, faculty allocations and a small published lesson tree.
 * Run: node --env-file=.env scripts/seed.js   (uses DB_NAME from the env file)
 * Demo passwords are development-only; see README "Demo accounts".
 */
import process from 'node:process';
import bcrypt from 'bcryptjs';
import { query, queryOne, closePool } from '../src/db.js';

const DEMO_PASSWORD = process.env.SEED_PASSWORD ?? 'Synora@2026';

const ROLES = [
  ['Student', 'Learns, practises and submits activities'],
  ['Faculty', 'Authors content and grades assigned batches'],
  ['Administrator', 'Manages users, batches and assignments'],
];
const SUBJECTS = [
  ['C Programming', 'Procedural programming fundamentals in C'],
  ['C++ Programming', 'Object-oriented programming in C++'],
  ['DBMS/SQL', 'Relational database concepts and SQL'],
];
const USERS = [
  ['Administrator', 'Synora Admin', 'admin@synora.local'],
  ['Faculty', 'Dr. Priya Nair', 'faculty@synora.local'],
  ['Student', 'Arjun Menon', 'student@synora.local'],
];
const TOPICS = {
  'C Programming': [
    ['Introduction to C', [['Hello, World and the compile cycle', 'Understand how a C program is written, compiled and run.'], ['Variables and data types', 'Declare variables and choose the right primitive type.']]],
    ['Control Flow', [['if / else and switch', 'Branch program execution on conditions.'], ['Loops: for, while, do-while', 'Repeat work with the three loop forms.']]],
    ['Pointers and Arrays', [['Arrays and indexing', 'Store sequences of values.'], ['Pointer basics', 'Hold and dereference addresses.']]],
  ],
  'C++ Programming': [
    ['From C to C++', [['Namespaces, iostream and references', 'See what C++ adds on top of C.']]],
    ['Classes and Objects', [['Defining a class', 'Group data and behaviour.'], ['Constructors and destructors', 'Control object lifetime.']]],
  ],
  'DBMS/SQL': [
    ['Relational Model', [['Tables, rows and keys', 'Understand relations, primary keys and foreign keys.']]],
    ['Querying with SELECT', [['SELECT, WHERE and ORDER BY', 'Filter and sort rows.'], ['JOINs', 'Combine rows across tables.']]],
  ],
};

async function ensure(selectSql, insertSql, params) {
  const existing = await queryOne(selectSql, params);
  if (existing) return existing.Id;
  const row = await queryOne(insertSql, params);
  return row.Id;
}

async function main() {
  for (const [name, description] of ROLES) {
    await ensure(
      `SELECT RoleId AS Id FROM dbo.Roles WHERE RoleName = @name`,
      `INSERT INTO dbo.Roles (RoleName, Description) OUTPUT INSERTED.RoleId AS Id VALUES (@name, @description)`,
      { name, description },
    );
  }
  const subjectIds = {};
  for (const [title, description] of SUBJECTS) {
    subjectIds[title] = await ensure(
      `SELECT SubjectId AS Id FROM dbo.Subjects WHERE Title = @title`,
      `INSERT INTO dbo.Subjects (Title, Description, Status) OUTPUT INSERTED.SubjectId AS Id VALUES (@title, @description, N'Active')`,
      { title, description },
    );
  }

  const hash = await bcrypt.hash(DEMO_PASSWORD, 10);
  const userIds = {};
  for (const [role, name, email] of USERS) {
    userIds[role] = await ensure(
      `SELECT UserId AS Id FROM dbo.Users WHERE Email = @email`,
      `INSERT INTO dbo.Users (RoleId, Name, Email, PasswordHash) OUTPUT INSERTED.UserId AS Id
       SELECT RoleId, @name, @email, @hash FROM dbo.Roles WHERE RoleName = @role`,
      { role, name, email, hash },
    );
  }

  const batchId = await ensure(
    `SELECT BatchId AS Id FROM dbo.Batches WHERE Name = @name`,
    `INSERT INTO dbo.Batches (Name, AcademicYear, Status, CreatedBy) OUTPUT INSERTED.BatchId AS Id VALUES (@name, @year, N'Active', @by)`,
    { name: 'BCA 2026 - Section A', year: '2026-27', by: userIds.Administrator },
  );
  await query(`UPDATE dbo.Users SET BatchId = @batchId WHERE UserId = @id AND BatchId IS NULL`, { batchId, id: userIds.Student });

  for (const subjectId of Object.values(subjectIds)) {
    await ensure(
      `SELECT AssignmentId AS Id FROM dbo.FacultyAssignments WHERE BatchId = @batchId AND SubjectId = @subjectId`,
      `INSERT INTO dbo.FacultyAssignments (BatchId, SubjectId, FacultyId, AssignedBy) OUTPUT INSERTED.AssignmentId AS Id
       VALUES (@batchId, @subjectId, @facultyId, @by)`,
      { batchId, subjectId, facultyId: userIds.Faculty, by: userIds.Administrator },
    );
  }

  for (const [subjectTitle, topics] of Object.entries(TOPICS)) {
    const subjectId = subjectIds[subjectTitle];
    for (const [tIndex, [topicTitle, lessons]] of topics.entries()) {
      const topicId = await ensure(
        `SELECT TopicId AS Id FROM dbo.Topics WHERE SubjectId = @subjectId AND OrderIndex = @orderIndex`,
        `INSERT INTO dbo.Topics (SubjectId, Title, OrderIndex, Status, CreatedBy) OUTPUT INSERTED.TopicId AS Id
         VALUES (@subjectId, @title, @orderIndex, N'Published', @by)`,
        { subjectId, title: topicTitle, orderIndex: tIndex + 1, by: userIds.Faculty },
      );
      for (const [lIndex, [lessonTitle, objective]] of lessons.entries()) {
        await ensure(
          `SELECT LessonId AS Id FROM dbo.Lessons WHERE TopicId = @topicId AND OrderIndex = @orderIndex`,
          `INSERT INTO dbo.Lessons (TopicId, Title, ContentBody, Objectives, OrderIndex, Status) OUTPUT INSERTED.LessonId AS Id
           VALUES (@topicId, @title, @body, @objective, @orderIndex, N'Published')`,
          {
            topicId,
            title: lessonTitle,
            body: `# ${lessonTitle}\n\n${objective}\n\nThis lesson body is seed content. Faculty replace it from the Authoring Studio (SCR-05).`,
            objective,
            orderIndex: lIndex + 1,
          },
        );
      }
    }
  }

  const counts = await queryOne(
    `SELECT (SELECT COUNT(*) FROM dbo.Users) AS Users, (SELECT COUNT(*) FROM dbo.Topics) AS Topics, (SELECT COUNT(*) FROM dbo.Lessons) AS Lessons`,
  );
  console.log(`Seed complete for ${process.env.DB_NAME}:`, counts);
}

try {
  await main();
} finally {
  await closePool();
}
