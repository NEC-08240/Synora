import { badRequest } from '../../http.js';

/**
 * Quiz grader (spec 6.3): every question answered once, option must belong to the question,
 * score = sum of Points of correct questions. Read-only; results carry per-question correctness
 * for faculty/internal use only (M3-2 must not expose them to students).
 */
export async function grade(activity, payload) {
  const answers = payload?.answers;
  if (!Array.isArray(answers)) throw badRequest('answers must be an array');
  const byQuestion = new Map();
  for (const a of answers) {
    if (!a || a.questionId == null || a.optionId == null) throw badRequest('Each answer needs questionId and optionId');
    const qid = Number(a.questionId);
    if (byQuestion.has(qid)) throw badRequest('Duplicate answer for a question');
    byQuestion.set(qid, Number(a.optionId));
  }
  const questions = activity.questions ?? [];
  if (byQuestion.size !== questions.length) throw badRequest('Every question must be answered');

  let score = 0;
  const results = questions.map((q) => {
    const optionId = byQuestion.get(Number(q.QuestionId));
    const option = (q.options ?? []).find((o) => Number(o.OptionId) === optionId);
    if (!option) throw badRequest('Answer does not match a question option');
    const passed = Boolean(option.IsCorrect);
    if (passed) score += Number(q.Points);
    return { questionId: q.QuestionId, optionId, passed, points: passed ? Number(q.Points) : 0 };
  });
  const passed = results.filter((r) => r.passed).length;
  return { score: Math.round(score * 100) / 100, results, passed, total: questions.length };
}
