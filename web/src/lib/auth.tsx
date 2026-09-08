"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, AUTH_EVENT, getToken, setToken, User } from "./api";

type AuthState = {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, display_name: string, invite_code?: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    const load: Promise<User | null> = getToken() ? api.me() : Promise.resolve(null);
    load
      .then((u) => !cancelled && setUser(u))
      .catch(() => setToken(null))
      .finally(() => !cancelled && setReady(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setToken(null);
      setUser(null);
      router.push("/login");
    };
    window.addEventListener(AUTH_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_EVENT, onUnauthorized);
  }, [router]);

  const login = useCallback(async (email: string, password: string) => {
    const out = await api.login({ email, password });
    setToken(out.access_token);
    setUser(out.user);
  }, []);
  const register = useCallback(async (email: string, password: string, display_name: string, invite_code?: string) => {
    const out = await api.register({ email, password, display_name, invite_code });
    setToken(out.access_token);
    setUser(out.user);
  }, []);
  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  return <Ctx.Provider value={{ user, ready, login, register, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** Renders children only for a signed-in user; otherwise redirects to /login. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);
  if (!ready) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!user) return null;
  return <>{children}</>;
}
