import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { btn, input } from './Shell.jsx';

const CONNECT_TIMEOUT_MS = 15000;
const REPLY_TIMEOUT_MS = 60000; // idle limit: re-armed on every text frame

/** Detaches handlers before closing so a discarded socket cannot update state afterwards. */
function closeSocket(ws) {
  if (!ws) return;
  ws.onmessage = null;
  ws.onclose = null;
  ws.onerror = null;
  ws.close();
}

/** Workspace right pane: text chat with the AI tutor over the relay (docs/technical/ai-session-protocol.md). */
export default function TutorPanel({ lessonId }) {
  const [messages, setMessages] = useState([]); // { id, role: 'user' | 'ai', text }
  const [draft, setDraft] = useState('');
  const [state, setState] = useState('idle'); // idle | connecting | ready | replying | closed | error
  const [notice, setNotice] = useState('');
  const socket = useRef(null);
  const nextId = useRef(0);
  const timer = useRef(null);
  const attempt = useRef(0); // bumped on every connect/fail/unmount so stale async steps bail out

  useEffect(() => () => {
    clearTimeout(timer.current);
    attempt.current++;
    closeSocket(socket.current);
  }, []);

  const append = (role, text) => setMessages((m) => [...m, { id: nextId.current++, role, text }]);
  const markLastDone = () => setMessages((m) => (m.length ? [...m.slice(0, -1), { ...m[m.length - 1], done: true }] : m));
  const stopTimer = () => clearTimeout(timer.current);

  const fail = (message) => {
    stopTimer();
    attempt.current++;
    closeSocket(socket.current);
    socket.current = null;
    markLastDone();
    setNotice(message);
    setState('error');
  };

  const armReplyTimer = () => {
    stopTimer();
    timer.current = setTimeout(() => fail('The tutor stopped replying. Retry to start a new session.'), REPLY_TIMEOUT_MS);
  };

  const onFrame = (frame) => {
    if (frame.type === 'ready') {
      stopTimer();
      setState('ready');
    } else if (frame.type === 'text') {
      setState('replying');
      armReplyTimer();
      setMessages((m) => {
        const last = m[m.length - 1];
        return last?.role === 'ai' && !last.done
          ? [...m.slice(0, -1), { ...last, text: last.text + frame.delta }]
          : [...m, { id: nextId.current++, role: 'ai', text: frame.delta }];
      });
    } else if (frame.type === 'turn_complete') {
      stopTimer();
      setState('ready');
      markLastDone();
    } else if (frame.type === 'error') setNotice(frame.message);
  };

  const connect = async () => {
    const current = ++attempt.current;
    const isCurrent = () => current === attempt.current;
    setState('connecting');
    setNotice('');
    stopTimer();
    timer.current = setTimeout(() => fail('The tutor is taking too long to connect.'), CONNECT_TIMEOUT_MS);
    try {
      const session = await api('POST', '/ai/sessions', { lessonId });
      if (!isCurrent()) return;
      if (!session.available) {
        stopTimer();
        setNotice('The AI tutor is not configured on this server yet.');
        setState('closed');
        return;
      }
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${window.location.host}${session.wsPath}`);
      socket.current = ws;
      ws.onmessage = (e) => {
        let frame;
        try {
          frame = JSON.parse(e.data);
        } catch {
          return; // malformed frame: ignore it rather than crash the pane
        }
        onFrame(frame);
      };
      ws.onclose = () => {
        stopTimer();
        setState('closed');
        markLastDone();
      };
      ws.onerror = () => setNotice('Connection to the tutor was lost.');
    } catch (e) {
      if (!isCurrent()) return;
      stopTimer();
      setNotice(e.message);
      setState('closed');
    }
  };

  const send = (e) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || state !== 'ready') return;
    append('user', text);
    socket.current.send(JSON.stringify({ type: 'user_text', text }));
    setDraft('');
    setState('replying');
    armReplyTimer();
  };

  const offline = state === 'idle' || state === 'closed' || state === 'error';
  const offlineLabel = { closed: 'Reconnect tutor', error: 'Retry tutor' }[state] ?? 'Start tutor session';

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Synora AI tutor">
      <h2 className="border-b border-border bg-surface px-3 py-2 text-sm font-bold">Synora AI</h2>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-sm" aria-live="polite">
        {messages.length === 0 && <p className="text-muted">Ask a question about this lesson.</p>}
        {messages.map((m) => (
          <p key={m.id} className={`whitespace-pre-wrap rounded p-2 ${m.role === 'user' ? 'ml-6 bg-surface' : 'mr-6 border border-border'}`}>
            {m.text}
          </p>
        ))}
        {notice && <p role="alert" className="text-xs text-warning">{notice}</p>}
      </div>
      {offline ? (
        <button onClick={connect} className={`${btn} m-3`}>{offlineLabel}</button>
      ) : (
        <form onSubmit={send} className="flex gap-2 border-t border-border p-3">
          <input
            aria-label="Message to the tutor"
            className={input}
            maxLength={4000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={state === 'connecting' ? 'Connecting…' : 'Type your question'}
          />
          <button className={btn} disabled={state !== 'ready' || !draft.trim()}>Send</button>
        </form>
      )}
    </section>
  );
}
