import { test } from 'node:test';
import assert from 'node:assert/strict';
import { grade } from '../src/assessment/graders/quiz.js';

const opt = (OptionId, IsCorrect) => ({ OptionId, IsCorrect, OptionText: `o${OptionId}` });
const activity = {
  ActivityType: 'Quiz',
  questions: [
    { QuestionId: 1, Points: 2.5, options: [opt(10, true), opt(11, false)] },
    { QuestionId: 2, Points: 1, options: [opt(20, false), opt(21, true)] },
  ],
};
const ans = (...pairs) => ({ answers: pairs.map(([questionId, optionId]) => ({ questionId, optionId })) });

test('quiz: score is the sum of points of correct questions', async () => {
  const all = await grade(activity, ans([1, 10], [2, 21]));
  assert.equal(all.score, 3.5);
  const half = await grade(activity, ans([1, 10], [2, 20]));
  assert.equal(half.score, 2.5);
  assert.deepEqual(half.results.map((r) => [r.questionId, r.passed]), [[1, true], [2, false]]);
  assert.equal((await grade(activity, ans([1, 11], [2, 20]))).score, 0);
});

test('quiz: every question must be answered, once, with an option of that question', async () => {
  await assert.rejects(grade(activity, ans([1, 10])), { status: 400 });
  await assert.rejects(grade(activity, ans([1, 10], [2, 21], [3, 1])), { status: 400 });
  await assert.rejects(grade(activity, ans([1, 10], [1, 11], [2, 21])), { status: 400 });
  await assert.rejects(grade(activity, ans([1, 10], [2, 10])), { status: 400 });
  await assert.rejects(grade(activity, {}), { status: 400 });
  await assert.rejects(grade(activity, { answers: [null] }), { status: 400 });
});

test('quiz: ids sent as numeric strings still match', async () => {
  assert.equal((await grade(activity, ans(['1', '10'], ['2', '21']))).score, 3.5);
});
