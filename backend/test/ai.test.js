import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { WebSocketServer, WebSocket as WsClient } from 'ws';

// This file mints far more than the default 10 sessions/min; config reads the limit at import time, so set it first.
process.env.RATE_LIMIT_AI_PER_MIN = '1000';
const { api, login, startServer, stopServer } = await import('./helpers.js');
const { attachAiRelay } = await import('../src/ai/relay.js');
const { queryOne } = await import('../src/db.js');

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
    seen.apiKeyHeader = req.headers['x-goog-api-key'];
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

  assert.equal(seen.url, '/', 'key is not in the upstream URL');
  assert.equal(seen.apiKeyHeader, 'test-key', 'key is sent to upstream in a header, never to the client');
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

const T = { timeout: 30000 }; // a hung socket must fail the test, not hang the run
const LIMIT_MS = 5000;

/** Polls `fn` until it returns truthy or LIMIT_MS passes (replaces fixed sleeps). */
async function until(fn, what) {
  const end = Date.now() + LIMIT_MS;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 10));
  }
}

/** Fake Gemini upstream + relay; `onMessage(ws, msg)` handles non-setup frames. Setup always gets setupComplete. */
async function startRelay(onMessage) {
  const fake = new WebSocketServer({ port: 0 });
  const relayServer = http.createServer((req, res) => res.end());
  const stop = async () => {
    fake.clients.forEach((c) => c.terminate());
    if (relayServer.listening) await new Promise((r) => relayServer.close(r));
    await new Promise((r) => fake.close(r));
  };
  try {
    fake.on('connection', (ws) => {
      ws.on('message', (data) => {
        const msg = JSON.parse(data.toString());
        if (msg.setup) return ws.send(JSON.stringify({ setupComplete: {} }));
        onMessage?.(ws, msg);
      });
    });
    attachAiRelay(relayServer, { upstreamUrl: `ws://127.0.0.1:${fake.address().port}`, apiKey: 'test-key' });
    await new Promise((r) => relayServer.listen(0, r));
  } catch (err) {
    await stop();
    throw err;
  }
  return { url: () => `ws://127.0.0.1:${relayServer.address().port}`, port: () => relayServer.address().port, stop };
}

const mint = async () => (await api('POST', '/api/v1/ai/sessions', { cookie: student, body: {} })).body.wsPath;

/** `ws`-library client for wsPath; resolves once the relay says ready, rejects with {statusCode} on an HTTP refusal. */
function openPath(relayUrl, wsPath) {
  return new Promise((resolve, reject) => {
    const ws = new WsClient(relayUrl + wsPath, { headers: { Cookie: student } });
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('no ready frame')); }, LIMIT_MS);
    ws.on('message', (d) => JSON.parse(d.toString()).type === 'ready' && (clearTimeout(timer), resolve(ws)));
    ws.on('unexpected-response', (req, res) => { clearTimeout(timer); reject(Object.assign(new Error(`status ${res.statusCode}`), { statusCode: res.statusCode })); });
    ws.on('error', (e) => { clearTimeout(timer); reject(e); });
    ws.on('close', () => { clearTimeout(timer); reject(new Error('closed before ready')); });
  });
}
const openLive = async (relayUrl) => openPath(relayUrl, await mint());
const closed = (ws) => new Promise((r) => (ws.readyState === ws.CLOSED ? r() : ws.once('close', r)));
const bigFrame = (text) => Buffer.from(JSON.stringify({ serverContent: { modelTurn: { parts: [{ text }] }, pad: 'x'.repeat(5 * 1024 * 1024) } }));
const frame = (content) => Buffer.from(JSON.stringify({ serverContent: content }));

/** Opens a session, sends one user turn on ready, collects frames until the relay closes the socket. */
async function runTurn(relay) {
  const wsPath = await mint();
  return connect(relay.url() + wsPath, student, (ws) => {
    ws.addEventListener('message', (e) => {
      if (JSON.parse(e.data).type === 'ready') ws.send(JSON.stringify({ type: 'user_text', text: 'hi' }));
    });
  });
}

test('upstream frames are relayed in order even when an earlier Blob decodes slower', T, async () => {
  const relay = await startRelay((ws) => {
    // A is a Blob (async decode); B and turnComplete are text frames, which the old per-event handler processed immediately and so overtook A.
    ws.send(bigFrame('A'), { binary: true });
    ws.send(frame({ modelTurn: { parts: [{ text: 'B' }] } }).toString());
    ws.send(frame({ turnComplete: true }).toString());
  });
  try {
    const wsPath = await mint();
    const messages = await connect(relay.url() + wsPath, student, (ws) => {
      ws.addEventListener('message', (e) => {
        const { type } = JSON.parse(e.data);
        if (type === 'ready') ws.send(JSON.stringify({ type: 'user_text', text: 'hi' }));
        if (type === 'turn_complete') ws.close();
      });
    });
    assert.deepEqual(messages.filter((m) => m.type === 'text').map((m) => m.delta), ['A', 'B']);
  } finally {
    await relay.stop();
  }
});

test('an upstream close right after the last frames does not drop the tail of the reply', T, async () => {
  const relay = await startRelay((ws) => {
    ws.send(bigFrame('A'), { binary: true });
    ws.send(frame({ modelTurn: { parts: [{ text: 'B' }] }, turnComplete: true }), { binary: true });
    ws.close(); // upstream goes away right after the frames; the close event must not outrun the pending decodes (terminate() would discard the unsent 5 MB frame on Linux)
  });
  try {
    const messages = await runTurn(relay);
    assert.deepEqual(messages.filter((m) => m.type !== 'ready' && m.type !== 'error').map((m) => m.delta ?? m.type), ['A', 'B', 'turn_complete']);
  } finally {
    await relay.stop();
  }
});

test('an abrupt upstream termination is reported to the client as an error and closes it', T, async () => {
  const relay = await startRelay((ws) => {
    ws.send(frame({ modelTurn: { parts: [{ text: 'A' }] } }).toString());
    ws.terminate(); // no close handshake: the relay sees code 1006
  });
  try {
    const messages = await runTurn(relay);
    // 1006 raises the socket error event; it is queued behind the frame chain, so any received text is delivered first and is a prefix of the reply.
    assert.ok(messages.some((m) => m.type === 'error' && ['upstream_error', 'upstream_closed'].includes(m.code)));
    assert.ok(!messages.some((m) => m.type === 'turn_complete'));
    assert.ok(messages.filter((m) => m.type === 'text').every((m) => m.delta === 'A'), 'any delivered text is a prefix of the reply');
  } finally {
    await relay.stop();
  }
});

test('an abrupt upstream termination delivers the frames already received before the error', T, async () => {
  const relay = await startRelay((ws) => {
    ws.send(bigFrame('A'), { binary: true }, () => ws.terminate()); // frame fully written, then no close handshake (1006)
  });
  try {
    const messages = await runTurn(relay);
    const kinds = messages.filter((m) => m.type !== 'ready').map((m) => m.type);
    assert.deepEqual(kinds.slice(0, 2), ['text', 'error'], 'the received text must arrive before the error frame');
  } finally {
    await relay.stop();
  }
});

test('a student may hold at most 2 live relay sockets; refusal is a 429 that does not burn the session', T, async () => {
  const relay = await startRelay();
  const open = [];
  try {
    open.push(await openLive(relay.url()), await openLive(relay.url()));

    const wsPath = await mint();
    await assert.rejects(openPath(relay.url(), wsPath), { statusCode: 429 });
    assert.ok(open.every((ws) => ws.readyState === ws.OPEN), 'existing sockets stay open');

    // Freeing a slot lets the same (unconsumed) session through; poll until the relay has noticed the close.
    open[0].close();
    await closed(open[0]);
    open.push(await until(() => openPath(relay.url(), wsPath).catch((e) => (e.statusCode === 429 ? false : Promise.reject(e))), 'a free slot'));
  } finally {
    open.forEach((ws) => ws.terminate());
    await relay.stop();
  }
});

test('refused upgrades (unknown session, 403) release their slot', T, async () => {
  const relay = await startRelay();
  const open = [];
  try {
    for (let i = 0; i < 3; i += 1) {
      await assert.rejects(openPath(relay.url(), '/api/v1/ai/ws?session=not-a-session'), { statusCode: 403 });
    }
    // If each refusal leaked a slot, these two would already be refused with 429.
    open.push(await openLive(relay.url()), await openLive(relay.url()));
  } finally {
    open.forEach((ws) => ws.terminate());
    await relay.stop();
  }
});

test('a client frame over the 16 KB limit does not crash the API process', T, async () => {
  const relay = await startRelay();
  try {
    const ws = await openLive(relay.url());
    ws.send('x'.repeat(20 * 1024));
    await closed(ws);
    (await openLive(relay.url())).terminate(); // still serving
  } finally {
    await relay.stop();
  }
});

test('a client that resets the socket during the auth lookup neither crashes the API nor leaks a slot', T, async () => {
  const relay = await startRelay();
  const open = [];
  try {
    const wsPath = await mint(); // never consumed: the abort happens before takeSession
    for (let i = 0; i < 4; i += 1) {
      await new Promise((resolve) => {
        const sock = net.connect(relay.port(), '127.0.0.1', () => {
          sock.write(`GET ${wsPath} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\nCookie: ${student}\r\n\r\n`);
          sock.resetAndDestroy();
        });
        sock.on('error', () => {});
        sock.on('close', resolve);
      });
    }
    await new Promise((r) => setTimeout(r, 300)); // the server-side auth lookups have no observable signal
    // fresh session: on a fast runner an aborted request may already have consumed wsPath, which would make this a 403
    open.push(await openLive(relay.url()), await openLive(relay.url()));
  } finally {
    open.forEach((ws) => ws.terminate());
    await relay.stop();
  }
});
