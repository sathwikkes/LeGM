"""Roster slots and legality.

A roster is a list of Slot objects built from the league config. Starting
slots accept players by positional eligibility, bench slots accept anyone,
IL slots are never fillable during a draft.

Assignment is a maximum bipartite matching of players to starting slots
(Kuhn's algorithm); everyone unmatched goes to the bench. A set of players
fits a roster iff the unmatched count is at most the bench size. Because
the matching is recomputed from scratch each time, an earlier player can
shift slots (PG -> G) to make room for a new one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from legm.config.models import LeagueConfig, Position

SlotKind = Literal["start", "bench", "il"]


@dataclass(frozen=True)
class Slot:
    label: str
    kind: SlotKind
    positions: tuple[Position, ...]  # empty for bench/il: anyone fits

    def accepts(self, positions: Iterable[Position]) -> bool:
        if self.kind == "bench":
            return True
        if self.kind == "il":
            return False
        if set(self.positions) >= set(Position):  # UTIL takes anyone, even with no eligibility
            return True
        return any(p in self.positions for p in positions)


def build_slots(config: LeagueConfig) -> list[Slot]:
    """Unique-labelled slots: duplicates are numbered (C1, C2, UTIL1, UTIL2)."""
    counts: dict[str, int] = {}
    for s in config.roster.slots:
        counts[s] = counts.get(s, 0) + 1
    seen: dict[str, int] = {}
    slots: list[Slot] = []
    for s in config.roster.slots:
        seen[s] = seen.get(s, 0) + 1
        label = f"{s}{seen[s]}" if counts[s] > 1 else s
        slots.append(Slot(label, "start", config.roster.slot_positions(s)))
    for i in range(1, config.roster.bench + 1):
        slots.append(Slot(f"BN{i}", "bench", ()))
    for i in range(1, config.roster.il + 1):
        slots.append(Slot(f"IL{i}", "il", ()))
    return slots


def draftable_slots(slots: Sequence[Slot]) -> int:
    return sum(1 for s in slots if s.kind != "il")


def _specificity_order(slots: Sequence[Slot]) -> list[int]:
    """Indexes of starting slots, most specific (fewest eligible positions) first."""
    starts = [i for i, s in enumerate(slots) if s.kind == "start"]
    return sorted(starts, key=lambda i: (len(slots[i].positions), i))


def match_starters(
    players: Mapping[int, Sequence[Position]],
    slots: Sequence[Slot],
) -> dict[int, int]:
    """Maximum matching of player_id -> starting slot index.

    Players are processed in insertion order (draft order); slots are tried
    most-specific first so a PG lands in PG before G before UTIL.
    """
    order = _specificity_order(slots)
    slot_to_player: dict[int, int] = {}

    def try_place(pid: int, visited: set[int]) -> bool:
        eligible = [si for si in order if si not in visited and slots[si].accepts(players[pid])]
        # Prefer a free slot so earlier players keep theirs; only then displace.
        for si in eligible:
            if si not in slot_to_player:
                slot_to_player[si] = pid
                return True
        for si in eligible:
            visited.add(si)
            if try_place(slot_to_player[si], visited):
                slot_to_player[si] = pid
                return True
        return False

    for pid in players:
        try_place(pid, set())
    return {pid: si for si, pid in slot_to_player.items()}


def assign(players: Mapping[int, Sequence[Position]], slots: Sequence[Slot]) -> dict[str, int | None] | None:
    """Slot label -> player_id (None for empty). Returns None if the players do not fit."""
    matched = match_starters(players, slots)
    bench = [s for s in slots if s.kind == "bench"]
    leftover = [pid for pid in players if pid not in matched]
    if len(leftover) > len(bench):
        return None
    out: dict[str, int | None] = {s.label: None for s in slots}
    for pid, si in matched.items():
        out[slots[si].label] = pid
    for slot, pid in zip(bench, leftover, strict=False):
        out[slot.label] = pid
    return out


def fits(players: Mapping[int, Sequence[Position]], slots: Sequence[Slot]) -> bool:
    return assign(players, slots) is not None


def can_add(
    players: Mapping[int, Sequence[Position]],
    new_pid: int,
    new_positions: Sequence[Position],
    slots: Sequence[Slot],
) -> bool:
    if new_pid in players:
        return False
    trial = dict(players)
    trial[new_pid] = tuple(new_positions)
    return fits(trial, slots)


def open_starting_slots(players: Mapping[int, Sequence[Position]], slots: Sequence[Slot]) -> list[Slot]:
    matched = set(match_starters(players, slots).values())
    return [s for i, s in enumerate(slots) if s.kind == "start" and i not in matched]


def open_positions(players: Mapping[int, Sequence[Position]], slots: Sequence[Slot]) -> list[Position]:
    """Positions for which one more single-position player would fill a starting slot."""
    base = len(match_starters(players, slots))
    out = []
    for pos in Position:
        trial = dict(players)
        trial[-1] = (pos,)
        if len(match_starters(trial, slots)) > base:
            out.append(pos)
    return out


def open_bench_slots(players: Mapping[int, Sequence[Position]], slots: Sequence[Slot]) -> int:
    matched = match_starters(players, slots)
    bench = sum(1 for s in slots if s.kind == "bench")
    return bench - (len(players) - len(matched))
