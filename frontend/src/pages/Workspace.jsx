import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, safeUrl } from '../api.js';
import Shell from '../components/Shell.jsx';
import PracticePanel from '../components/PracticePanel.jsx';
import TutorPanel from '../components/TutorPanel.jsx';

const TABS = ['Theory', 'Objectives', 'Resources'];

/** SCR-03 Interactive Learning Workspace: content | practice | AI tutor. */
export default function Workspace() {
  const { lessonId } = useParams();
  // Keyed by lesson so switching lessons remounts all state (lesson, tab, editor) instead of carrying it over.
  return <WorkspaceLesson key={lessonId} lessonId={lessonId} />;
}

function WorkspaceLesson({ lessonId }) {
  const [lesson, setLesson] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('Theory');

  useEffect(() => {
    let ignore = false;
    api('GET', `/lessons/${lessonId}`)
      .then((d) => { if (!ignore) setLesson(d.lesson); })
      .catch((e) => { if (!ignore) setError(e.status === 404 ? 'This lesson is not available.' : e.message); });
    return () => { ignore = true; };
  }, [lessonId]);

  if (error) {
    return (
      <Shell title="Workspace">
        <p role="alert" className="text-error">{error}</p>
        <Link to="/learn" className="mt-4 inline-block text-primary">Back to the hub</Link>
      </Shell>
    );
  }
  if (!lesson) return <Shell title="Workspace"><p className="text-muted">Loading…</p></Shell>;

  return (
    <Shell title={lesson.title} full>
      <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <section className="flex min-h-0 flex-col border-r border-border" aria-label="Lesson content">
          <div role="tablist" className="flex border-b border-border">
            {TABS.map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`flex-1 py-3 text-sm ${tab === t ? 'border-b-2 border-primary text-primary' : 'text-muted hover:text-text'}`}
              >
                {t}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="min-h-0 flex-1 overflow-auto p-5">
            {tab === 'Theory' && (
              <>
                <h1 className="mb-3 text-xl font-bold">{lesson.title}</h1>
                {/* Rendered as text, never HTML: content is faculty-authored but still untrusted. */}
                <div className="whitespace-pre-wrap text-sm leading-relaxed">{lesson.contentBody}</div>
              </>
            )}
            {tab === 'Objectives' && (
              <div className="whitespace-pre-wrap text-sm leading-relaxed">{lesson.objectives || 'No objectives listed.'}</div>
            )}
            {tab === 'Resources' && (
              <ul className="space-y-2 text-sm">
                {lesson.resources.length === 0 && <li className="text-muted">No resources for this lesson.</li>}
                {lesson.resources.map((r) => (
                  <li key={r.resourceId}>
                    <span className="mr-2 text-xs text-muted">{r.resourceType}</span>
                    {safeUrl(r.url)
                      ? <a href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{r.title}</a>
                      : r.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
        <div className="min-h-0 border-r border-border"><PracticePanel /></div>
        <TutorPanel key={lessonId} lessonId={Number(lessonId)} />
      </div>
    </Shell>
  );
}
