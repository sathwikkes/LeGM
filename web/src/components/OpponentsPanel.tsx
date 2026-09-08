"use client";

import { useEffect, useState } from "react";
import { api, fmt, Opponents } from "@/lib/api";

export default function OpponentsPanel({ draftId, picksMade, isComplete }: { draftId: string; picksMade: number; isComplete: boolean }) {
  const [data, setData] = useState<Opponents | null>(null);
  useEffect(() => {
    if (isComplete) return;
    api.opponents(draftId).then(setData).catch(() => {});
  }, [draftId, picksMade, isComplete]);
  if (isComplete) return <p className="text-xs text-slate-400">Draft complete.</p>;
  if (!data) return <p className="text-xs text-slate-400">Loading…</p>;
  if (data.opponents.length === 0) return <p className="text-xs text-slate-400">You are on the clock: no opponents pick before you.</p>;
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500">Teams picking before your pick #{data.until_pick}, with their likely targets.</p>
      {data.opponents.map((o) => (
        <div key={o.team_index} className="rounded-lg border border-white/10 bg-[#0e1729] p-2 text-xs">
          <div className="flex items-baseline gap-2">
            <span className="font-semibold">{o.team_name}</span>
            <span className="text-slate-400">pick #{o.pick_number}</span>
            <span className="ml-auto text-slate-400">needs {o.open_positions.join(", ") || "bench only"}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {o.likely_targets.map((t) => (
              <span key={t.player.player_id} className="rounded bg-white/5 px-1.5 py-0.5">
                {fmt.lastName(t.player.name)} <span className="num text-slate-400">{fmt.pct(t.probability)}</span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
