import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import type { CurrentUser } from "../types/user";
import * as authApi from "../api/auth";
import { ApiError } from "../api/client";

interface AuthContextValue {
  user: CurrentUser | null;
  isLoading: boolean; // true only during the initial /auth/me check on page load
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On first mount, ask the backend "who am I" using whatever cookie the
  // browser already has. This is how a page refresh doesn't log you out --
  // there is no token sitting in JS memory/localStorage to restore from,
  // the httponly cookie is the only persistent thing, and only the
  // backend can read it.
  const checkSession = useCallback(async () => {
    try {
      const currentUser = await authApi.fetchCurrentUser();
      setUser(currentUser);
    } catch (err) {
      // 401 here just means "not logged in" -- not an error state worth
      // surfacing, it's the expected outcome for a fresh visitor.
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        // Anything else (network down, backend not running) -- still
        // treat as logged-out for UI purposes, but this is worth knowing
        // about during development.
        console.error("Unexpected error checking session:", err);
        setUser(null);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const login = useCallback(async (username: string, password: string) => {
    const currentUser = await authApi.login({ username, password });
    setUser(currentUser);
    return currentUser;
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    await checkSession();
  }, [checkSession]);

  return (
    <AuthContext.Provider
      value={{ user, isLoading, login, logout, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}