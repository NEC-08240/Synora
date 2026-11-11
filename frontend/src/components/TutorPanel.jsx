import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { btn, input } from './Shell.jsx';

/** Workspace right pane: text chat with the AI tutor over the relay (docs/technical/ai-session-protocol.md). */
export default function TutorPanel({ lessonId }) {
  const [messages, setMessages] = useState([]); // { id, role: 'user' | 'ai', text }
  const [draft, setDraft] = useState('');
  const [state, setState] = useState('idle'); // idle | connecting | ready | replying | closed
  const [notice, setNotice] = useState('');
  const socket = useRef(null);
  const nextId = useRef(0);

  useEffect(() => () => socket.current?.close(), []);

  const append = (role, text) => setMessages((m) => [...m, { id: nextId.current++, role, text }]);

  const onFrame = (frame) => {
    if (frame.type === 'ready') setState('ready');
    else if (frame.type === 'text') {
      setState('replying');
      setMessages((m) => {
        const last = m[m.length - 1];
        return last?.role === 'ai' && !last.done
          ? [...m.slice(0, -1), { ...last, text: last.text + frame.delta }]
          : [...m, { id: nextId.current++, role: 'ai', text: frame.delta }];
      });
    } else if (frame.type === 'turn_complete') {
      setState('ready');
      setMessages((m) => (m.length ? [...m.slice(0, -1), { ...m[m.length - 1], done: true }] : m));
    } else if (frame.type === 'error') setNotice(frame.message);
  };

  const connect = async () => {
    setState('connecting');
    setNotice('');
    try {
      const session = await api('POST', '/ai/sessions', { lessonId });
      if (!session.available) {
        setNotice('The AI tutor is not configured on this server yet.');
        setState('closed');
        return;
      }
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${window.location.host}${session.wsPath}`);
      socket.current = ws;
      ws.onmessage = (e) => onFrame(JSON.parse(e.data));
      ws.onclose = () => setState('closed');
      ws.onerror = () => setNotice('Connection to the tutor was lost.');
    } catch (e) {
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
  };

  const offline = state === 'idle' || state === 'closed';

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
        <button onClick={connect} className={`${btn} m-3`}>{state === 'closed' ? 'Reconnect tutor' : 'Start tutor session'}</button>
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
