import { createContext, useContext, useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { api } from './api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading, null = anonymous

  useEffect(() => {
    api('GET', '/auth/me').then((d) => setUser(d.user)).catch(() => setUser(null));
  }, []);

  const login = async (email, password) => {
    const d = await api('POST', '/auth/login', { email, password });
    setUser(d.user);
    return d.user;
  };
  const logout = async () => {
    await api('POST', '/auth/logout').catch(() => {});
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

export const homeFor = (role) => (role === 'Student' ? '/learn' : '/manage');

export function RequireRole({ roles, children }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined) return <p className="p-8 text-muted">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return children;
}
