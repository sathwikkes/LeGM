"""WebSocket fan-out: every connected client of a draft receives the full DraftOut after each change."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class DraftHub:
    def __init__(self) -> None:
        self._clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, draft_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients[draft_id].add(ws)

    async def disconnect(self, draft_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[draft_id].discard(ws)

    def client_count(self, draft_id: str) -> int:
        return len(self._clients.get(draft_id, ()))

    async def broadcast(self, draft_id: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._clients.get(draft_id, ()))
        dead = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients[draft_id].discard(ws)
