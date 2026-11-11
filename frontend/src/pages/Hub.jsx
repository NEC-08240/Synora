import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';
import Shell, { card } from '../components/Shell.jsx';
import { useAuth } from '../auth.jsx';

/** SCR-02 Student Learning Hub: allocated subjects, expand to topics and lessons. */
export default function Hub() {
  const { user } = useAuth();
  const [subjects, setSubjects] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api('GET', '/subjects').then((d) => setSubjects(d.subjects)).catch((e) => setError(e.message));
  }, []);

  return (
    <Shell title="Learning Hub">
      <h1 className="text-3xl font-bold">Welcome back, {user.name.split(' ')[0]}!</h1>
      <p className="mb-8 text-muted">Pick a subject to continue learning.</p>
      {error && <p role="alert" className="text-warning">{error}</p>}
      {subjects && subjects.length === 0 && <p className="text-muted">No subjects are allocated to your batch yet.</p>}
      <div className="grid items-start gap-4 md:grid-cols-2 lg:grid-cols-3">
        {subjects?.map((s) => <SubjectCard key={s.subjectId} subject={s} />)}
      </div>
    </Shell>
  );
}

function SubjectCard({ subject }) {
  const [topics, setTopics] = useState(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');

  const toggle = async () => {
    setOpen(!open);
    if (topics) return;
    try {
      const { topics: t } = await api('GET', `/subjects/${subject.subjectId}/topics`);
      setTopics(await Promise.all(
        t.map(async (topic) => ({ ...topic, lessons: (await api('GET', `/topics/${topic.topicId}/lessons`)).lessons })),
      ));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className={card}>
      <button onClick={toggle} className="w-full text-left" aria-expanded={open}>
        <h3 className="text-lg font-bold">{subject.title}</h3>
        <p className="text-sm text-muted">{subject.description}</p>
        <p className="mt-2 text-xs text-primary">{subject.topicCount} topics {open ? '▲' : '▼'}</p>
      </button>
      {open && (
        <ul className="mt-4 space-y-3 border-t border-border pt-4">
          {error && <li role="alert" className="text-sm text-warning">{error}</li>}
          {!topics && !error && <li className="text-sm text-muted">Loading…</li>}
          {topics?.map((t) => (
            <li key={t.topicId}>
              <p className="text-sm font-semibold">{t.title}</p>
              <ul className="ml-3 mt-1 space-y-1">
                {t.lessons.map((l) => (
                  <li key={l.lessonId}>
                    <Link to={`/learn/lessons/${l.lessonId}`} className="text-sm text-muted hover:text-primary">› {l.title}</Link>
                  </li>
                ))}
                {t.lessons.length === 0 && <li className="text-xs text-muted">No published lessons yet.</li>}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
