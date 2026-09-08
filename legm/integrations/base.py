"""Draft source adapters (Phase 8).

A DraftSource yields external picks (from Yahoo, a browser companion, or a
file) that the API applies to the local DraftState. The local state stays
authoritative: adapters only *suggest* picks, and every applied pick goes
through the same make_pick validation as a manual one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from legm.data.names import normalize_name
from legm.draft.models import DraftState
from legm.draft.state import DraftError, current_pick, make_pick


@dataclass(frozen=True)
class ExternalPick:
    pick_number: int
    player_name: str
    player_id: int | None = None  # nba_id when the source knows it
    team_name: str | None = None
    source: str = "external"


class DraftSource(Protocol):
    name: str

    def poll(self) -> list[ExternalPick]:
        """All picks the source currently knows about, in pick order."""
        ...


@dataclass
class SyncReport:
    applied: list[ExternalPick] = field(default_factory=list)
    skipped: list[tuple[ExternalPick, str]] = field(default_factory=list)

    @property
    def applied_count(self) -> int:
        return len(self.applied)


def resolve_player_id(state: DraftState, pick: ExternalPick) -> int | None:
    if pick.player_id is not None and pick.player_id in state.pool:
        return pick.player_id
    q = normalize_name(pick.player_name)
    exact = [c.player_id for c in state.pool.values() if normalize_name(c.name) == q]
    if len(exact) == 1:
        return exact[0]
    partial = [c.player_id for c in state.pool.values() if q in normalize_name(c.name)]
    return partial[0] if len(partial) == 1 else None


def apply_external_picks(state: DraftState, picks: list[ExternalPick]) -> tuple[DraftState, SyncReport]:
    """Apply picks whose pick_number matches the next local pick; skip the rest with a reason.

    Picks already reflected locally (pick_number < current) are ignored silently
    unless they disagree, in which case they are reported as conflicts.
    """
    report = SyncReport()
    local = {p.pick_number: p.player_id for p in state.picks}
    for ext in sorted(picks, key=lambda p: p.pick_number):
        pid = resolve_player_id(state, ext)
        if ext.pick_number < current_pick(state):
            if pid is not None and local.get(ext.pick_number) != pid:
                report.skipped.append((ext, f"conflict: local pick {ext.pick_number} is a different player"))
            continue
        if ext.pick_number != current_pick(state):
            report.skipped.append((ext, f"out of order: expected pick {current_pick(state)}"))
            continue
        if pid is None:
            report.skipped.append((ext, f"unresolved player {ext.player_name!r}"))
            continue
        try:
            state = make_pick(state, pid)
        except DraftError as exc:
            report.skipped.append((ext, str(exc)))
            continue
        report.applied.append(ext)
    return state, report
