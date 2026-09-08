"use client";

import { useState } from "react";
import { Draft, fmt } from "@/lib/api";

export default function RosterPanel({ draft }: { draft: Draft }) {
  const [team, setTeam] = useState(draft.config.user_team_index);
  const roster = draft.rosters[team];
  return (
    <section className="rounded-lg border border-white/10 bg-[#0e1729] p-3">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Roster</h2>
        <select value={team} onChange={(e) => setTeam(Number(e.target.value))} className="rounded border border-white/10 bg-[#0b1220] px-2 py-0.5 text-sm">
          {draft.config.team_names.map((n, i) => (
            <option key={i} value={i}>
              {n}
              {i === draft.config.user_team_index ? " (you)" : ""}
            </option>
          ))}
        </select>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {roster.slots.map((s) => (
            <tr key={s.slot} className={`border-t border-white/5 ${s.kind !== "start" ? "text-slate-400" : ""}`}>
              <td className="w-14 py-1 text-xs font-semibold uppercase text-slate-400">{s.slot}</td>
              <td className="py-1">
                {s.player ? (
                  <>
                    <span className="font-medium text-white">{s.player.name}</span>
                    <span className="ml-1 text-xs text-slate-400">
                      {fmt.pos(s.player.positions)} · {fmt.n1(s.player.fpg)} FP/G
                    </span>
                  </>
                ) : (
                  <span className="text-slate-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-400">
        Open starters: {roster.open_positions.length ? roster.open_positions.join(", ") : "none"} · bench open: {roster.open_bench}
      </p>
    </section>
  );
}
