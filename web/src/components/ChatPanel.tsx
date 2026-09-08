"use client";

import { useEffect, useRef, useState } from "react";
import { api, ChatMessage, LLMStatus } from "@/lib/api";

type Shown = ChatMessage & { tools?: string[] };

const SUGGESTIONS = ["Who should I draft?", "Can I wait a round for a center?", "Who is most likely to disappear before my next pick?", "Which position is getting scarce?"];

export default function ChatPanel({ draftId }: { draftId: string }) {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [messages, setMessages] = useState<Shown[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.llmStatus().then(setStatus).catch(() => setStatus({ available: false, model: "", tools: [] }));
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    const next: Shown[] = [...messages, { role: "user", content }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const out = await api.chat(
        draftId,
        next.map(({ role, content }) => ({ role, content })),
      );
      setMessages([...next, { role: "assistant", content: out.reply, tools: out.tool_calls.map((t) => t.name) }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col rounded-lg border border-white/10 bg-[#0e1729] p-3">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Assistant</h2>
        {status && (
          <span className={`text-[10px] ${status.available ? "text-emerald-300" : "text-slate-500"}`}>
            {status.available ? status.model : "offline: set ANTHROPIC_API_KEY on the API server"}
          </span>
        )}
      </div>
      <div className="max-h-72 min-h-24 space-y-2 overflow-auto text-sm">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} disabled={!status?.available || busy} className="rounded border border-white/10 px-2 py-0.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-40">
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`rounded px-2 py-1.5 ${m.role === "user" ? "bg-amber-400/10" : "bg-white/5"}`}>
            <div className="whitespace-pre-wrap">{m.content}</div>
            {m.tools && m.tools.length > 0 && <div className="mt-1 text-[10px] text-slate-500">tools: {m.tools.join(", ")}</div>}
          </div>
        ))}
        {busy && <div className="text-xs text-slate-400">Thinking…</div>}
        {error && <div className="text-xs text-red-300">{error}</div>}
        <div ref={endRef} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-2 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={status?.available ? "Ask about the draft…" : "Assistant offline"}
          disabled={!status?.available || busy}
          className="flex-1 rounded border border-white/10 bg-[#0b1220] px-2 py-1 text-sm disabled:opacity-50"
        />
        <button disabled={!status?.available || busy || !input.trim()} className="rounded bg-white/10 px-3 py-1 text-sm hover:bg-white/20 disabled:opacity-40">
          Send
        </button>
      </form>
    </section>
  );
}
