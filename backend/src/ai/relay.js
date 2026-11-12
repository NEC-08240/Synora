/**
 * WebSocket relay between the browser and the Gemini Multimodal Live API.
 *
 * Browser -> relay:  { type: 'user_text', text }        (text only in V1)
 * Relay -> browser:  { type: 'ready' }
 *                    { type: 'text', delta }            streamed model text
 *                    { type: 'turn_complete' }
 *                    { type: 'error', code, message }   then the socket closes
 *
 * The Gemini key stays on the server. Nothing said in a session is persisted.
 */
import { WebSocketServer } from 'ws';
import { config } from '../config.js';
import { COOKIE_NAME, userFromToken } from '../auth/middleware.js';
import { WS_PATH, takeSession } from './sessions.js';

const GEMINI_WS = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';
const MAX_USER_TEXT = 4000;
const IDLE_CLOSE_MS = 10 * 60 * 1000;
const MAX_MESSAGES_PER_MIN = 30; // per connection; a student cannot run up Gemini quota with a tight loop

function parseCookie(header = '') {
  const pair = header.split(';').map((s) => s.trim()).find((s) => s.startsWith(`${COOKIE_NAME}=`));
  return pair ? decodeURIComponent(pair.slice(COOKIE_NAME.length + 1)) : undefined;
}

function send(ws, msg) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(msg));
}

function fail(ws, code, message) {
  send(ws, { type: 'error', code, message });
  ws.close(1011, code);
}

/** Pipes one authorized client socket to a fresh Gemini Live session. */
export function bridge(client, session, { upstreamUrl = GEMINI_WS, apiKey = config.ai.apiKey } = {}) {
  if (!apiKey) return fail(client, 'ai_unavailable', 'The AI tutor is not configured on this server');

  // Key goes in a header, not the query string, so it stays out of URLs and proxy/access logs.
  const upstream = new WebSocket(upstreamUrl, { headers: { 'x-goog-api-key': apiKey } });
  let idleTimer = setTimeout(() => client.close(1000, 'idle'), IDLE_CLOSE_MS);
  const touch = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => client.close(1000, 'idle'), IDLE_CLOSE_MS);
  };

  upstream.addEventListener('open', () => {
    upstream.send(JSON.stringify({
      setup: {
        model: `models/${config.ai.model}`,
        generationConfig: { responseModalities: ['TEXT'] },
        systemInstruction: { parts: [{ text: session.systemInstruction }] },
      },
    }));
  });

  upstream.addEventListener('message', async (event) => {
    const raw = typeof event.data === 'string' ? event.data : await event.data.text();
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (msg.setupComplete) return send(client, { type: 'ready' });
    const content = msg.serverContent;
    if (!content) return;
    for (const part of content.modelTurn?.parts ?? []) {
      if (part.text) send(client, { type: 'text', delta: part.text });
    }
    if (content.turnComplete) send(client, { type: 'turn_complete' });
  });

  upstream.addEventListener('error', () => fail(client, 'upstream_error', 'The AI service is unreachable'));
  upstream.addEventListener('close', (event) => {
    if (client.readyState === client.OPEN) {
      // 1000 = normal; anything else (quota, bad model, auth) is surfaced so the UI can fall back.
      if (event.code !== 1000) send(client, { type: 'error', code: 'upstream_closed', message: event.reason || `Upstream closed (${event.code})` });
      client.close(1000, 'upstream closed');
    }
  });

  let windowStart = Date.now();
  let windowCount = 0;
  client.on('message', (data) => {
    touch();
    if (Date.now() - windowStart >= 60 * 1000) {
      windowStart = Date.now();
      windowCount = 0;
    }
    if (++windowCount > MAX_MESSAGES_PER_MIN) {
      return send(client, { type: 'error', code: 'rate_limited', message: 'Too many messages, slow down' });
    }
    let msg;
    try {
      msg = JSON.parse(data.toString());
    } catch {
      return send(client, { type: 'error', code: 'bad_message', message: 'Messages must be JSON' });
    }
    if (msg.type !== 'user_text' || typeof msg.text !== 'string' || !msg.text.trim()) {
      return send(client, { type: 'error', code: 'bad_message', message: 'Expected { type: "user_text", text }' });
    }
    if (msg.text.length > MAX_USER_TEXT) {
      return send(client, { type: 'error', code: 'bad_message', message: `Message too long (max ${MAX_USER_TEXT} characters)` });
    }
    if (upstream.readyState !== WebSocket.OPEN) {
      return send(client, { type: 'error', code: 'not_ready', message: 'The AI tutor is still connecting' });
    }
    upstream.send(JSON.stringify({
      clientContent: { turns: [{ role: 'user', parts: [{ text: msg.text }] }], turnComplete: true },
    }));
  });

  client.on('close', () => {
    clearTimeout(idleTimer);
    if (upstream.readyState === WebSocket.OPEN || upstream.readyState === WebSocket.CONNECTING) upstream.close(1000);
  });
}

/** Mounts the relay on an http.Server; only upgrades for WS_PATH are handled here. */
export function attachAiRelay(server, options) {
  const wss = new WebSocketServer({ noServer: true, maxPayload: 16 * 1024 });

  server.on('upgrade', async (req, socket, head) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname !== WS_PATH) return socket.destroy();

      const origin = req.headers.origin;
      if (origin && !config.corsOrigins.includes(origin)) return reject(socket, 403);
      const user = await userFromToken(parseCookie(req.headers.cookie));
      if (!user || user.RoleName !== 'Student') return reject(socket, 401);
      const session = takeSession(url.searchParams.get('session'), user.UserId);
      if (!session) return reject(socket, 403);

      wss.handleUpgrade(req, socket, head, (ws) => bridge(ws, session, options));
    } catch (err) {
      console.error('ws upgrade failed:', err.message);
      reject(socket, 500);
    }
  });
  return wss;
}

function reject(socket, status) {
  const text = { 401: 'Unauthorized', 500: 'Internal Server Error' }[status] ?? 'Forbidden';
  socket.write(`HTTP/1.1 ${status} ${text}\r\nConnection: close\r\n\r\n`);
  socket.destroy();
}
