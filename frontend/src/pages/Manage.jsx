import { useEffect, useState } from 'react';
import { api } from '../api.js';
import Shell, { card } from '../components/Shell.jsx';

/** Faculty/Admin landing: read-only subject list. Authoring UIs are Phase 5 (December). */
export default function Manage() {
  const [subjects, setSubjects] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let ignore = false;
    api('GET', '/subjects')
      .then((d) => { if (!ignore) setSubjects(d.subjects); })
      .catch((e) => { if (!ignore) setError(e.message); });
    return () => { ignore = true; };
  }, []);
  return (
    <Shell title="Manage">
      <h1 className="mb-6 text-2xl font-bold">Subjects</h1>
      {error && <p role="alert" className="text-warning">{error}</p>}
      {!subjects && !error && <p className="text-muted">Loading subjects…</p>}
      {subjects?.length === 0 && <p className="text-muted">No subjects yet.</p>}
      <div className="grid gap-4 md:grid-cols-3">
        {subjects?.map((s) => (
          <div key={s.subjectId} className={card}>
            <h3 className="font-bold">{s.title}</h3>
            <p className="text-sm text-muted">{s.status} · {s.topicCount} topics</p>
          </div>
        ))}
      </div>
      <p className="mt-8 text-sm text-muted">Content authoring and reports are scheduled for December.</p>
    </Shell>
  );
}
