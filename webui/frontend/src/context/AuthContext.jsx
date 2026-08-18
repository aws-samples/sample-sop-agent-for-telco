import { createContext, useContext } from 'react'
const AuthContext = createContext(null)

const isAuthStubbed = import.meta.env.VITE_AUTH_STUB === 'true';
// Auth stub disabled by default; set VITE_AUTH_STUB=true for local dev only.
// Production builds that omit the env var get the secure default (no stub).
const defaultAuth = {
  isAuthenticated: isAuthStubbed,
  isAdmin: isAuthStubbed,
  user: isAuthStubbed ? { name: 'Admin (Dev)', role: 'admin' } : null,
};

export const AuthProvider = ({ children }) => (
  <AuthContext.Provider value={{ ...defaultAuth, login: () => Promise.resolve({ success: true }), logout: () => {}, changePassword: () => Promise.resolve({ success: true }), loading: false }}>
    {children}
  </AuthContext.Provider>
)
export const useAuth = () => useContext(AuthContext) || { ...defaultAuth, logout: () => {}, changePassword: () => Promise.resolve({ success: true }), loading: false }
export default AuthContext
