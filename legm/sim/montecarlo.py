"""Monte Carlo survival (Phase 5): P(player is still available at the user's next pick).

Vectorized over simulations. For each of the K picks between now and the user's
next turn, every simulation draws noisy consensus ranks for the candidate
window and the team on the clock takes its lowest-scoring legal player.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from legm.draft.models import DraftState
from legm.draft.order import next_pick_for_team, pick_to_round_team
from legm.draft.state import current_pick, is_complete, team_on_the_clock
from legm.sim.opponents import Candidates, OpponentModel, build_candidates, team_adjustments


@dataclass
class SurvivalResult:
    from_pick: int
    until_pick: int | None
    n_sims: int
    picks_between: list[tuple[int, int]]  # (pick_number, team_index)
    probabilities: dict[int, float] = field(default_factory=dict)  # player_id -> P(available)

    def p(self, player_id: int) -> float:
        """Players outside the candidate window are assumed to survive."""
        return self.probabilities.get(player_id, 1.0)


def picks_until_user_turn(state: DraftState) -> tuple[int, int | None, list[tuple[int, int]]]:
    """(from_pick, user_next_pick, opponent picks in between).

    If the user is on the clock now, the window starts at the following pick:
    the question is "if I pass on X now, is X there at my *next* turn".
    """
    if is_complete(state):
        return current_pick(state), None, []
    cfg = state.config
    start = current_pick(state)
    if team_on_the_clock(state) == cfg.user_team_index:
        start += 1
    until = next_pick_for_team(cfg.user_team_index, start, cfg.num_teams, cfg.rounds)
    if until is None:
        return start, None, []
    between = [(p, pick_to_round_team(p, cfg.num_teams)[1]) for p in range(start, until)]
    return start, until, between


def survival(
    state: DraftState,
    model: OpponentModel,
    n_sims: int = 500,
    seed: int = 0,
    candidates: Candidates | None = None,
) -> SurvivalResult:
    start, until, between = picks_until_user_turn(state)
    cands = candidates if candidates is not None else build_candidates(state, model)
    result = SurvivalResult(from_pick=start, until_pick=until, n_sims=n_sims, picks_between=between)
    C = len(cands.player_ids)
    if C == 0:
        return result
    if not between:
        result.probabilities = {int(pid): 1.0 for pid in cands.player_ids}
        return result

    # If the user is on the clock, the player they take now is unknown; the
    # simulation leaves the whole window available and lets opponents pick.
    per_team: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for _, team in between:
        if team not in per_team:
            per_team[team] = team_adjustments(state, team, cands, model)

    rng = np.random.default_rng(seed)
    available = np.ones((n_sims, C), dtype=bool)
    base = cands.consensus_rank[None, :]
    for _, team in between:
        bonus, legal = per_team[team]
        scores = base + rng.normal(0.0, model.adp_sigma, size=(n_sims, C)) - bonus[None, :]
        scores = np.where(available & legal[None, :], scores, np.inf)
        chosen = scores.argmin(axis=1)
        has_choice = np.isfinite(scores[np.arange(n_sims), chosen])
        available[np.arange(n_sims)[has_choice], chosen[has_choice]] = False

    probs = available.mean(axis=0)
    result.probabilities = {int(pid): float(p) for pid, p in zip(cands.player_ids, probs, strict=True)}
    return result
