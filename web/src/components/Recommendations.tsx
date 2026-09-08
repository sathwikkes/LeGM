"use client";

import { Components, fmt, Recommendations as Recs } from "@/lib/api";

type Props = {
  recs: Recs | null;
  busy: boolean;
  canPick: boolean;
  onPick: (id: number) => void;
  onVote: (id: number, vote: 1 | -1) => void;
  voted: Record<number, 1 | -1>;
  teamName: string;
};

export default function Recommendations({ recs, busy, canPick, onPick, onVote, voted, teamName }: Props) {
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Recommended for {teamName}</h2>
        {recs?.until_pick && (
          <span className="text-xs text-slate-500">
            P(return) = chance of surviving to pick #{recs.until_pick} · {recs.n_sims} sims
          </span>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {(recs?.recommendations ?? []).map((r) => (
          <div key={r.player.player_id} className={`rounded-lg border p-3 ${r.rank === 1 ? "border-amber-400/60 bg-amber-400/5" : "border-white/10 bg-[#0e1729]"}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs text-slate-400">
                  #{r.rank} · score <span className="num font-semibold text-white">{fmt.n0(r.score)}</span>
                </div>
                <div className="font-semibold leading-tight">{r.player.name}</div>
                <div className="text-xs text-slate-300">
                  {fmt.pos(r.player.positions)} · {r.player.team}
                </div>
              </div>
              <div className="flex flex-col items-end gap-1">
                <button onClick={() => onPick(r.player.player_id)} disabled={busy || !canPick} className="rounded bg-amber-500 px-2 py-1 text-xs font-semibold text-black hover:bg-amber-400 disabled:opacity-40">
                  Draft
                </button>
                <div className="flex gap-1 text-xs">
                  <button title="Good recommendation" onClick={() => onVote(r.player.player_id, 1)} className={`rounded px-1.5 py-0.5 ${voted[r.player.player_id] === 1 ? "bg-emerald-500/30" : "hover:bg-white/10"}`}>
                    👍
                  </button>
                  <button title="Bad recommendation" onClick={() => onVote(r.player.player_id, -1)} className={`rounded px-1.5 py-0.5 ${voted[r.player.player_id] === -1 ? "bg-red-500/30" : "hover:bg-white/10"}`}>
                    👎
                  </button>
                </div>
              </div>
            </div>
            <dl className="mt-2 grid grid-cols-4 gap-1 text-center text-xs">
              <Stat label="FP/G" value={fmt.n1(r.components.fpg)} />
              <Stat label="Season" value={fmt.n0(r.components.season_fp)} />
              <Stat label="VORP" value={fmt.n0(r.components.pool_vorp)} />
              <Stat label="P(ret)" value={fmt.pct(r.components.p_return)} />
            </dl>
            <ComponentBars c={r.components} />
            <details className="mt-2 text-xs text-slate-300">
              <summary className="cursor-pointer text-slate-400">Why</summary>
              <ul className="mt-1 space-y-0.5">
                {r.reasons.map((reason, i) => (
                  <li key={i}>· {reason}</li>
                ))}
              </ul>
            </details>
          </div>
        ))}
        {recs && recs.recommendations.length === 0 && <p className="text-sm text-slate-400">No legal picks.</p>}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-white/5 py-1">
      <dt className="text-[10px] uppercase text-slate-400">{label}</dt>
      <dd className="num font-semibold">{value}</dd>
    </div>
  );
}

export function ComponentBars({ c }: { c: Components }) {
  const rows: [string, number, string][] = [
    ["value", c.value, "bg-amber-400"],
    ["fit", c.fit, "bg-emerald-400"],
    ["scarcity", c.scarcity, "bg-sky-400"],
    ["GP", c.gp_norm, "bg-violet-400"],
    ["upside", c.upside, "bg-pink-400"],
    ["injury", c.injury_risk, "bg-red-400"],
    ["conf.", c.confidence, "bg-slate-400"],
  ];
  return (
    <div className="mt-2 space-y-0.5">
      {rows.map(([label, v, color]) => (
        <div key={label} className="flex items-center gap-2 text-[10px] text-slate-400">
          <span className="w-12 text-right">{label}</span>
          <div className="h-1.5 flex-1 rounded bg-white/5">
            <div className={`h-1.5 rounded ${color}`} style={{ width: `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%` }} />
          </div>
          <span className="num w-8">{Math.round(v * 100)}</span>
        </div>
      ))}
    </div>
  );
}
