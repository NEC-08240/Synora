import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { btn } from './Shell.jsx';

const STARTERS = {
  c: '#include <stdio.h>\n\nint main(void) {\n    printf("Hello, Synora!\\n");\n    return 0;\n}\n',
  cpp: '#include <iostream>\n\nint main() {\n    std::cout << "Hello, Synora!" << std::endl;\n    return 0;\n}\n',
  sql: 'SELECT 1 AS answer;\n',
};
const LABELS = { c: 'C', cpp: 'C++', sql: 'SQL' };

/** Workspace centre pane: editor, run button, output. Execution happens server-side (see practice-execution.md). */
export default function PracticePanel() {
  const [language, setLanguage] = useState('c');
  const [sources, setSources] = useState(STARTERS);
  const [stdin, setStdin] = useState('');
  const [status, setStatus] = useState(null); // { code, sql } runner availability
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let ignore = false;
    api('GET', '/execute/status')
      .then((s) => { if (!ignore) setStatus(s); })
      .catch(() => { if (!ignore) setStatus({ code: false, sql: false }); });
    return () => { ignore = true; };
  }, []);

  const isSql = language === 'sql';
  // Run stays disabled until the runner status is known, so a click cannot race the status check.
  const available = status ? (isSql ? status.sql : status.code) : false;

  const run = async () => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const source = sources[language];
      setResult(isSql
        ? await api('POST', '/execute/sql', { sql: source })
        : await api('POST', '/execute/code', { language, source, stdin }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Practice workspace">
      <div className="flex items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <label className="text-xs text-muted" htmlFor="practice-language">Language</label>
        <select
          id="practice-language"
          value={language}
          onChange={(e) => { setLanguage(e.target.value); setResult(null); setError(''); }}
          className="rounded border border-input-border bg-surface px-2 py-1 text-sm"
        >
          {Object.keys(LABELS).map((k) => <option key={k} value={k}>{LABELS[k]}</option>)}
        </select>
        <button onClick={run} disabled={busy || !available} className={`${btn} ml-auto py-1.5`}>
          {busy ? 'Running…' : 'Run'}
        </button>
      </div>
      {status && !available && (
        <p role="status" className="border-b border-border px-3 py-2 text-xs text-warning">
          The {LABELS[language]} runner is not configured on this server.
        </p>
      )}
      <textarea
        aria-label={`${LABELS[language]} editor`}
        spellCheck={false}
        value={sources[language]}
        onChange={(e) => setSources({ ...sources, [language]: e.target.value })}
        className="min-h-0 flex-1 resize-none bg-code-bg p-3 font-mono text-sm text-code-text outline-none"
      />
      {!isSql && (
        <input
          aria-label="Program input (stdin)"
          placeholder="Program input (stdin)"
          value={stdin}
          onChange={(e) => setStdin(e.target.value)}
          className="border-t border-code-muted/30 bg-code-bg px-3 py-2 font-mono text-xs text-code-text outline-none"
        />
      )}
      <div className="h-2/5 overflow-auto border-t border-code-muted/30 bg-code-bg p-3 font-mono text-xs text-code-text" aria-live="polite">
        {error && <p role="alert" className="text-code-error">{error}</p>}
        {!error && !result && <p className="text-code-muted">Output appears here.</p>}
        {result && (isSql ? <SqlResult r={result} /> : <CodeResult r={result} />)}
      </div>
    </section>
  );
}

function CodeResult({ r }) {
  return (
    <>
      {r.compileError && <p className="mb-1 text-code-error">Compilation failed</p>}
      {r.timedOut && <p className="mb-1 text-code-error">Time limit exceeded</p>}
      {r.stdout && <pre className="whitespace-pre-wrap">{r.stdout}</pre>}
      {r.stderr && <pre className="whitespace-pre-wrap text-code-error">{r.stderr}</pre>}
      <p className="mt-2 text-code-muted">exit {r.exitCode ?? '–'} · {r.durationMs} ms</p>
    </>
  );
}

function SqlResult({ r }) {
  if (r.error) return <pre className="whitespace-pre-wrap text-code-error">{r.error}</pre>;
  if (r.columns.length === 0) return <p className="text-code-success">Statement executed. {r.rowCount} row(s) affected.</p>;
  return (
    <>
      <table className="border-collapse">
        <thead>
          <tr>{r.columns.map((c) => <th key={c} className="border border-code-muted/40 px-2 py-1 text-left text-code-accent">{c}</th>)}</tr>
        </thead>
        <tbody>
          {r.rows.map((row, i) => (
            // Result rows have no identity and never reorder, so the index is a safe key.
            <tr key={i}>{r.columns.map((c) => <td key={c} className="border border-border px-2 py-1">{String(row[c] ?? 'NULL')}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-muted">{r.rowCount} row(s){r.truncated ? ' (truncated)' : ''}</p>
    </>
  );
}
