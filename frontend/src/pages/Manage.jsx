import { useEffect, useState } from 'react';
import { api } from '../api.js';
import Shell, { card } from '../components/Shell.jsx';

/** Faculty/Admin landing: read-only subject list. Authoring UIs are Phase 5 (December). */
export default function Manage() {
  const [subjects, setSubjects] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    api('GET', '/subjects').then((d) => setSubjects(d.subjects)).catch((e) => setError(e.message));
  }, []);
  return (
    <Shell title="Manage">
      <h1 className="mb-6 text-2xl font-bold">Subjects</h1>
      {error && <p role="alert" className="text-warning">{error}</p>}
      <div className="grid gap-4 md:grid-cols-3">
        {subjects.map((s) => (
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
