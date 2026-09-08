"""Replacement level and Value Over Replacement Player.

Replacement level for position P is the N-th best season FP among players
eligible at P, where
    N = num_teams * (number of starting slots a P-eligible player may fill).
Multi-position players count toward every position they are eligible at.
Overall replacement level uses N = num_teams * total starting slots across
all players.

A player's VORP is season FP minus the LOWEST replacement level among their
eligible positions: multi-eligibility is an asset, so a player is valued
against the position where they are hardest to replace.

Inputs are plain pandas objects so the functions stay pure and testable.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from legm.config.models import LeagueConfig, Position

OVERALL = "OVERALL"


def nth_best(values: Iterable[float], n: int) -> float:
    """The n-th largest value (1-indexed). If fewer than n values, the smallest.
    Empty input returns 0.0."""
    ordered = sorted((float(v) for v in values), reverse=True)
    if not ordered:
        return 0.0
    if n < 1:
        raise ValueError("n must be >= 1")
    return ordered[min(n, len(ordered)) - 1]


def replacement_levels(
    season_fp: pd.Series,
    positions: pd.Series,
    config: LeagueConfig,
) -> dict[str, float]:
    """Replacement level per position plus OVERALL.

    season_fp: season fantasy points indexed by player id.
    positions:  iterable of Position per player, same index.
    """
    if not season_fp.index.equals(positions.index):
        positions = positions.reindex(season_fp.index)
    teams = config.league.num_teams
    levels: dict[str, float] = {}
    for pos in Position:
        slots = config.roster.starting_slots_for(pos)
        if slots == 0:
            continue
        eligible_mask = positions.map(lambda ps, p=pos: p in set(ps or ()))
        levels[pos.value] = nth_best(season_fp[eligible_mask.fillna(False)], teams * slots)
    levels[OVERALL] = nth_best(season_fp, teams * config.roster.num_starting_slots)
    return levels


def player_replacement_level(eligible: Iterable[Position], levels: dict[str, float]) -> float:
    """Lowest replacement level among a player's eligible positions.
    Players with no positional eligibility are measured against OVERALL."""
    candidates = [levels[p.value] for p in eligible if p.value in levels]
    if not candidates:
        return levels[OVERALL]
    return min(candidates)


def vorp(
    season_fp: pd.Series,
    positions: pd.Series,
    levels: dict[str, float],
) -> pd.Series:
    """VORP per player = season FP - lowest eligible replacement level."""
    positions = positions.reindex(season_fp.index)
    baseline = positions.map(lambda ps: player_replacement_level(ps or (), levels))
    return (season_fp - baseline.astype(float)).rename("VORP")
