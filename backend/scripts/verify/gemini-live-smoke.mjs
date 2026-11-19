/*
 * Live Gemini tutor smoke test (verification only, not part of `npm test`).
 * Needs a RUNNING API whose process has GEMINI_API_KEY set (the key never enters this script).
 *   BASE_URL=http://localhost:4012 SMOKE_EMAIL=student@synora.local SMOKE_PASSWORD=... LESSON_ID=1 \
 *     node scripts/verify/gemini-live-smoke.mjs
 * Prints timings and event names only; never message headers, cookies or the key. Uses at most 3 live Gemini turns.
 */
import WebSocket from 'ws';

const { BASE_URL, SMOKE_EMAIL, SMOKE_PASSWORD, LESSON_ID } = process.env;
if (!BASE_URL || !SMOKE_EMAIL || !SMOKE_PASSWORD) throw new Error('BASE_URL, SMOKE_EMAIL and SMOKE_PASSWORD are required');

const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ email: SMOKE_EMAIL, password: SMOKE_PASSWORD }),
});
if (res.status !== 200) throw new Error(`login failed: ${res.status}`);
const cookie = res.headers.get('set-cookie').split(';')[0];

async function openSocket() {
  const r = await fetch(`${BASE_URL}/api/v1/ai/sessions`, {
    method: 'POST', headers: { 'content-type': 'application/json', cookie },
    body: JSON.stringify(LESSON_ID ? { lessonId: Number(LESSON_ID) } : {}),
  });
  const body = await r.json();
  if (r.status !== 201) throw new Error(`session ${r.status} ${JSON.stringify(body)}`);
  console.log(`session: 201 available=${body.available}`);
  const ws = new WebSocket(`${BASE_URL.replace('http', 'ws')}${body.wsPath}`, { headers: { cookie } });
  const events = [];
  ws.on('message', (d) => events.push({ at: Date.now(), msg: JSON.parse(d.toString()) }));
  return new Promise((resolve) => {
    ws.on('unexpected-response', (_q, rs) => resolve({ refused: rs.statusCode }));
    ws.on('error', () => {});
    ws.on('open', () => resolve({ ws, events }));
  });
}

const waitFor = (events, pred, ms = 30000) => new Promise((resolve) => {
  const t0 = Date.now();
  const tick = () => {
    const hit = events.find(pred);
    if (hit) return resolve(hit);
    if (Date.now() - t0 > ms) return resolve(null);
    setTimeout(tick, 50);
  };
  tick();
});

async function ask(label, text) {
  const s = await openSocket();
  if (s.refused) return console.log(`${label}: refused ${s.refused}`);
  const { ws, events } = s;
  const ready = await waitFor(events, (e) => e.msg.type === 'ready' || e.msg.type === 'error');
  console.log(`${label}: first event=${ready ? ready.msg.type : 'none'}${ready?.msg.code ? ` code=${ready.msg.code} message=${ready.msg.message}` : ''}`);
  if (ready?.msg.type !== 'ready') return ws.close();
  const t0 = Date.now();
  ws.send(JSON.stringify({ type: 'user_text', text }));
  const done = await waitFor(events, (e) => e.at >= t0 && (e.msg.type === 'turn_complete' || e.msg.type === 'error'), 45000);
  const turn = events.filter((e) => e.at >= t0);
  const deltas = turn.filter((e) => e.msg.type === 'text');
  const order = turn.map((e) => e.msg.type).filter((t, i, a) => a[i - 1] !== t).join('>');
  console.log(`${label}: order=${order} deltas=${deltas.length} firstDeltaMs=${deltas[0] ? deltas[0].at - t0 : 'n/a'} totalMs=${done ? done.at - t0 : 'timeout'}`);
  const reply = deltas.map((e) => e.msg.delta).join('');
  console.log(`${label}: reply(first 200 chars)=${JSON.stringify(reply.slice(0, 200))}`);
  const err = turn.find((e) => e.msg.type === 'error');
  if (err) console.log(`${label}: error code=${err.msg.code} message=${err.msg.message}`);
  return { ws, events };
}

const a = await ask('on-topic', 'In one sentence, what is a pointer in C?');
if (a?.ws) {
  a.ws.close();
  await ask('off-topic', 'What is the capital of France?').then((r) => r?.ws?.close());
}

// Local protections (no Gemini turn needed for the long-message and socket-cap checks).
const s1 = await openSocket();
const s2 = await openSocket();
const s3 = await openSocket();
console.log(`socket cap: 1=${s1.refused ?? 'open'} 2=${s2.refused ?? 'open'} 3=${s3.refused ?? 'open'}`);
if (s1.ws) {
  s1.ws.send(JSON.stringify({ type: 'user_text', text: 'x'.repeat(4001) }));
  const e = await waitFor(s1.events, (x) => x.msg.type === 'error' && x.msg.code === 'bad_message', 5000);
  console.log(`over-4000 message: ${e ? `rejected (${e.msg.code})` : 'NOT rejected'}`);
}
for (const s of [s1, s2, s3]) s.ws?.close();
process.exit(0);
