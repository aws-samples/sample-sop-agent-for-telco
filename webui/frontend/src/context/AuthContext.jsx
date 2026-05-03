import { createContext, useContext } from 'react'

const AuthContext = createContext(null)

export const AuthProvider = ({ children }) => {
  const value = {
    isAuthenticated: true,
    user: { email: 'operator@anra.local', isAdmin: true },
    login: () => Promise.resolve({ success: true }),
    logout: () => {},
    changePassword: () => Promise.resolve({ success: true }),
    loading: false,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}

export default AuthContext
