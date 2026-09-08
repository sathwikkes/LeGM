"use client";

import { forwardRef } from "react";
import { AvailablePlayer, fmt } from "@/lib/api";

const POSITIONS = ["", "PG", "SG", "SF", "PF", "C"];

type Props = {
  players: AvailablePlayer[];
  total: number;
  q: string;
  position: string;
  highlight: number;
  busy: boolean;
  canPick: boolean;
  selected: number[];
  onQuery: (q: string) => void;
  onPosition: (p: string) => void;
  onHighlight: (i: number) => void;
  onPick: (id: number) => void;
  onToggleSelect: (id: number) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
};

function returnColor(p: number | null) {
  if (p == null) return "text-slate-400";
  if (p < 0.35) return "text-red-300";
  if (p < 0.7) return "text-amber-300";
  return "text-emerald-300";
}

const AvailableTable = forwardRef<HTMLInputElement, Props>(function AvailableTable(
  { players, total, q, position, highlight, busy, canPick, selected, onQuery, onPosition, onHighlight, onPick, onToggleSelect, onKeyDown },
  ref,
) {
  return (
    <section className="flex min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Available</h2>
        <input
          ref={ref}
          value={q}
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search  ( / to focus, ↑↓ Enter to draft )"
          className="w-72 rounded border border-white/10 bg-[#0e1729] px-2 py-1 text-sm"
        />
        <div className="flex gap-1">
          {POSITIONS.map((p) => (
            <button key={p || "all"} onClick={() => onPosition(p)} className={`rounded px-2 py-1 text-xs ${position === p ? "bg-amber-500 text-black" : "border border-white/10 text-slate-300 hover:bg-white/5"}`}>
              {p || "All"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-slate-400">{total} available · tick 2–5 to compare</span>
      </div>
      <div className="overflow-auto rounded-lg border border-white/10 bg-[#0e1729]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-[#0e1729] text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-2 py-2"></th>
              <th className="px-2 py-2">Player</th>
              <th className="px-2 py-2">Pos</th>
              <th className="px-2 py-2">Team</th>
              <th className="px-2 py-2 text-right">GP</th>
              <th className="px-2 py-2 text-right">FP/G</th>
              <th className="px-2 py-2 text-right">Season</th>
              <th className="px-2 py-2 text-right" title="VORP recomputed on the remaining pool">VORP</th>
              <th className="px-2 py-2 text-right" title="Probability the player is still available at your next pick">P(ret)</th>
              <th className="px-2 py-2 text-right">ADP</th>
              <th className="px-2 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {players.map((p, i) => (
              <tr
                key={p.player_id}
                onMouseEnter={() => onHighlight(i)}
                onDoubleClick={() => canPick && !busy && onPick(p.player_id)}
                className={`border-t border-white/5 ${i === highlight ? "bg-amber-400/10" : ""} ${!p.legal_for_user ? "opacity-40" : ""}`}
              >
                <td className="px-2 py-1.5">
                  <input type="checkbox" checked={selected.includes(p.player_id)} onChange={() => onToggleSelect(p.player_id)} aria-label={`compare ${p.name}`} />
                </td>
                <td className="px-2 py-1.5">
                  <span className="font-medium">{p.name}</span>
                  {p.fills_open_slot && <span className="ml-2 rounded bg-emerald-500/20 px-1 text-[10px] text-emerald-300">fills slot</span>}
                  {p.injury_status && <span className="ml-2 rounded bg-red-500/20 px-1 text-[10px] text-red-300">{p.injury_status}</span>}
                </td>
                <td className="px-2 py-1.5 text-slate-300">{fmt.pos(p.positions)}</td>
                <td className="px-2 py-1.5 text-slate-300">{p.team ?? ""}</td>
                <td className="num px-2 py-1.5 text-right">{fmt.n0(p.gp)}</td>
                <td className="num px-2 py-1.5 text-right">{fmt.n1(p.fpg)}</td>
                <td className="num px-2 py-1.5 text-right">{fmt.n0(p.season_fp)}</td>
                <td className="num px-2 py-1.5 text-right">{fmt.n0(p.pool_vorp)}</td>
                <td className={`num px-2 py-1.5 text-right ${returnColor(p.p_return)}`}>{fmt.pct(p.p_return)}</td>
                <td className="num px-2 py-1.5 text-right text-slate-400">{fmt.n1(p.adp)}</td>
                <td className="px-2 py-1.5 text-right">
                  <button onClick={() => onPick(p.player_id)} disabled={busy || !canPick || !p.legal_for_user} className="rounded border border-white/10 px-2 py-0.5 text-xs hover:bg-amber-500 hover:text-black disabled:opacity-40">
                    Draft
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
});

export default AvailableTable;
