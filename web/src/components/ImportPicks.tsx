"use client";

import { useState } from "react";
import { api, ImportReport } from "@/lib/api";

export default function ImportPicks({ draftId, onDone }: { draftId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("pick_number,player_name\n");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setError(null);
    try {
      const r = await api.importPicks(draftId, text.trim().startsWith("{") || text.trim().startsWith("[") ? "json" : "csv", text);
      setReport(r);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="rounded border border-white/10 px-3 py-1 text-sm hover:bg-white/5">
        Import picks
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-80 rounded-lg border border-white/10 bg-[#0e1729] p-3 text-xs shadow-xl">
          <p className="mb-1 text-slate-400">Paste CSV (pick_number, player_name) or JSON from Yahoo / a companion export. Picks apply in order from the current pick.</p>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} className="w-full rounded border border-white/10 bg-[#0b1220] p-1 font-mono" />
          <div className="mt-1 flex gap-2">
            <button onClick={submit} className="rounded bg-amber-500 px-2 py-1 font-semibold text-black">
              Apply
            </button>
            <button onClick={() => setOpen(false)} className="rounded border border-white/10 px-2 py-1">
              Close
            </button>
          </div>
          {error && <p className="mt-1 text-red-300">{error}</p>}
          {report && (
            <p className="mt-1 text-slate-300">
              Applied {report.applied}. {report.skipped.length > 0 && `Skipped: ${report.skipped.map((s) => `#${s.pick_number} ${s.player_name} (${s.reason})`).join("; ")}`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
