"use client";

import { useEffect, useState } from "react";
import { api, Compare, fmt } from "@/lib/api";

type Props = { draftId: string; ids: number[]; picksMade: number; onClear: () => void; onRemove: (id: number) => void };

export default function ComparePanel({ draftId, ids, picksMade, onClear, onRemove }: Props) {
  const [data, setData] = useState<Compare | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (ids.length < 2) return;
    api
      .compare(draftId, ids)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [draftId, ids, picksMade]);
  if (ids.length < 2) return null;
  const rows: [string, (c: Compare["players"][number]) => string][] = [
    ["Score", (p) => (p.components.score == null ? "—" : fmt.n0(p.components.score))],
    ["FP/G", (p) => fmt.n1(p.components.fpg)],
    ["Season FP", (p) => fmt.n0(p.components.season_fp)],
    ["Pool VORP", (p) => fmt.n0(p.components.pool_vorp)],
    ["GP", (p) => fmt.n0(p.components.gp)],
    ["Fills slot", (p) => (p.components.fit ? p.components.open_positions_filled.join("/") : "no")],
    ["Scarcity", (p) => fmt.pct(p.components.scarcity)],
    ["Injury", (p) => p.components.injury_status ?? "—"],
    ["Confidence", (p) => fmt.pct(p.components.confidence)],
    ["ADP", (p) => fmt.n1(p.components.adp) || "—"],
    ["P(return)", (p) => fmt.pct(p.components.p_return)],
  ];
  return (
    <section className="rounded-lg border border-sky-400/30 bg-[#0e1729] p-3">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Compare</h2>
        {data?.until_pick && <span className="text-xs text-slate-500">P(return) to pick #{data.until_pick}</span>}
        <button onClick={onClear} className="ml-auto text-xs text-slate-400 hover:text-white">
          clear
        </button>
      </div>
      {error && <p className="text-xs text-red-300">{error}</p>}
      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left text-slate-500"></th>
                {data.players.map((p) => (
                  <th key={p.player.player_id} className="px-2 py-1 text-left">
                    <div className="font-semibold">{p.player.name}</div>
                    <div className="font-normal text-slate-400">
                      {fmt.pos(p.player.positions)} · {p.player.team}
                      {p.drafted && <span className="ml-1 text-red-300">drafted</span>}
                    </div>
                    <button onClick={() => onRemove(p.player.player_id)} className="text-[10px] text-slate-500 hover:text-white">
                      remove
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, get]) => (
                <tr key={label} className="border-t border-white/5">
                  <td className="px-2 py-1 text-slate-400">{label}</td>
                  {data.players.map((p) => (
                    <td key={p.player.player_id} className="num px-2 py-1">
                      {get(p)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
