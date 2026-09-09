"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "@/lib/api";

export interface AuthUser {
  id: number;
  email: string;
  role: "admin" | "platform_admin";
}

interface LoginResponse extends AuthUser {
  token: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => void;
}

const STORAGE_KEY = "trailmind.auth";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // Restore a session from localStorage, but re-validate it against the API rather
  // than trusting the stored token forever — it may have expired (12h) or the
  // account may have been suspended/rejected since it was saved.
  useEffect(() => {
    // Fetch-on-mount to re-validate a stored token — a standard pattern this rule
    // flags overzealously below (it can't see that the real setState calls only fire
    // after the async apiFetch resolves, not synchronously in the effect body; the
    // no-stored-token early exit is the one genuinely synchronous case).
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setReady(true);
      return;
    }
    const parsed = JSON.parse(stored) as { token: string };
    apiFetch<AuthUser>("/api/admin/me", { token: parsed.token })
      .then((me) => {
        setUser(me);
        setToken(parsed.token);
      })
      .catch(() => localStorage.removeItem(STORAGE_KEY))
      .finally(() => setReady(true));
  }, []);

  async function login(email: string, password: string): Promise<AuthUser> {
    const response = await apiFetch<LoginResponse>("/api/admin/login", {
      method: "POST",
      body: { email, password },
    });
    const { token: newToken, ...authUser } = response;
    setUser(authUser);
    setToken(newToken);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: newToken }));
    return authUser;
  }

  function logout() {
    setUser(null);
    setToken(null);
    localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <AuthContext.Provider value={{ user, token, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
