import { HttpError } from '../../http.js';

/** Stub until M3-3 (spec section 8): same interface as the real grader, grade(activity, payload) -> { score, results }. */
export async function grade() {
  throw new HttpError(501, 'Grader not implemented yet');
}
