import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assertRotateAllowed } from '../scripts/rotate-demo.js';

const OK = { ROTATE_CONFIRM: '1', DEMO_NEW_PASSWORD: 'a-long-enough-pw-16' };

test('rotate guard passes with confirmation and a long password', () => {
  assert.doesNotThrow(() => assertRotateAllowed(OK));
});
test('rotate guard refuses without ROTATE_CONFIRM', () => {
  assert.throws(() => assertRotateAllowed({ ...OK, ROTATE_CONFIRM: undefined }), /ROTATE_CONFIRM/);
});
test('rotate guard refuses a short or missing password', () => {
  assert.throws(() => assertRotateAllowed({ ...OK, DEMO_NEW_PASSWORD: 'short' }), /at least 16/);
  assert.throws(() => assertRotateAllowed({ ROTATE_CONFIRM: '1' }), /DEMO_NEW_PASSWORD/);
});
