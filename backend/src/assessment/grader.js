import { config } from '../config.js';
import { query, queryOne } from '../db.js';
import { badRequest, tooManyRequests } from '../http.js';
import { grade as gradeQuiz } from './graders/quiz.js';
import { grade as gradeCode } from './graders/code.js';
import { grade as gradeSql } from './graders/sql.js';

/*
 * Grader registry. Interface: grade(activity, payload) -> { score, results }, pure of HTTP and of submission writes.
 * ActivityType -> grader. Assignment (and Practice) is never auto-graded, so it has no entry.
 * registerGrader is the seam M3-2 tests use to inject a stub grader.
 */
const graders = new Map([
  ['Quiz', gradeQuiz],
  ['Coding', gradeCode],
  ['SQL', gradeSql],
]);

export function registerGrader(activityType, fn) {
  graders.set(activityType, fn);
}

// Bounded in-process semaphore: grading may spawn sandbox work, so cap how many run at once.
let running = 0;
const waiting = [];

async function acquire() {
  if (running < config.assessment.gradeConcurrency) {
    running += 1;
    return;
  }
  if (waiting.length >= config.assessment.queueMax) throw tooManyRequests('Grading is busy, please try again in a moment');
  await new Promise((resolve) => waiting.push(resolve));
}

function release() {
  const next = waiting.shift();
  if (next) next(); // hand the slot over without decrementing
  else running -= 1;
}

/**
 * Server-side only: hydrates the activity with everything its grader needs, hidden data included
 * (IsCorrect, test cases, ExpectedResult as the stored JSON string). Never feed the result to a student projection.
 */
export async function loadGradable(activity) {
  const id = activity.ActivityId;
  if (activity.ActivityType === 'Quiz') {
    const questions = await query('SELECT * FROM dbo.QuizQuestions WHERE ActivityId = @id ORDER BY OrderIndex', { id });
    const options = await query(
      'SELECT o.* FROM dbo.QuizOptions o JOIN dbo.QuizQuestions q ON q.QuestionId = o.QuestionId WHERE q.ActivityId = @id',
      { id },
    );
    for (const q of questions) q.options = options.filter((o) => o.QuestionId === q.QuestionId);
    return { ...activity, questions };
  }
  if (activity.ActivityType === 'Coding') {
    const testCases = await query('SELECT * FROM dbo.TestCases WHERE ActivityId = @id ORDER BY OrderIndex', { id });
    const subject = await queryOne('SELECT Title FROM dbo.Subjects WHERE SubjectId = @id', { id: activity.SubjectId });
    const m = /^c(\+\+)?(\s|$)/i.exec(subject?.Title ?? ''); // same rule as the publish check (D3): language comes from the Subject
    return { ...activity, testCases, language: m ? (m[1] ? 'cpp' : 'c') : null };
  }
  if (activity.ActivityType === 'SQL') {
    return { ...activity, sqlSpec: await queryOne('SELECT * FROM dbo.SqlTaskSpecs WHERE ActivityId = @id', { id }) };
  }
  return activity;
}

export async function runGrading(activity, payload) {
  const grader = graders.get(activity.ActivityType);
  if (!grader) throw badRequest(`${activity.ActivityType} activities are not auto-graded`);
  await acquire();
  try {
    return await grader(activity, payload);
  } finally {
    release();
  }
}
