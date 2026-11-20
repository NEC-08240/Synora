import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assertSeedAllowed } from '../scripts/seed.js';

const VALID_ENV = Object.freeze({ NODE_ENV: 'development', ALLOW_SEED: '1', SEED_PASSWORD: 'correct-horse-9' });

test('seed guard passes with a valid development env', () => {
  assert.doesNotThrow(() => assertSeedAllowed(VALID_ENV));
});

test('seed guard refuses when SEED_PASSWORD is unset', () => {
  assert.throws(() => assertSeedAllowed({ ...VALID_ENV, SEED_PASSWORD: undefined }), /SEED_PASSWORD is required/);
});

test('seed guard refuses a SEED_PASSWORD shorter than 12 characters', () => {
  assert.throws(() => assertSeedAllowed({ ...VALID_ENV, SEED_PASSWORD: 'short-pw1' }), /at least 12 characters/);
});

test('seed guard refuses when NODE_ENV is production', () => {
  assert.throws(() => assertSeedAllowed({ ...VALID_ENV, NODE_ENV: 'production' }), /^Error: refusing to seed production$/);
});

test('seed guard refuses when ALLOW_SEED is missing', () => {
  assert.throws(() => assertSeedAllowed({ ...VALID_ENV, ALLOW_SEED: undefined }), /ALLOW_SEED=1/);
});
