import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { btn, input } from '../components/Shell.jsx';
import { homeFor, useAuth } from '../auth.jsx';
import { SESSION_EXPIRED_MESSAGE } from '../uiState.js';

/** Maps a failed login to user-facing text; the server's "not active" message is shown as-is. */
function loginErrorMessage(err) {
  if (err.status === 401) return /not active/i.test(err.message) ? err.message : 'Invalid email or password.';
  if (err.status === 429) return 'Too many attempts, try later.';
  return 'Sign-in failed. Please try again.';
}

/** SCR-01 Auth & Gateway: single login form, role-based redirect. */
export default function Login() {
  const { user, expired, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const u = await login(email, password);
      // Only honour a remembered path the role can actually open.
      const from = u.role === 'Student' ? location.state?.from : null;
      navigate(from ?? homeFor(u.role), { replace: true });
    } catch (err) {
      setError(loginErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex h-full items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-surface p-8">
        <h1 className="text-2xl font-semibold text-primary">Synora</h1>
        <p className="text-sm text-muted">Sign in with your institute account.</p>
        <label className="block text-sm">
          <span className="text-muted">Email</span>
          <input className={input} type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Password</span>
          <input className={input} type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {expired && !error && <p role="status" className="alert alert-warning">{SESSION_EXPIRED_MESSAGE}</p>}
        {error && <p role="alert" className="alert">{error}</p>}
        <button className={`${btn} w-full`} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main>
  );
}
