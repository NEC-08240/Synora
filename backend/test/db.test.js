import { test } from 'node:test';
import assert from 'node:assert/strict';
import { closePool, getPool } from '../src/db.js';

/** Fake mssql pool: connect() fails or succeeds as scripted, and records close() calls. */
function fakePool({ connectError } = {}) {
  const pool = {
    closed: 0,
    connect: async () => {
      if (connectError) throw connectError;
      return pool;
    },
    close: async () => { pool.closed += 1; },
  };
  return pool;
}

test('a failed connect is not cached: the next getPool() retries and recovers', async () => {
  await closePool();
  const failing = fakePool({ connectError: new Error('ECONNREFUSED') });
  await assert.rejects(getPool(() => failing), /ECONNREFUSED/);
  assert.equal(failing.closed, 1, 'half-open pool is closed after a failed connect');

  const healthy = fakePool();
  const recovered = await getPool(() => healthy);
  assert.equal(recovered, healthy);
  assert.equal(await getPool(() => fakePool()), healthy, 'successful pool is cached');
  await closePool();
  assert.equal(healthy.closed, 1);
});

test('closePool does not throw when the pending connect already failed', async () => {
  await closePool();
  await assert.rejects(getPool(() => fakePool({ connectError: new Error('boom') })));
  await assert.doesNotReject(closePool());
});
