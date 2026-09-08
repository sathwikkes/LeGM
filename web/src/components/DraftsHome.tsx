"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, DraftSummary, League } from "@/lib/api";

export default function DraftsHome() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<DraftSummary[] | null>(null);
  const [league, setLeague] = useState<League | null>(null);
  const [name, setName] = useState("");
  const [slot, setSlot] = useState(1);
  const [teams, setTeams] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Until /api/league answers, fall back to the config default the API also uses.
  const numTeams = teams ?? league?.num_teams ?? 8;
  const maxTeams = league?.max_teams ?? 20;

  const refresh = () => api.drafts().then(setDrafts).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    api.league().then(setLeague).catch((e) => setError(e.message));
  }, []);

  const changeTeams = (n: number) => {
    setTeams(n);
    if (slot > n) setSlot(n); // keep the draft slot inside the new team count
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await api.createDraft({ name: name.trim(), user_slot: slot, num_teams: numTeams });
      router.push(`/draft/${d.draft_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm(`Delete draft "${id}"?`)) return;
    await api.deleteDraft(id);
    refresh();
  };

  return (
    <div className="grid gap-6 md:grid-cols-[360px_1fr]">
      <section className="rounded-lg border border-white/10 bg-[#0e1729] p-4">
        <h2 className="mb-3 text-base font-semibold">New draft</h2>
        {league && (
          <p className="mb-3 text-xs text-slate-400">
            {league.draft_type} · {league.format} · {league.slots.join(" ")} + {league.bench} BN
          </p>
        )}
        <form onSubmit={create} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-300">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              pattern="[A-Za-z0-9_\-]+"
              required
              placeholder="league-2026"
              className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-300">Teams</span>
            <select
              value={numTeams}
              onChange={(e) => changeTeams(Number(e.target.value))}
              className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5"
            >
              {Array.from({ length: maxTeams - 1 }, (_, i) => i + 2).map((n) => (
                <option key={n} value={n}>
                  {n} teams{n === league?.num_teams ? " (league default)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-300">Your draft slot</span>
            <select
              value={slot}
              onChange={(e) => setSlot(Number(e.target.value))}
              className="mt-1 w-full rounded border border-white/10 bg-[#0b1220] px-2 py-1.5"
            >
              {Array.from({ length: numTeams }, (_, i) => (
                <option key={i} value={i + 1}>
                  Pick {i + 1}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={busy}
            className="w-full rounded bg-amber-500 px-3 py-2 text-sm font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
          >
            {busy ? "Building pool…" : "Start draft"}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </section>

      <section>
        <h2 className="mb-3 text-base font-semibold">Saved drafts</h2>
        {drafts === null ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : drafts.length === 0 ? (
          <p className="text-sm text-slate-400">No drafts yet.</p>
        ) : (
          <ul className="divide-y divide-white/10 rounded-lg border border-white/10 bg-[#0e1729]">
            {drafts.map((d) => (
              <li key={d.draft_id} className="flex items-center justify-between px-4 py-3 text-sm">
                <div>
                  <Link href={`/draft/${d.draft_id}`} className="font-medium hover:text-amber-300">
                    {d.draft_id}
                  </Link>
                  <div className="text-xs text-slate-400">
                    {d.num_teams} teams · you pick {d.user_team_index + 1} · {d.picks_made}/{d.total_picks} picks
                    {d.is_complete ? " · complete" : ""}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Link href={`/draft/${d.draft_id}`} className="rounded border border-white/10 px-2 py-1 hover:bg-white/5">
                    Open
                  </Link>
                  <button onClick={() => remove(d.draft_id)} className="rounded border border-white/10 px-2 py-1 text-red-300 hover:bg-white/5">
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
