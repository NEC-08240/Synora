// Browser smoke test for SCR-01/02/03. Drives headless Chrome/Edge over the DevTools protocol,
// so it needs no test-framework dependency. Requires the backend (:4000) and the Vite dev
// server (:5173) to be running with the seeded demo accounts.  Usage: npm run smoke
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const BASE = process.env.SMOKE_URL ?? 'http://localhost:5173';
// No default: the demo password must be supplied (the same SEED_PASSWORD used by `npm run seed`).
const PASSWORD = process.env.SEED_PASSWORD;
if (!PASSWORD) {
  console.error('SEED_PASSWORD must be set to the demo-account password (see backend/.env.example).');
  process.exit(1);
}
const DEBUG_PORT = 9333;
const WAIT_MS = 10_000;
const BROWSER = process.env.CHROME_PATH ?? [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].find(existsSync);
assert.ok(BROWSER, 'No Chrome/Edge found; set CHROME_PATH');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'synora-smoke-'));
const browser = spawn(BROWSER, [
  '--headless=new', `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--window-size=1400,900', 'about:blank',
], { stdio: 'ignore' });

async function debuggerUrl() {
  for (let i = 0; i < 50; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json();
      const page = pages.find((p) => p.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* browser still starting */ }
    await sleep(200);
  }
  throw new Error('Browser did not open its debugging port');
}

const ws = new WebSocket(await debuggerUrl());
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const pending = new Map();
const pageErrors = [];
let nextId = 0;
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.method === 'Runtime.exceptionThrown') pageErrors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
  const waiter = pending.get(msg.id);
  if (!waiter) return;
  pending.delete(msg.id);
  if (msg.error) waiter.reject(new Error(msg.error.message)); else waiter.resolve(msg.result);
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});

async function evaluate(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}\n  in: ${expression}`);
  return r.result.value;
}
async function waitFor(expression, label) {
  const deadline = Date.now() + WAIT_MS;
  while (Date.now() < deadline) {
    if (await evaluate(`Boolean(${expression})`).catch(() => false)) return;
    await sleep(100);
  }
  throw new Error(`Timed out waiting for: ${label}\n  at ${await evaluate('location.pathname')}\n  page text: ${(await evaluate('document.body.innerText')).slice(0, 400)}`);
}
const q = JSON.stringify;
const goto = (path) => send('Page.navigate', { url: BASE + path });
const hasText = (text) => `document.body.innerText.includes(${q(text)})`;
const atPath = (path) => `location.pathname === ${q(path)}`;
const click = (selector, label) => evaluate(
  `[...document.querySelectorAll(${q(selector)})].find((e) => e.innerText.trim().startsWith(${q(label)})).click()`);
async function type(selector, value) {
  await evaluate(`document.querySelector(${q(selector)}).focus()`);
  await send('Input.insertText', { text: value });
}
async function signIn(email, password = PASSWORD) {
  await goto('/login');
  await waitFor(`${atPath('/login')} && document.querySelector('input[type=email]')`, 'login form');
  await type('input[type=email]', email);
  await type('input[type=password]', password);
  await click('button', 'Sign in');
}
const step = (name) => console.log(`✔ ${name}`);

try {
  await send('Runtime.enable');
  await send('Page.enable');

  await goto('/learn');
  await waitFor(atPath('/login'), 'anonymous visitor redirected to /login');
  step('anonymous visitor is sent to the login page');

  await signIn('student@synora.local', 'wrong-password');
  await waitFor(hasText('Invalid email or password.'), 'wrong password message');
  step('wrong password shows an error and stays on login');

  await signIn('student@synora.local');
  await waitFor(`${atPath('/learn')} && ${hasText('C Programming')}`, 'student hub with subjects');
  step('student signs in and sees the learning hub (SCR-02)');

  await send('Network.enable');
  await send('Network.clearBrowserCookies'); // simulate an expired session
  await click('button', 'C Programming');
  await waitFor(`${atPath('/login')} && ${hasText('Your session has expired')}`, 'session-expired message on login');
  step('expired session returns to login with a session-expired message');
  await signIn('student@synora.local');
  await waitFor(`${atPath('/learn')} && ${hasText('C Programming')}`, 'student hub after re-login');

  await click('button', 'C Programming');
  await waitFor(`document.querySelector('a[href^="/learn/lessons/"]')`, 'lesson links under the subject');
  await evaluate(`document.querySelector('a[href^="/learn/lessons/"]').click()`);
  await waitFor(`location.pathname.startsWith('/learn/lessons/') && document.querySelector('[role=tab]') && document.querySelector('textarea')`, 'workspace with tabs and editor');
  step('subject expands to lessons and a lesson opens the workspace (SCR-03)');

  for (const tab of ['Objectives', 'Resources', 'Theory']) {
    await click('[role=tab]', tab);
    await waitFor(`document.querySelector('[role=tab][aria-selected=true]').innerText.trim() === ${q(tab)}`, `${tab} tab selected`);
  }
  step('Theory / Objectives / Resources tabs switch');

  const runners = await evaluate(`fetch('/api/v1/execute/status').then((r) => r.json())`);
  await evaluate(`(() => { const s = document.querySelector('#practice-language'); s.value = 'sql'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  if (runners.sql) {
    await waitFor(`document.querySelector('textarea').value.includes('answer')`, 'SQL starter loaded');
    await click('button', 'Run');
    await waitFor(`document.querySelector('th')?.innerText === 'answer' && document.querySelector('td')?.innerText === '1'`, 'SQL result table');
    step('SQL runs in the sandbox and the result table renders');
  } else {
    await waitFor(hasText('The SQL runner is not configured'), 'SQL runner notice');
    step('SQL runner reported as not configured (SANDBOX_DB_* unset)');
  }

  await evaluate(`(() => { const s = document.querySelector('#practice-language'); s.value = 'c'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  if (runners.code) {
    await click('button', 'Run');
    await waitFor(hasText('Hello, Synora!'), 'C program output');
    step('C program compiles and runs through the executor');
  } else {
    await waitFor(hasText('The C runner is not configured'), 'C runner notice');
    step('C runner reported as not configured (EXECUTOR_URL unset)');
  }

  await click('button', 'Start tutor session');
  await waitFor(`${hasText('The AI tutor is not configured')} || document.querySelector('input[placeholder="Type your question"]')`, 'tutor session outcome');
  step(await evaluate(hasText('The AI tutor is not configured'))
    ? 'AI tutor reported as not configured (GEMINI_API_KEY unset)'
    : 'AI tutor session opened');

  await goto('/manage');
  await waitFor(atPath('/learn'), 'student bounced from /manage');
  step('student cannot open the faculty area');

  await click('button', 'Sign out');
  await waitFor(atPath('/login'), 'signed out');
  await signIn('faculty@synora.local');
  await waitFor(atPath('/manage'), 'faculty lands on /manage');
  await goto('/learn');
  await waitFor(atPath('/manage'), 'faculty bounced from /learn');
  step('faculty lands on /manage and cannot open the student area');

  assert.deepEqual(pageErrors, [], 'uncaught page errors');
  step('no uncaught page errors');
} finally {
  ws.close();
  browser.kill();
  await sleep(500);
  rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
