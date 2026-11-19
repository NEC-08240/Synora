/*
 * Projections: the ONLY place assessment rows become API objects (spec section 6, hidden-data protection).
 * Student projections are an allow-list, so a new column never leaks by default. Students never receive
 * IsCorrect, Explanation, InputData, ExpectedOutput, ExpectedResult, or ActualOutput/stderr of hidden cases.
 * SetupScript IS student-visible: /execute/sql needs it and the tables are queryable anyway.
 */

const activityBase = (a) => ({
  activityId: a.ActivityId,
  topicId: a.TopicId,
  title: a.Title,
  instructions: a.Instructions,
  activityType: a.ActivityType,
  isGraded: Boolean(a.IsGraded),
  maxScore: a.MaxScore,
  starterCode: a.StarterCode ?? null,
  hints: a.Hints ?? null,
  timeLimitMs: a.TimeLimitMs ?? null,
  status: a.Status,
});

export const questionStudent = (q) => ({
  questionId: q.QuestionId,
  questionText: q.QuestionText,
  points: q.Points,
  orderIndex: q.OrderIndex,
  options: (q.options ?? []).map((o) => ({ optionId: o.OptionId, optionText: o.OptionText, orderIndex: o.OrderIndex })),
});

export const questionFaculty = (q) => ({
  questionId: q.QuestionId,
  questionText: q.QuestionText,
  explanation: q.Explanation ?? null,
  points: q.Points,
  orderIndex: q.OrderIndex,
  options: (q.options ?? []).map((o) => ({
    optionId: o.OptionId,
    optionText: o.OptionText,
    isCorrect: Boolean(o.IsCorrect),
    orderIndex: o.OrderIndex,
  })),
});

/** Test cases are hidden from students (D2); they only learn that a case exists. */
export const testCaseStudent = (tc) => ({ testCaseId: tc.TestCaseId, orderIndex: tc.OrderIndex });

export const testCaseFaculty = (tc) => ({
  testCaseId: tc.TestCaseId,
  inputData: tc.InputData,
  expectedOutput: tc.ExpectedOutput,
  orderIndex: tc.OrderIndex,
});

export const sqlSpecStudent = (s) => ({ setupScript: s.SetupScript });
export const sqlSpecFaculty = (s) => ({ setupScript: s.SetupScript, expectedResult: s.ExpectedResult });

export const activityStudent = (a, { questions = [], testCases = [], sqlSpec = null } = {}) => ({
  ...activityBase(a),
  questions: questions.map(questionStudent),
  testCases: testCases.map(testCaseStudent),
  sqlSpec: sqlSpec ? sqlSpecStudent(sqlSpec) : null,
});

export const activityFaculty = (a, { questions = [], testCases = [], sqlSpec = null } = {}) => ({
  ...activityBase(a),
  createdBy: a.CreatedBy,
  questions: questions.map(questionFaculty),
  testCases: testCases.map(testCaseFaculty),
  sqlSpec: sqlSpec ? sqlSpecFaculty(sqlSpec) : null,
});

/** Student-visible grading outcome: counts and flags only, never per-case output or stderr. */
export const resultStudent = (r) => ({
  passed: r.passed,
  total: r.total,
  compileError: Boolean(r.compileError),
  timedOut: Boolean(r.timedOut),
});

export const resultFaculty = (r) => ({
  testCaseId: r.TestCaseId,
  passed: Boolean(r.Passed),
  actualOutput: r.ActualOutput ?? null,
  executionTimeMs: r.ExecutionTimeMs ?? null,
});

const submissionBase = (s) => ({
  submissionId: s.SubmissionId,
  activityId: s.ActivityId,
  attemptNo: s.AttemptNo,
  status: s.Status,
  score: s.Score ?? null,
  feedback: s.Feedback ?? null,
  submittedContent: s.SubmittedContent ?? null,
  submittedAt: s.SubmittedAt,
  gradedAt: s.GradedAt ?? null,
});

export const submissionStudent = (s) => ({
  ...submissionBase(s),
  ...(s.total === undefined ? {} : { passed: s.passed, total: s.total }),
});

export const submissionFaculty = (s) => ({
  ...submissionBase(s),
  studentId: s.StudentId,
  gradedBy: s.GradedBy ?? null,
});
