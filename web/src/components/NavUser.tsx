"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function NavUser() {
  const { user, ready, logout } = useAuth();
  if (!ready) return null;
  if (!user)
    return (
      <Link href="/login" className="ml-auto rounded border border-white/10 px-2 py-1 text-xs hover:bg-white/5">
        Sign in
      </Link>
    );
  return (
    <div className="ml-auto flex items-center gap-3 text-xs text-slate-300">
      <span>{user.display_name}</span>
      <button onClick={logout} className="rounded border border-white/10 px-2 py-1 hover:bg-white/5">
        Sign out
      </button>
    </div>
  );
}
