"use client";

import { Draft, fmt } from "@/lib/api";

function pickNumber(round: number, team: number, numTeams: number) {
  const offset = round % 2 === 1 ? team : numTeams - 1 - team;
  return (round - 1) * numTeams + offset + 1;
}

export default function DraftBoard({ draft }: { draft: Draft }) {
  const { num_teams, rounds, team_names, user_team_index } = draft.config;
  const byPick = new Map(draft.picks.map((p) => [p.pick_number, p]));
  const current = draft.clock.current_pick;
  return (
    <section className="overflow-auto rounded-lg border border-white/10 bg-[#0e1729]">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[#0e1729]">
          <tr>
            <th className="px-1 py-1 text-slate-400">Rd</th>
            {team_names.map((n, i) => (
              <th key={i} className={`px-1 py-1 ${i === user_team_index ? "text-amber-300" : "text-slate-300"}`}>
                {n}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rounds }, (_, r) => r + 1).map((round) => (
            <tr key={round} className="border-t border-white/5">
              <td className="num px-1 py-1 text-center text-slate-500">{round}</td>
              {team_names.map((_, t) => {
                const n = pickNumber(round, t, num_teams);
                const p = byPick.get(n);
                const isNow = n === current && !draft.clock.is_complete;
                return (
                  <td
                    key={t}
                    title={p ? `#${n} ${p.player.name}` : `#${n}`}
                    className={`h-8 px-1 py-0.5 text-center ${isNow ? "bg-amber-400/20 outline outline-1 outline-amber-400" : t === user_team_index ? "bg-amber-400/5" : ""}`}
                  >
                    {p ? (
                      <div className="truncate">
                        <div className="font-medium">{fmt.lastName(p.player.name)}</div>
                        <div className="text-[10px] text-slate-400">{fmt.pos(p.player.positions)}</div>
                      </div>
                    ) : (
                      <span className="num text-slate-600">{n}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
