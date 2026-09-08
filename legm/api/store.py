"""Per-user draft storage in the database (drafts table, JSON blob), with per-draft locks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine

from legm.data.db import session_scope
from legm.data.models import DraftRecord
from legm.draft.models import DraftState


class DraftNotFound(KeyError):
    pass


class DraftExists(ValueError):
    pass


class DraftStore:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._cache: dict[tuple[int, str], DraftState] = {}
        self._locks: dict[tuple[int, str], threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, owner_id: int, draft_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault((owner_id, draft_id), threading.Lock())

    def ids(self, owner_id: int) -> list[tuple[str, datetime]]:
        """(draft_id, updated_at) for the owner, most recently updated first."""
        with session_scope(self.engine) as s:
            rows = s.execute(
                select(DraftRecord.draft_id, DraftRecord.updated_at)
                .where(DraftRecord.owner_id == owner_id)
                .order_by(DraftRecord.updated_at.desc())
            ).all()
        return [(d, t) for d, t in rows]

    def get(self, owner_id: int, draft_id: str) -> DraftState:
        key = (owner_id, draft_id)
        if key in self._cache:
            return self._cache[key]
        with session_scope(self.engine) as s:
            rec = s.execute(
                select(DraftRecord).where(DraftRecord.owner_id == owner_id, DraftRecord.draft_id == draft_id)
            ).scalar_one_or_none()
            if rec is None:
                raise DraftNotFound(draft_id)
            state = DraftState.model_validate_json(rec.state_json)
        self._cache[key] = state
        return state

    def _write(self, s, owner_id: int, state: DraftState) -> None:
        rec = s.execute(
            select(DraftRecord).where(DraftRecord.owner_id == owner_id, DraftRecord.draft_id == state.draft_id)
        ).scalar_one_or_none()
        if rec is None:
            rec = DraftRecord(owner_id=owner_id, draft_id=state.draft_id, state_json="", picks_made=0)
            s.add(rec)
        rec.state_json = state.model_dump_json()
        rec.picks_made = len(state.picks)

    def create(self, owner_id: int, state: DraftState) -> DraftState:
        with self._lock(owner_id, state.draft_id):
            with session_scope(self.engine) as s:
                exists = s.execute(
                    select(DraftRecord.id).where(DraftRecord.owner_id == owner_id, DraftRecord.draft_id == state.draft_id)
                ).scalar_one_or_none()
                if exists is not None:
                    raise DraftExists(state.draft_id)
                self._write(s, owner_id, state)
            self._cache[(owner_id, state.draft_id)] = state
        return state

    def update(self, owner_id: int, draft_id: str, fn: Callable[[DraftState], DraftState]) -> DraftState:
        with self._lock(owner_id, draft_id):
            state = fn(self.get(owner_id, draft_id))
            with session_scope(self.engine) as s:
                self._write(s, owner_id, state)
            self._cache[(owner_id, draft_id)] = state
            return state

    def delete(self, owner_id: int, draft_id: str) -> None:
        with self._lock(owner_id, draft_id):
            with session_scope(self.engine) as s:
                rec = s.execute(
                    select(DraftRecord).where(DraftRecord.owner_id == owner_id, DraftRecord.draft_id == draft_id)
                ).scalar_one_or_none()
                if rec is None:
                    raise DraftNotFound(draft_id)
                s.delete(rec)
            self._cache.pop((owner_id, draft_id), None)
