import { Link } from 'react-router-dom';
import { useAuth } from '../auth.jsx';

/** Top bar + page body shared by every signed-in screen. */
export default function Shell({ title, children, full = false }) {
  const { user, logout } = useAuth();
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-border bg-surface px-5 py-3">
        <Link to="/" className="text-lg font-bold tracking-wide text-primary">Synora</Link>
        {title && <span className="text-sm text-muted">/ {title}</span>}
        <span className="ml-auto text-sm text-muted">{user?.name} · {user?.role}</span>
        <button onClick={logout} className="rounded border border-border px-3 py-1 text-sm hover:border-primary hover:text-primary">
          Sign out
        </button>
      </header>
      <main className={full ? 'min-h-0 flex-1' : 'mx-auto w-full max-w-6xl flex-1 p-6'}>{children}</main>
    </div>
  );
}

export const card = 'rounded-lg border border-border bg-surface p-5';
export const btn = 'rounded bg-primary px-4 py-2 text-sm font-semibold text-canvas hover:bg-primary/90 disabled:opacity-50';
export const input = 'w-full rounded border border-border bg-canvas px-3 py-2 text-sm text-text outline-none focus:border-primary';
