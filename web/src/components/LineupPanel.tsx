"use client";

import { useState } from "react";
import { api, BenchReason, Draft, fmt, Lineup } from "@/lib/api";

const REASON_LABEL: Record<BenchReason, string> = {
  no_game: "no game",
  ruled_out: "ruled out",
  outscored: "no slot",
};

// Today in US Eastern, which is how NBA game dates are keyed.
function todayEastern(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

function riskClass(p: number): string {
  if (p >= 1) return "text-slate-400";
  if (p >= 0.75) return "text-amber-300";
  return "text-red-300";
}

export default function LineupPanel({ draft }: { draft: Draft }) {
  const [team, setTeam] = useState(draft.config.user_team_index);
  const [date, setDate] = useState(todayEastern());
  const [lineup, setLineup] = useState<Lineup | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const optimize = async () => {
    setBusy(true);
    setError(null);
    try {
      setLineup(await api.lineup(draft.draft_id, { date, team }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLineup(null);
    } finally {
      setBusy(false);
    }
  };

  const stale = lineup !== null && (lineup.date !== date || lineup.team_index !== team);

  return (
    <section className="rounded-lg border border-white/10 bg-[#0e1729] p-3">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">Daily lineup</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded border border-white/10 bg-[#0b1220] px-2 py-1 text-sm"
        />
        <select
          value={team}
          onChange={(e) => setTeam(Number(e.target.value))}
          className="rounded border border-white/10 bg-[#0b1220] px-2 py-1 text-sm"
        >
          {draft.config.team_names.map((n, i) => (
            <option key={i} value={i}>
              {n}
              {i === draft.config.user_team_index ? " (you)" : ""}
            </option>
          ))}
        </select>
        <button
          onClick={optimize}
          disabled={busy}
          className="rounded bg-amber-500 px-3 py-1 text-sm font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          {busy ? "Optimizing…" : "Optimize lineup"}
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {lineup && !lineup.schedule_loaded && (
        <p className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
          No NBA schedule loaded. Run <code>legm ingest-schedule --season 2025-26</code> so the optimizer
          knows who is playing.
        </p>
      )}

      {lineup && (
        <>
          {stale && (
            <p className="mb-2 text-xs text-slate-500">
              Showing {lineup.team_name} on {lineup.date}. Press Optimize to refresh.
            </p>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="w-14 font-medium">Slot</th>
                <th className="font-medium">Player</th>
                <th className="w-14 font-medium">Opp</th>
                <th className="w-12 text-right font-medium">FP/G</th>
                <th className="w-12 text-right font-medium">xFP</th>
              </tr>
            </thead>
            <tbody>
              {lineup.slots.map((s) => (
                <tr key={s.slot} className="border-t border-white/5">
                  <td className="py-1 text-xs font-semibold uppercase text-slate-400">{s.slot}</td>
                  <td className="py-1">
                    {s.player ? (
                      <>
                        <span className="font-medium text-white">{s.player.name}</span>
                        <span className="ml-1 text-xs text-slate-400">{fmt.pos(s.player.positions)}</span>
                        {s.player.play_probability < 1 && (
                          <span className={`ml-1 text-xs ${riskClass(s.player.play_probability)}`}>
                            {s.player.injury_status ?? "risk"} · {fmt.pct(s.player.play_probability)}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-1 text-xs text-slate-400">{s.player?.opponent ?? ""}</td>
                  <td className="py-1 text-right text-slate-400">{s.player ? fmt.n1(s.player.fpg) : ""}</td>
                  <td className="py-1 text-right font-medium">{s.player ? fmt.n1(s.player.expected_points) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-2 text-xs text-slate-400">
            Expected <span className="font-semibold text-amber-300">{fmt.n1(lineup.expected_points)}</span> FP from{" "}
            {lineup.slots.filter((s) => s.player).length} starters · {lineup.games_scheduled} NBA games
            {lineup.empty_slots.length > 0 && <> · empty: {lineup.empty_slots.join(", ")}</>}
          </p>
          {lineup.points_left_on_bench > 0 && (
            <p className="text-xs text-slate-500">
              {fmt.n1(lineup.points_left_on_bench)} FP left on the bench to lineup congestion.
            </p>
          )}

          {lineup.bench.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs uppercase tracking-wide text-slate-500">
                Bench ({lineup.bench.length})
              </summary>
              <ul className="mt-1 space-y-0.5">
                {lineup.bench.map((b) => (
                  <li key={b.player.player_id} className="flex justify-between text-xs text-slate-400">
                    <span>
                      {b.player.name} <span className="text-slate-600">{fmt.pos(b.player.positions)}</span>
                    </span>
                    <span className={b.reason === "outscored" ? "text-slate-500" : "text-slate-600"}>
                      {REASON_LABEL[b.reason]}
                      {b.reason === "outscored" && ` · ${fmt.n1(b.player.expected_points)} xFP`}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
