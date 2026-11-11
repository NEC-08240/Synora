import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { WebSocketServer } from 'ws';
import { api, login, startServer, stopServer } from './helpers.js';
import { attachAiRelay } from '../src/ai/relay.js';
import { queryOne } from '../src/db.js';

let student;
let baseUrl;
before(async () => {
  baseUrl = await startServer();
  student = await login('student');
});
after(stopServer);

const wsUrl = (path) => baseUrl.replace('http', 'ws') + path;

/** Opens a client socket with the auth cookie; resolves with collected messages until close. */
function connect(url, cookie, onOpen) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, { headers: cookie ? { Cookie: cookie } : {} });
    const messages = [];
    ws.addEventListener('message', (e) => messages.push(JSON.parse(e.data)));
    ws.addEventListener('open', () => onOpen?.(ws));
    ws.addEventListener('close', () => resolve(messages));
    ws.addEventListener('error', (e) => (messages.length ? resolve(messages) : reject(e.error ?? new Error('ws error'))));
  });
}

test('only students can open AI sessions, and an AIQuery event is recorded without content', async () => {
  const me = (await api('GET', '/api/v1/auth/me', { cookie: student })).body.user;
  const before = (await queryOne(`SELECT COUNT(*) AS n FROM dbo.LearningActivity WHERE StudentId = @id AND EventType = N'AIQuery'`, { id: me.userId })).n;

  const faculty = await login('faculty');
  assert.equal((await api('POST', '/api/v1/ai/sessions', { cookie: faculty, body: {} })).status, 403);

  const topics = (await api('GET', '/api/v1/subjects/1/topics', { cookie: student })).body.topics;
  const lessons = (await api('GET', `/api/v1/topics/${topics[0].topicId}/lessons`, { cookie: student })).body.lessons;
  const res = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: { lessonId: lessons[0].lessonId } });
  assert.equal(res.status, 201);
  assert.match(res.body.wsPath, /^\/api\/v1\/ai\/ws\?session=[0-9a-f-]{36}$/);
  assert.equal(res.body.context.lessonId, lessons[0].lessonId);
  assert.equal(typeof res.body.available, 'boolean');

  assert.equal((await api('POST', '/api/v1/ai/sessions', { cookie: student, body: { lessonId: 999999 } })).status, 404);

  const after = (await queryOne(`SELECT COUNT(*) AS n FROM dbo.LearningActivity WHERE StudentId = @id AND EventType = N'AIQuery'`, { id: me.userId })).n;
  assert.equal(after, before + 1);
});

test('relay rejects unauthenticated, foreign and reused sessions', async () => {
  const { body } = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} });
  await assert.rejects(connect(wsUrl(body.wsPath)), 'no cookie');
  await assert.rejects(connect(wsUrl('/api/v1/ai/ws?session=not-a-session'), student), 'unknown session');

  const faculty = await login('faculty');
  await assert.rejects(connect(wsUrl(body.wsPath), faculty), 'another user');

  const first = await connect(wsUrl(body.wsPath), student); // consumes the session (no key configured -> error frame)
  assert.ok(first.length >= 1);
  await assert.rejects(connect(wsUrl(body.wsPath), student), 'single use');
});

test('without GEMINI_API_KEY the client gets an explicit ai_unavailable error', async () => {
  const { body } = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} });
  const messages = await connect(wsUrl(body.wsPath), student);
  assert.deepEqual(messages[0], { type: 'error', code: 'ai_unavailable', message: 'The AI tutor is not configured on this server' });
});

test('relay streams text from a Gemini-shaped upstream and validates client frames', async () => {
  // Fake Gemini Live endpoint: acknowledges setup, echoes each user turn back in two chunks.
  const fake = new WebSocketServer({ port: 0 });
  const seen = {};
  fake.on('connection', (ws, req) => {
    seen.url = req.url;
    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      if (msg.setup) {
        seen.setup = msg.setup;
        return ws.send(JSON.stringify({ setupComplete: {} }));
      }
      const text = msg.clientContent.turns[0].parts[0].text;
      ws.send(JSON.stringify({ serverContent: { modelTurn: { parts: [{ text: `Echo: ${text.slice(0, 3)}` }] } } }));
      ws.send(JSON.stringify({ serverContent: { modelTurn: { parts: [{ text: text.slice(3) }] }, turnComplete: true } }));
    });
  });
  const upstreamUrl = `ws://127.0.0.1:${fake.address().port}`;

  const relayServer = http.createServer((req, res) => res.end());
  attachAiRelay(relayServer, { upstreamUrl, apiKey: 'test-key' });
  await new Promise((r) => relayServer.listen(0, r));

  const { body } = await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} });
  const messages = await connect(`ws://127.0.0.1:${relayServer.address().port}${body.wsPath}`, student, (ws) => {
    ws.send('not json');
    ws.addEventListener('message', (e) => {
      const { type } = JSON.parse(e.data);
      if (type === 'ready') ws.send(JSON.stringify({ type: 'user_text', text: 'hello world' }));
      if (type === 'turn_complete') ws.close();
    });
  });

  assert.equal(seen.url, '/?key=test-key', 'key is sent to upstream, never to the client');
  assert.equal(seen.setup.generationConfig.responseModalities[0], 'TEXT');
  assert.match(seen.setup.systemInstruction.parts[0].text, /Arjun Menon/);
  // The client's bad frame races the upstream 'ready'; check the streamed sequence without it.
  assert.deepEqual(messages.filter((m) => m.type !== 'error'), [
    { type: 'ready' },
    { type: 'text', delta: 'Echo: hel' },
    { type: 'text', delta: 'lo world' },
    { type: 'turn_complete' },
  ]);
  assert.ok(messages.some((m) => m.code === 'bad_message'));
  assert.ok(!JSON.stringify(messages).includes('test-key'));

  await new Promise((r) => relayServer.close(r));
  await new Promise((r) => fake.close(r));
});
