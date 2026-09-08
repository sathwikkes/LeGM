"use client";

import { Connection } from "@/lib/useDraft";
import { Draft } from "@/lib/api";
import ImportPicks from "./ImportPicks";

type Props = {
  draft: Draft;
  connection: Connection;
  busy: boolean;
  onUndo: () => void;
  onSimToMe: () => void;
  onSimAll: () => void;
  onImported: () => void;
};

export default function ClockBar({ draft, connection, busy, onUndo, onSimToMe, onSimAll, onImported }: Props) {
  const c = draft.clock;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-white/10 bg-[#0e1729] px-4 py-3">
      <div>
        <div className="text-xs uppercase text-slate-400">{draft.draft_id}</div>
        {c.is_complete ? (
          <div className="text-lg font-semibold text-emerald-300">Draft complete</div>
        ) : (
          <div className="text-lg font-semibold">
            Pick <span className="num">{c.current_pick}</span> · Round <span className="num">{c.current_round}</span>
          </div>
        )}
      </div>
      {!c.is_complete && (
        <div className={`rounded px-3 py-1 text-sm font-semibold ${c.is_user_turn ? "bg-amber-500 text-black" : "bg-white/10"}`}>
          {c.is_user_turn ? "You are on the clock" : `${c.team_name_on_the_clock} on the clock`}
        </div>
      )}
      {!c.is_complete && !c.is_user_turn && c.user_next_pick != null && (
        <div className="text-sm text-slate-300">
          Your next pick: <span className="num font-semibold text-white">#{c.user_next_pick}</span> ·{" "}
          <span className="num">{c.picks_before_user}</span> picks away
        </div>
      )}
      <div className="ml-auto flex items-center gap-2">
        <span
          title={connection}
          className={`h-2 w-2 rounded-full ${connection === "live" ? "bg-emerald-400" : connection === "connecting" ? "bg-amber-400" : "bg-red-400"}`}
        />
        <button onClick={onUndo} disabled={busy || draft.picks.length === 0} className="rounded border border-white/10 px-3 py-1 text-sm hover:bg-white/5 disabled:opacity-40">
          Undo
        </button>
        <button onClick={onSimToMe} disabled={busy || c.is_complete || c.is_user_turn} className="rounded border border-white/10 px-3 py-1 text-sm hover:bg-white/5 disabled:opacity-40">
          Sim to my pick
        </button>
        <button onClick={onSimAll} disabled={busy || c.is_complete} className="rounded border border-white/10 px-3 py-1 text-sm hover:bg-white/5 disabled:opacity-40">
          Sim rest
        </button>
        {!c.is_complete && <ImportPicks draftId={draft.draft_id} onDone={onImported} />}
      </div>
    </div>
  );
}
