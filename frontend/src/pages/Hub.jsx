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
    let ignore = false;
    api('GET', '/subjects')
      .then((d) => { if (!ignore) setSubjects(d.subjects); })
      .catch((e) => { if (!ignore) setError(e.message); });
    return () => { ignore = true; };
  }, []);

  const firstName = user?.name?.split(' ')[0] ?? '';

  return (
    <Shell title="Learning Hub">
      <h1 className="text-3xl font-bold">Welcome back{firstName ? `, ${firstName}` : ''}!</h1>
      <p className="mb-8 text-muted">Pick a subject to continue learning.</p>
      {error && <p role="alert" className="text-warning">{error}</p>}
      {!subjects && !error && <p className="text-muted">Loading subjects…</p>}
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
    setError('');
    try {
      const { topics: t } = await api('GET', `/subjects/${subject.subjectId}/topics`);
      // One failed lesson request should not blank the whole subject.
      const settled = await Promise.allSettled(
        t.map((topic) => api('GET', `/topics/${topic.topicId}/lessons`)),
      );
      setTopics(t.map((topic, i) => ({
        ...topic,
        lessons: settled[i].status === 'fulfilled' ? settled[i].value.lessons : [],
        lessonsFailed: settled[i].status === 'rejected',
      })));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className={card}>
      <button onClick={toggle} className="w-full text-left" aria-expanded={open} aria-label={`${subject.title}, ${open ? 'collapse' : 'expand'} topics`}>
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
                {t.lessonsFailed && <li role="alert" className="text-xs text-warning">Could not load lessons for this topic.</li>}
                {!t.lessonsFailed && t.lessons.length === 0 && <li className="text-xs text-muted">No published lessons yet.</li>}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
