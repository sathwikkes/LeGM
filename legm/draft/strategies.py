"""Deterministic opponent strategies for simulated drafts.

A Strategy is a callable (state, team_index, rng) -> player_id. Each picks
from the legal, available players. `jitter` widens the choice to a uniform
pick among the top-N candidates so seeded simulations vary reproducibly.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from legm.draft.models import DraftState, PlayerCard
from legm.draft.state import DraftError, available, is_legal_pick

Strategy = Callable[[DraftState, int, random.Random], int]

ADP_UNKNOWN = 10_000.0


def legal_candidates(state: DraftState, team_index: int) -> list[PlayerCard]:
    from legm.draft.state import team_roster

    cands = available(state)
    if team_roster(state, team_index).open_bench > 0:
        return cands  # bench takes anyone, so every available player is legal
    return [c for c in cands if is_legal_pick(state, team_index, c.player_id)]


def _choose(cands: list[PlayerCard], rng: random.Random, jitter: int) -> int:
    if not cands:
        raise DraftError("no legal players available")
    top = cands[: max(1, jitter)]
    return rng.choice(top).player_id if len(top) > 1 else top[0].player_id


@dataclass(frozen=True)
class BestAvailable:
    """Highest pool VORP, ties by season FP."""

    jitter: int = 1

    def __call__(self, state: DraftState, team_index: int, rng: random.Random) -> int:
        return _choose(legal_candidates(state, team_index), rng, self.jitter)


@dataclass(frozen=True)
class AdpOrder:
    """Lowest ADP first; players without ADP fall behind everyone with one, ordered by VORP."""

    jitter: int = 1

    def __call__(self, state: DraftState, team_index: int, rng: random.Random) -> int:
        cands = legal_candidates(state, team_index)
        cands.sort(key=lambda c: (c.adp if c.adp is not None else ADP_UNKNOWN, -c.vorp))
        return _choose(cands, rng, self.jitter)


@dataclass(frozen=True)
class NeedsAware:
    """Best available among players who fill an open starting slot; bench players
    only once every starting slot is filled."""

    jitter: int = 1

    def __call__(self, state: DraftState, team_index: int, rng: random.Random) -> int:
        from legm.draft.state import team_roster

        roster = team_roster(state, team_index)
        cands = legal_candidates(state, team_index)
        if roster.open_positions:
            needed = set(roster.open_positions)
            starters = [c for c in cands if needed & set(c.positions)]
            if starters:
                return _choose(starters, rng, self.jitter)
        return _choose(cands, rng, self.jitter)


STRATEGIES: dict[str, type] = {
    "best_available": BestAvailable,
    "adp": AdpOrder,
    "needs": NeedsAware,
}


def make_strategy(name: str, jitter: int = 1) -> Strategy:
    try:
        return STRATEGIES[name](jitter=jitter)
    except KeyError as exc:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}") from exc
