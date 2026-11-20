import { Navigate, Route, Routes } from 'react-router-dom';
import { RequireRole, homeFor, useAuth } from './auth.jsx';
import Login from './pages/Login.jsx';
import Hub from './pages/Hub.jsx';
import Workspace from './pages/Workspace.jsx';
import Manage from './pages/Manage.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';

function Root() {
  const { user } = useAuth();
  if (user === undefined) return null;
  return <Navigate to={user ? homeFor(user.role) : '/login'} replace />;
}

// Role boundaries are enforced server-side; RequireRole only redirects. Faculty and Administrator share /manage.
export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Root />} />
        <Route path="/login" element={<Login />} />
        <Route path="/learn" element={<RequireRole roles={['Student']}><Hub /></RequireRole>} />
        <Route path="/learn/lessons/:lessonId" element={<RequireRole roles={['Student']}><Workspace /></RequireRole>} />
        <Route path="/manage" element={<RequireRole roles={['Faculty', 'Administrator']}><Manage /></RequireRole>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}
