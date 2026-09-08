"use client";

import { useEffect, useState } from "react";
import { api, fmt, Player } from "@/lib/api";

const POSITIONS = ["", "PG", "SG", "SF", "PF", "C"];

export default function RankingsTable() {
  const [players, setPlayers] = useState<Player[]>([]);
  const [q, setQ] = useState("");
  const [position, setPosition] = useState("");
  const [inactive, setInactive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .players({ top: 300, q, position, include_inactive: inactive })
        .then(setPlayers)
        .catch((e) => setError(e.message));
    }, 150);
    return () => clearTimeout(t);
  }, [q, position, inactive]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Rankings</h1>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search player"
          className="rounded border border-white/10 bg-[#0e1729] px-2 py-1 text-sm"
        />
        <div className="flex gap-1">
          {POSITIONS.map((p) => (
            <button
              key={p || "all"}
              onClick={() => setPosition(p)}
              className={`rounded px-2 py-1 text-xs ${position === p ? "bg-amber-500 text-black" : "border border-white/10 text-slate-300 hover:bg-white/5"}`}
            >
              {p || "All"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-xs text-slate-300">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          include players with no games last season
        </label>
      </div>
      {error && <p className="mb-2 text-sm text-red-400">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-white/10 bg-[#0e1729]">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Pos</th>
              <th className="px-3 py-2">Team</th>
              <th className="px-3 py-2 text-right">GP</th>
              <th className="px-3 py-2 text-right">FP/G</th>
              <th className="px-3 py-2 text-right">Season FP</th>
              <th className="px-3 py-2 text-right">VORP</th>
              <th className="px-3 py-2 text-right">ADP</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p, i) => (
              <tr key={p.player_id} className="border-t border-white/5 hover:bg-white/5">
                <td className="num px-3 py-1.5 text-slate-400">{i + 1}</td>
                <td className="px-3 py-1.5 font-medium">{p.name}</td>
                <td className="px-3 py-1.5 text-slate-300">{fmt.pos(p.positions)}</td>
                <td className="px-3 py-1.5 text-slate-300">{p.team ?? ""}</td>
                <td className="num px-3 py-1.5 text-right">{fmt.n0(p.gp)}</td>
                <td className="num px-3 py-1.5 text-right">{fmt.n1(p.fpg)}</td>
                <td className="num px-3 py-1.5 text-right">{fmt.n0(p.season_fp)}</td>
                <td className="num px-3 py-1.5 text-right">{fmt.n0(p.vorp)}</td>
                <td className="num px-3 py-1.5 text-right text-slate-400">{fmt.n1(p.adp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
