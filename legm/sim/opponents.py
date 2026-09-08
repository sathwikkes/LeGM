"""Opponent model (Phase 6): how a simulated manager chooses.

Each opponent picks the candidate with the lowest *noisy consensus rank*:

    score = consensus_rank + N(0, adp_sigma) - needs_bonus * fills_open_starting_slot

Consensus rank is ADP when loaded, otherwise the player's rank by VORP on the
remaining pool. Illegal picks (roster cannot fit the player) are excluded.
The same model is used for the probability tables shown in the UI and for the
Monte Carlo survival simulation, so the two agree by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from legm.config.models import LeagueConfig, Position
from legm.draft.models import DraftState
from legm.draft.state import available_frame, is_legal_pick, team_roster


@dataclass(frozen=True)
class OpponentModel:
    adp_sigma: float = 6.0
    needs_bonus: float = 3.0
    candidate_window: int = 80

    @classmethod
    def from_config(cls, league: LeagueConfig) -> "OpponentModel":
        sim = league.simulation
        return cls(adp_sigma=sim.adp_sigma, needs_bonus=sim.needs_bonus, candidate_window=sim.candidate_window)


@dataclass
class Candidates:
    """The candidate window for a draft moment, in consensus-rank order."""

    player_ids: np.ndarray  # (C,)
    consensus_rank: np.ndarray  # (C,) float
    positions: list[tuple[Position, ...]]
    frame: pd.DataFrame  # available_frame rows for the candidates (index = player id)

    def index_of(self, player_id: int) -> int | None:
        hits = np.flatnonzero(self.player_ids == player_id)
        return int(hits[0]) if len(hits) else None


def consensus_ranks(frame: pd.DataFrame) -> pd.Series:
    """ADP when present, else the VORP-order rank on the remaining pool (1-indexed).
    Players without ADP slot in after the ADP-ranked players at their VORP rank."""
    vorp_rank = pd.Series(np.arange(1, len(frame) + 1, dtype=float), index=frame.index)
    adp = frame["ADP"].astype(float)
    return adp.where(adp.notna(), vorp_rank)


def build_candidates(state: DraftState, model: OpponentModel) -> Candidates:
    frame = available_frame(state, recompute_vorp=True)
    ranks = consensus_ranks(frame)
    order = ranks.sort_values(kind="stable").index[: model.candidate_window]
    sub = frame.loc[order]
    return Candidates(
        player_ids=np.asarray(order, dtype=np.int64),
        consensus_rank=ranks.loc[order].to_numpy(dtype=float),
        positions=[tuple(p) for p in sub["POSITION_LIST"]],
        frame=sub,
    )


@dataclass(frozen=True)
class TeamNeeds:
    open_positions: frozenset[Position]
    bench_open: bool


def team_needs(state: DraftState, team_index: int) -> TeamNeeds:
    r = team_roster(state, team_index)
    return TeamNeeds(open_positions=frozenset(r.open_positions), bench_open=r.open_bench > 0)


def team_adjustments(
    state: DraftState, team_index: int, cands: Candidates, model: OpponentModel
) -> tuple[np.ndarray, np.ndarray]:
    """(bonus, legal) arrays over candidates for one team at the current roster."""
    needs = team_needs(state, team_index)
    fills = np.array([bool(needs.open_positions & set(p)) for p in cands.positions])
    bonus = np.where(fills, model.needs_bonus, 0.0)
    if needs.bench_open:
        legal = np.ones(len(cands.player_ids), dtype=bool)
    else:
        legal = np.array([fills[i] or is_legal_pick(state, team_index, int(pid)) for i, pid in enumerate(cands.player_ids)])
    return bonus, legal


def pick_probabilities(
    state: DraftState, team_index: int, model: OpponentModel, n_draws: int = 2000, seed: int = 0, top: int = 5
) -> list[tuple[int, float]]:
    """Probability that `team_index`, picking now, takes each candidate. Top `top` by probability."""
    cands = build_candidates(state, model)
    if len(cands.player_ids) == 0:
        return []
    bonus, legal = team_adjustments(state, team_index, cands, model)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, model.adp_sigma, size=(n_draws, len(cands.player_ids)))
    scores = cands.consensus_rank[None, :] + noise - bonus[None, :]
    scores[:, ~legal] = np.inf
    chosen = scores.argmin(axis=1)
    counts = np.bincount(chosen, minlength=len(cands.player_ids)) / n_draws
    order = np.argsort(-counts)[:top]
    return [(int(cands.player_ids[i]), float(counts[i])) for i in order if counts[i] > 0]
