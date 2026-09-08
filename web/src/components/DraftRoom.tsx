"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Available, Recommendations as Recs } from "@/lib/api";
import { useDraft } from "@/lib/useDraft";
import AvailableTable from "./AvailableTable";
import ChatPanel from "./ChatPanel";
import ClockBar from "./ClockBar";
import ComparePanel from "./ComparePanel";
import DraftBoard from "./DraftBoard";
import OpponentsPanel from "./OpponentsPanel";
import Recommendations from "./Recommendations";
import RosterPanel from "./RosterPanel";

export default function DraftRoom({ draftId }: { draftId: string }) {
  const { draft, error, busy, connection, pick, undo, simulate, refresh, clearError } = useDraft(draftId);
  const [available, setAvailable] = useState<Available | null>(null);
  const [recs, setRecs] = useState<Recs | null>(null);
  const [q, setQ] = useState("");
  const [position, setPosition] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [voted, setVoted] = useState<Record<number, 1 | -1>>({});
  const [tab, setTab] = useState<"board" | "log" | "opponents">("board");
  const searchRef = useRef<HTMLInputElement>(null);

  const picksMade = draft?.picks.length ?? -1;
  const clockTeam = draft?.clock.team_on_the_clock ?? null;

  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(() => {
      api
        .available(draftId, { q, position, limit: 100 })
        .then((a) => {
          setAvailable(a);
          setHighlight(0);
        })
        .catch(() => {});
    }, 120);
    return () => clearTimeout(t);
  }, [draftId, picksMade, q, position, draft]);

  useEffect(() => {
    if (!draft || draft.clock.is_complete) return;
    api.recommendations(draftId, 3).then(setRecs).catch(() => {});
  }, [draftId, picksMade, clockTeam, draft]);

  const doPick = useCallback(
    async (id: number) => {
      const next = await pick(id);
      if (next) {
        setQ("");
        setPosition("");
        setSelected((s) => s.filter((x) => x !== id));
      }
    },
    [pick],
  );

  const vote = useCallback(
    async (id: number, v: 1 | -1) => {
      setVoted((m) => ({ ...m, [id]: v }));
      try {
        await api.feedback(draftId, id, v);
        const r = await api.recommendations(draftId, 3);
        setRecs(r);
      } catch {
        /* keep local mark */
      }
    },
    [draftId],
  );

  const toggleSelect = useCallback((id: number) => {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 5 ? s : [...s, id]));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== searchRef.current) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = available?.players.length ?? 0;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(n - 1, h + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const p = available?.players[highlight];
      if (p && !busy && draft && !draft.clock.is_complete && p.legal_for_user) doPick(p.player_id);
    } else if (e.key === "Escape") {
      setQ("");
      searchRef.current?.blur();
    }
  };

  if (error && !draft) return <p className="text-red-400">{error}</p>;
  if (!draft) return <p className="text-slate-400">Loading draft…</p>;

  const canPick = !draft.clock.is_complete;
  const teamName = draft.clock.team_name_on_the_clock ?? "";

  return (
    <div className="space-y-4">
      <ClockBar draft={draft} connection={connection} busy={busy} onUndo={undo} onSimToMe={() => simulate(true)} onSimAll={() => simulate(false)} onImported={refresh} />
      {error && (
        <div className="flex items-center justify-between rounded border border-red-400/40 bg-red-400/10 px-3 py-2 text-sm text-red-200">
          <span>{error}</span>
          <button onClick={clearError} className="text-xs underline">
            dismiss
          </button>
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-4">
          {!draft.clock.is_complete && (
            <Recommendations recs={recs} busy={busy} canPick={canPick} onPick={doPick} onVote={vote} voted={voted} teamName={draft.clock.is_user_turn ? "you" : teamName} />
          )}
          <ComparePanel draftId={draftId} ids={selected} picksMade={picksMade} onClear={() => setSelected([])} onRemove={(id) => setSelected((s) => s.filter((x) => x !== id))} />
          <AvailableTable
            ref={searchRef}
            players={available?.players ?? []}
            total={available?.total ?? 0}
            q={q}
            position={position}
            highlight={highlight}
            busy={busy}
            canPick={canPick}
            selected={selected}
            onQuery={setQ}
            onPosition={setPosition}
            onHighlight={setHighlight}
            onPick={doPick}
            onToggleSelect={toggleSelect}
            onKeyDown={onSearchKey}
          />
        </div>
        <div className="space-y-4">
          <ChatPanel draftId={draftId} />
          <RosterPanel draft={draft} />
          <div>
            <div className="mb-2 flex gap-2 text-xs">
              {(["board", "log", "opponents"] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={`rounded px-2 py-1 capitalize ${tab === t ? "bg-white/10" : "text-slate-400"}`}>
                  {t === "log" ? "Pick log" : t}
                </button>
              ))}
            </div>
            {tab === "board" && <DraftBoard draft={draft} />}
            {tab === "opponents" && <OpponentsPanel draftId={draftId} picksMade={picksMade} isComplete={draft.clock.is_complete} />}
            {tab === "log" && (
              <ol className="max-h-[520px] overflow-auto rounded-lg border border-white/10 bg-[#0e1729] text-sm">
                {[...draft.picks].reverse().map((p) => (
                  <li key={p.pick_number} className="flex gap-2 border-t border-white/5 px-3 py-1">
                    <span className="num w-8 text-slate-500">{p.pick_number}</span>
                    <span className="w-20 truncate text-slate-400">{p.team_name}</span>
                    <span className="font-medium">{p.player.name}</span>
                    <span className="text-xs text-slate-400">{p.player.positions.join("/")}</span>
                  </li>
                ))}
                {draft.picks.length === 0 && <li className="px-3 py-2 text-slate-400">No picks yet.</li>}
              </ol>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
