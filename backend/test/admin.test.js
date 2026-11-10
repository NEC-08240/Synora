import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { api, login, startServer, stopServer, unique } from './helpers.js';

let admin;
before(async () => {
  await startServer();
  admin = await login('admin');
});
after(stopServer);

test('admin creates a batch, a student in it, a faculty member and an allocation', async () => {
  const tag = unique();
  const batch = await api('POST', '/api/v1/batches', { cookie: admin, body: { name: `Batch ${tag}`, academicYear: '2026-27' } });
  assert.equal(batch.status, 201);
  const batchId = batch.body.batch.batchId;

  const student = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'Test Student', email: `s-${tag}@synora.local`, password: 'Password123', role: 'Student', batchId },
  });
  assert.equal(student.status, 201);
  assert.equal(student.body.user.batchId, batchId);
  assert.equal(student.body.user.status, 'Active');

  const faculty = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'Test Faculty', email: `F-${tag}@Synora.local`, password: 'Password123', role: 'Faculty' },
  });
  assert.equal(faculty.status, 201);
  assert.equal(faculty.body.user.email, `f-${tag}@synora.local`, 'email is normalised to lower case');

  const allocation = await api('POST', '/api/v1/assignments', {
    cookie: admin,
    body: { batchId, subjectId: 1, facultyId: faculty.body.user.userId },
  });
  assert.equal(allocation.status, 201);
  assert.equal(allocation.body.assignment.facultyName, 'Test Faculty');

  const duplicate = await api('POST', '/api/v1/assignments', {
    cookie: admin,
    body: { batchId, subjectId: 1, facultyId: faculty.body.user.userId },
  });
  assert.equal(duplicate.status, 409, 'one faculty per batch+subject');

  const notFaculty = await api('POST', '/api/v1/assignments', {
    cookie: admin,
    body: { batchId, subjectId: 2, facultyId: student.body.user.userId },
  });
  assert.equal(notFaculty.status, 400);
  assert.match(notFaculty.body.details.facultyId, /Faculty/);

  const removed = await api('DELETE', `/api/v1/assignments/${allocation.body.assignment.assignmentId}`, { cookie: admin });
  assert.equal(removed.status, 204);
  assert.equal((await api('DELETE', `/api/v1/assignments/${allocation.body.assignment.assignmentId}`, { cookie: admin })).status, 404);
});

test('user creation validates role, batch rule, password and email uniqueness', async () => {
  const tag = unique();
  const badRole = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'X', email: `x-${tag}@synora.local`, password: 'Password123', role: 'Dean' },
  });
  assert.equal(badRole.status, 400);

  const facultyInBatch = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'X', email: `x-${tag}@synora.local`, password: 'Password123', role: 'Faculty', batchId: 1 },
  });
  assert.equal(facultyInBatch.status, 400);
  assert.match(facultyInBatch.body.details.batchId, /students/);

  const shortPw = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'X', email: `x-${tag}@synora.local`, password: 'short', role: 'Student' },
  });
  assert.equal(shortPw.status, 400);

  const dup = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'X', email: 'student@synora.local', password: 'Password123', role: 'Student' },
  });
  assert.equal(dup.status, 409);
});

test('suspending a user locks them out immediately', async () => {
  const tag = unique();
  const email = `susp-${tag}@synora.local`;
  const created = await api('POST', '/api/v1/users', {
    cookie: admin,
    body: { name: 'Suspend Me', email, password: 'Password123', role: 'Student' },
  });
  const loginRes = await api('POST', '/api/v1/auth/login', { body: { email, password: 'Password123' } });
  assert.equal(loginRes.status, 200);

  const patched = await api('PATCH', `/api/v1/users/${created.body.user.userId}`, { cookie: admin, body: { status: 'Suspended' } });
  assert.equal(patched.status, 200);
  assert.equal(patched.body.user.status, 'Suspended');

  assert.equal((await api('GET', '/api/v1/auth/me', { cookie: loginRes.cookie })).status, 401, 'existing session is invalidated');
  assert.equal((await api('POST', '/api/v1/auth/login', { body: { email, password: 'Password123' } })).status, 401);
});

test('patching an unknown user or an invalid id fails cleanly', async () => {
  assert.equal((await api('PATCH', '/api/v1/users/999999', { cookie: admin, body: { name: 'x' } })).status, 404);
  assert.equal((await api('PATCH', '/api/v1/users/abc', { cookie: admin, body: { name: 'x' } })).status, 400);
});

test('faculty sees only their own allocations', async () => {
  const faculty = await login('faculty');
  const res = await api('GET', '/api/v1/assignments', { cookie: faculty });
  assert.equal(res.status, 200);
  assert.ok(res.body.assignments.length >= 3, 'seed allocates all three subjects to the demo faculty');
  assert.ok(res.body.assignments.every((a) => a.facultyName === 'Dr. Priya Nair'));
});
