import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseBooleanEnv,
  parseIntEnv,
  parseTrustProxy,
  parseGeminiModality,
  parseTrustServerCertificate,
  validateJwtSecret,
} from '../src/config.js';

const LONG_SECRET = 'x'.repeat(40);

test('JWT secret: a real secret of 32+ characters is accepted', () => {
  assert.equal(validateJwtSecret(LONG_SECRET), LONG_SECRET);
});

test('JWT secret: short secrets are rejected', () => {
  assert.throws(() => validateJwtSecret('short'), /at least 32 characters/);
});

test('JWT secret: placeholder values are rejected whatever their case or separator', () => {
  for (const placeholder of ['CHANGE_ME_' + 'a'.repeat(40), 'change-me-' + 'a'.repeat(40), 'Change_Me' + 'a'.repeat(40)]) {
    assert.throws(() => validateJwtSecret(placeholder), /placeholder/, placeholder.slice(0, 9));
  }
});

test('boolean env: unset/empty/false are false, true is true, anything else throws', () => {
  assert.equal(parseBooleanEnv(undefined, 'X'), false);
  assert.equal(parseBooleanEnv('', 'X'), false);
  assert.equal(parseBooleanEnv('false', 'X'), false);
  assert.equal(parseBooleanEnv('true', 'X'), true);
  assert.throws(() => parseBooleanEnv('yes', 'X'), /X must be "true" or "false"/);
});

test('DB_TRUST_SERVER_CERT: defaults to false and is allowed outside production', () => {
  assert.equal(parseTrustServerCertificate(undefined, false), false);
  assert.equal(parseTrustServerCertificate('true', false), true);
});

test('DB_TRUST_SERVER_CERT: true throws when NODE_ENV is production', () => {
  assert.throws(() => parseTrustServerCertificate('true', true), /must not be true when NODE_ENV=production/);
  assert.equal(parseTrustServerCertificate('false', true), false);
});

test('integer env: fallback when unset, validated otherwise', () => {
  assert.equal(parseIntEnv(undefined, 30, 'N'), 30);
  assert.equal(parseIntEnv('0', 30, 'N'), 0);
  assert.throws(() => parseIntEnv('-1', 30, 'N'), /N must be a non-negative integer/);
  assert.throws(() => parseIntEnv('1.5', 30, 'N'), /non-negative integer/);
});

test('TRUST_PROXY: unset means undefined (headers ignored), a number is a hop count', () => {
  assert.equal(parseTrustProxy(undefined), undefined);
  assert.equal(parseTrustProxy(''), undefined);
  assert.equal(parseTrustProxy('1'), 1);
  assert.throws(() => parseTrustProxy('loopback'), /TRUST_PROXY must be a non-negative integer/);
});

test('production without TRUST_PROXY fails at startup; 0 and a hop count are accepted', async () => {
  const { requireTrustProxyInProduction } = await import('../src/config.js');
  assert.throws(() => requireTrustProxyInProduction(undefined, true), /TRUST_PROXY must be set when NODE_ENV=production/);
  assert.equal(requireTrustProxyInProduction(0, true), 0);
  assert.equal(requireTrustProxyInProduction(undefined, false), undefined);
});

test('scratch guard refuses real and unknown databases, accepts SynoraT names', async () => {
  const { assertScratchDb } = await import('./scratch-guard.js');
  for (const name of ['SynoraV1', 'SynoraV1_Test', 'SynoraV1_Sandbox', 'Other', undefined]) {
    assert.throws(() => assertScratchDb({ DB_NAME: name }), /not a scratch database/, String(name));
  }
  assert.throws(() => assertScratchDb({ DB_NAME: 'SynoraT004_App', SANDBOX_DB_NAME: 'SynoraV1_Sandbox' }), /SANDBOX_DB_NAME=SynoraV1_Sandbox/);
  assert.doesNotThrow(() => assertScratchDb({ DB_NAME: 'SynoraT004_App', SANDBOX_DB_NAME: 'SynoraT004_Sandbox' }));
  assert.doesNotThrow(() => assertScratchDb({ DB_NAME: 'SynoraT004_App' }));
});

test('parseGeminiModality defaults to audio and accepts only audio or text', () => {
  assert.equal(parseGeminiModality(undefined), 'audio');
  assert.equal(parseGeminiModality(''), 'audio');
  assert.equal(parseGeminiModality('text'), 'text');
  assert.throws(() => parseGeminiModality('video'), /GEMINI_MODALITY/);
});
