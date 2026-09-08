"""Run a full or partial mock draft with one strategy per team."""

from __future__ import annotations

import random
from collections.abc import Mapping

from legm.draft.models import DraftState
from legm.draft.state import current_pick, is_complete, make_pick, team_on_the_clock, user_next_pick
from legm.draft.strategies import BestAvailable, Strategy


def simulate(
    state: DraftState,
    strategies: Mapping[int, Strategy] | None = None,
    default: Strategy | None = None,
    seed: int | None = 0,
    until_pick: int | None = None,
    stop_before_user: bool = False,
) -> DraftState:
    """Advance the draft by letting strategies pick.

    strategies: team_index -> Strategy; teams not listed use `default`.
    until_pick: stop when this pick number is on the clock (exclusive).
    stop_before_user: stop when the user's team is on the clock.
    """
    rng = random.Random(seed)
    default = default or BestAvailable()
    strategies = dict(strategies or {})
    while not is_complete(state):
        pick_no = current_pick(state)
        if until_pick is not None and pick_no >= until_pick:
            break
        team = team_on_the_clock(state)
        if stop_before_user and team == state.config.user_team_index:
            break
        strategy = strategies.get(team, default)
        state = make_pick(state, strategy(state, team, rng))
    return state


def simulate_until_user(state: DraftState, seed: int | None = 0, **kwargs) -> DraftState:
    """Convenience: advance to the user's next pick."""
    nxt = user_next_pick(state)
    if nxt is None:
        return state
    return simulate(state, seed=seed, until_pick=nxt, **kwargs)
