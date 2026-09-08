"""Projection v0: minutes-weighted blend of recent seasons.

Input is a long DataFrame with one row per (player, season) holding per-game
stats. Output is one row per player of projected per-game rates and GP.

Blend rule (see config/league.yaml `projection`):
  * Seasons are ordered most recent first and paired with nominal weights.
  * Per player, only seasons they actually have a row for count; their
    nominal weights are renormalized to sum to 1.
  * Per-game stat rates are averaged with effective weight
        nominal_weight * total_minutes   (total_minutes = gp * mpg)
    so a season in which a player barely played contributes little.
  * Projected GP = min(gp_cap, nominal-weighted mean of GP).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from legm.config.models import STAT_KEYS, ProjectionConfig

RATE_COLUMNS: tuple[str, ...] = ("MPG", *STAT_KEYS)
PROJECTION_COLUMNS: tuple[str, ...] = ("GP", *RATE_COLUMNS)


def season_weight_map(seasons: Sequence[str], nominal_weights: Sequence[float]) -> dict[str, float]:
    """Pair seasons (most recent first) with nominal weights.

    If fewer seasons than weights are supplied, extra weights are dropped.
    If more seasons than weights, raise: the config must cover every season.
    """
    if len(seasons) > len(nominal_weights):
        raise ValueError(
            f"{len(seasons)} seasons supplied but only {len(nominal_weights)} "
            f"season_weights configured"
        )
    return {season: float(w) for season, w in zip(seasons, nominal_weights, strict=False)}


def blend_player(rows: pd.DataFrame, weights: dict[str, float], gp_cap: int) -> pd.Series:
    """Blend one player's season rows. `rows` must have columns SEASON, GP and RATE_COLUMNS."""
    nominal = rows["SEASON"].map(weights).astype(float)
    if nominal.isna().any():
        unknown = rows.loc[nominal.isna(), "SEASON"].tolist()
        raise ValueError(f"no season weight for {unknown}")
    nominal = nominal / nominal.sum()

    total_minutes = rows["GP"].astype(float) * rows["MPG"].astype(float)
    effective = nominal * total_minutes
    if effective.sum() <= 0:
        # Player has rows but no minutes; fall back to nominal weights so we
        # still produce (zero) rates rather than NaN.
        effective = nominal

    out: dict[str, float] = {}
    for col in RATE_COLUMNS:
        out[col] = float(np.average(rows[col].astype(float), weights=effective))
    gp = float(np.average(rows["GP"].astype(float), weights=nominal))
    out["GP"] = min(float(gp_cap), gp)
    return pd.Series(out)[list(PROJECTION_COLUMNS)]


def build_v0_projections(
    season_stats: pd.DataFrame,
    seasons: Sequence[str],
    config: ProjectionConfig,
) -> pd.DataFrame:
    """Project every player in `season_stats`.

    season_stats columns: PLAYER_ID, SEASON, GP, MPG, and every STAT_KEYS column.
    `seasons` lists the seasons to blend, most recent first.
    Returns a frame indexed by PLAYER_ID with PROJECTION_COLUMNS.
    """
    weights = season_weight_map(seasons, config.season_weights)
    subset = season_stats[season_stats["SEASON"].isin(weights)]
    if subset.empty:
        return pd.DataFrame(columns=list(PROJECTION_COLUMNS)).rename_axis("PLAYER_ID")
    projected = subset.groupby("PLAYER_ID", sort=True).apply(
        lambda rows: blend_player(rows, weights, config.gp_cap), include_groups=False
    )
    return projected[list(PROJECTION_COLUMNS)]
