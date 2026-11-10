import { badRequest } from './http.js';

/**
 * Minimal body validation. `rules` maps field -> { type: 'string'|'int'|'bool'|'enum',
 * required?, max?, values? }. Returns a new object with only the declared fields.
 */
export function validate(body, rules) {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    throw badRequest('Request body must be a JSON object');
  }
  const errors = {};
  const out = {};
  for (const [field, rule] of Object.entries(rules)) {
    const value = body[field];
    if (value === undefined || value === null || value === '') {
      if (rule.required) errors[field] = 'is required';
      else if (value === null) out[field] = null;
      continue;
    }
    const err = check(value, rule);
    if (err) errors[field] = err;
    else out[field] = rule.type === 'string' ? value.trim() : value;
  }
  if (Object.keys(errors).length) throw badRequest('Validation failed', errors);
  return out;
}

function check(value, rule) {
  switch (rule.type) {
    case 'string':
      if (typeof value !== 'string') return 'must be a string';
      if (!value.trim()) return 'must not be blank';
      if (rule.max && value.length > rule.max) return `must be at most ${rule.max} characters`;
      return null;
    case 'int':
      if (!Number.isInteger(value)) return 'must be an integer';
      if (rule.min !== undefined && value < rule.min) return `must be >= ${rule.min}`;
      return null;
    case 'bool':
      return typeof value === 'boolean' ? null : 'must be a boolean';
    case 'enum':
      return rule.values.includes(value) ? null : `must be one of: ${rule.values.join(', ')}`;
    default:
      throw new Error(`Unknown rule type ${rule.type}`);
  }
}

/** Parse a positive integer route parameter or throw 400. */
export function idParam(raw, name = 'id') {
  const n = Number(raw);
  if (!Number.isInteger(n) || n <= 0) throw badRequest(`Invalid ${name}`);
  return n;
}
