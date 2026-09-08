"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Draft, getToken, WS_URL } from "./api";

export type Connection = "connecting" | "live" | "offline";

/** Authoritative draft state for one draft: initial GET, then WebSocket pushes, polling fallback. */
export function useDraft(draftId: string) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<Connection>("connecting");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .draft(draftId)
      .then((d) => !cancelled && setDraft(d))
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [draftId]);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let poll: ReturnType<typeof setInterval> | undefined;

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(`${WS_URL}/ws/drafts/${draftId}?token=${encodeURIComponent(getToken() ?? "")}`);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setConnection("live");
        if (poll) clearInterval(poll);
        poll = undefined;
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "draft") setDraft(msg.draft as Draft);
      };
      ws.onclose = (ev) => {
        if (closed || ev.code === 4401 || ev.code === 4404) return; // auth/not-found: don't retry
        setConnection("offline");
        if (!poll) poll = setInterval(() => api.draft(draftId).then(setDraft).catch(() => {}), 3000);
        timer = setTimeout(connect, Math.min(10000, 500 * 2 ** retry++));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      if (poll) clearInterval(poll);
      wsRef.current?.close();
    };
  }, [draftId]);

  const run = useCallback(async (fn: () => Promise<Draft>) => {
    setBusy(true);
    setError(null);
    try {
      const d = await fn();
      setDraft(d);
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const pick = useCallback((playerId: number) => run(() => api.pick(draftId, playerId)), [draftId, run]);
  const undo = useCallback(() => run(() => api.undo(draftId)), [draftId, run]);
  const simulate = useCallback(
    (untilUser: boolean, seed?: number) =>
      run(() => api.simulate(draftId, { strategy: "needs", jitter: 3, seed: seed ?? null, until_user: untilUser })),
    [draftId, run],
  );

  const refresh = useCallback(() => {
    api.draft(draftId).then(setDraft).catch(() => {});
  }, [draftId]);

  return { draft, error, busy, connection, pick, undo, simulate, refresh, clearError: () => setError(null) };
}
