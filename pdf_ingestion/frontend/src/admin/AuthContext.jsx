import React, { createContext, useContext, useState, useCallback } from "react";

const AuthContext = createContext(null);

/**
 * AuthProvider — wraps the admin app and provides auth state.
 *
 * Stores token and user info in memory (not localStorage) for security.
 * Provides login/logout functions and exposes isAuthenticated, user, token.
 */
export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);

  const login = useCallback((newToken, userInfo) => {
    setToken(newToken);
    setUser(userInfo);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const isAuthenticated = !!token;

  const value = {
    token,
    user,
    isAuthenticated,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * useAuth — hook to access auth context values.
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
