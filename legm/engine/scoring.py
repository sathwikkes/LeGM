"""Fantasy-point scoring. Pure functions; no I/O, no config loading.

A "stat row" is any Mapping (dict, pandas Series, ORM-derived dict) whose
keys are the stat names in legm.config.models.STAT_KEYS holding per-game
values. Stats the scoring config does not mention are ignored.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from legm.config.models import ScoringConfig


class MissingStatError(KeyError):
    """A stat the scoring config weights is absent from the stat row."""


def fantasy_points_per_game(stats: Mapping[str, float], scoring: ScoringConfig) -> float:
    """Fantasy points per game for one per-game stat row.

    Raises MissingStatError if a stat with a non-zero multiplier is missing
    or null. Stats with a zero multiplier are never required.
    """
    total = 0.0
    for stat, weight in scoring.weights().items():
        try:
            value = stats[stat]
        except KeyError as exc:
            raise MissingStatError(stat) from exc
        if value is None or pd.isna(value):
            raise MissingStatError(stat)
        total += float(value) * weight
    return total


def season_fantasy_points(fp_per_game: float, games_played: float) -> float:
    """Season fantasy points given a per-game rate and a games-played figure."""
    return fp_per_game * games_played


def fantasy_points_frame(stats: pd.DataFrame, scoring: ScoringConfig) -> pd.Series:
    """Vectorized FP/G for a frame with one per-game stat column per stat key.

    Equivalent to applying fantasy_points_per_game row by row.
    """
    weights = scoring.weights()
    missing = [s for s in weights if s not in stats.columns]
    if missing:
        raise MissingStatError(missing[0])
    fpg = pd.Series(0.0, index=stats.index)
    for stat, weight in weights.items():
        fpg = fpg + stats[stat].astype(float) * weight
    return fpg
