import { config } from '../config.js';
import { badRequest } from '../http.js';
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
  await new Promise((resolve) => waiting.push(resolve));
}

function release() {
  const next = waiting.shift();
  if (next) next(); // hand the slot over without decrementing
  else running -= 1;
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
