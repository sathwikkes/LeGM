"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginForm() {
  const { user, ready, login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [invite, setInvite] = useState("");
  const [inviteRequired, setInviteRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);
  useEffect(() => {
    api.authConfig().then((c) => setInviteRequired(c.invite_required)).catch(() => {});
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name, invite || undefined);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-10 max-w-sm rounded-lg border border-white/10 bg-[#0e1729] p-5">
      <div className="mb-4 flex gap-2 text-sm">
        <button onClick={() => setMode("login")} className={`rounded px-3 py-1 ${mode === "login" ? "bg-white/10" : "text-slate-400"}`}>
          Sign in
        </button>
        <button onClick={() => setMode("register")} className={`rounded px-3 py-1 ${mode === "register" ? "bg-white/10" : "text-slate-400"}`}>
          Create account
        </button>
      </div>
      <form onSubmit={submit} className="space-y-3">
        {mode === "register" && (
          <label className="block text-sm">
            <span className="text-slate-300">Display name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5" />
          </label>
        )}
        <label className="block text-sm">
          <span className="text-slate-300">Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5" />
        </label>
        <label className="block text-sm">
          <span className="text-slate-300">Password{mode === "register" ? " (8+ characters)" : ""}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 8 : 1}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5"
          />
        </label>
        {mode === "register" && inviteRequired && (
          <label className="block text-sm">
            <span className="text-slate-300">Invite code</span>
            <input value={invite} onChange={(e) => setInvite(e.target.value)} required className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5" />
          </label>
        )}
        <button disabled={busy} className="w-full rounded bg-amber-500 px-3 py-2 text-sm font-semibold text-black hover:bg-amber-400 disabled:opacity-50">
          {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}
