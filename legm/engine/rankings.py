"""Deterministic rankings: projection -> FP/G -> season FP -> VORP -> sorted table.

This is the one engine module that reads the database; everything it calls
is a pure function over pandas objects.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from legm.config.models import STAT_KEYS, LeagueConfig
from legm.data.crosswalk import effective_positions, format_positions
from legm.data.models import V0_SOURCE, Adp, Player, Projection, SeasonStat
from legm.engine.scoring import fantasy_points_frame
from legm.engine.vorp import replacement_levels, vorp

RANK_COLUMNS = ["RANK", "NAME", "POSITIONS", "TEAM", "GP", "FPG", "SEASON_FP", "VORP", "ADP"]


def latest_season(session: Session) -> str | None:
    return session.execute(select(func.max(SeasonStat.season))).scalar()


def active_player_ids(session: Session) -> set[int]:
    """Players with at least one game in the most recent ingested season."""
    season = latest_season(session)
    if season is None:
        return set()
    rows = session.execute(
        select(SeasonStat.player_id).where(SeasonStat.season == season, SeasonStat.gp > 0)
    ).scalars()
    return set(rows)


def selected_projections(session: Session) -> dict[int, Projection]:
    """One projection per player: newest CSV source beats v0_blend."""
    chosen: dict[int, Projection] = {}
    for proj in session.execute(select(Projection).order_by(Projection.created_at)).scalars():
        current = chosen.get(proj.player_id)
        if current is None:
            chosen[proj.player_id] = proj
        elif current.source == V0_SOURCE and proj.source != V0_SOURCE:
            chosen[proj.player_id] = proj
        elif current.source != V0_SOURCE and proj.source != V0_SOURCE:
            chosen[proj.player_id] = proj  # later CSV wins
    return chosen


def projection_confidence(seasons: int, total_minutes: float, source: str) -> float:
    """Heuristic confidence in [0, 1]: external projections are trusted most; a v0 blend
    gains confidence with a second season and with minutes played."""
    if source != V0_SOURCE:
        return 0.85
    return round(min(1.0, 0.4 + (0.2 if seasons >= 2 else 0.0) + 0.4 * min(1.0, total_minutes / 3000.0)), 3)


def player_pool(session: Session, include_inactive: bool = False) -> pd.DataFrame:
    """Frame indexed by PLAYER_ID with identity, positions, and projected stats."""
    projections = selected_projections(session)
    active = active_player_ids(session)
    players = {p.nba_id: p for p in session.execute(select(Player)).scalars()}
    adp = {a.player_id: a.adp for a in session.execute(select(Adp)).scalars()}
    history: dict[int, tuple[int, float]] = {}
    for pid, gp, mpg in session.execute(select(SeasonStat.player_id, SeasonStat.gp, SeasonStat.mpg)).all():
        n, mins = history.get(pid, (0, 0.0))
        history[pid] = (n + 1, mins + float(gp or 0) * float(mpg or 0))

    records = []
    for pid, proj in projections.items():
        player = players.get(pid)
        if player is None:
            continue
        if not include_inactive and pid not in active and proj.source == V0_SOURCE:
            continue
        positions = effective_positions(player)
        rec = {
            "PLAYER_ID": pid,
            "NAME": player.name,
            "POSITION_LIST": positions,
            "POSITIONS": format_positions(positions),
            "TEAM": player.team,
            "SOURCE": proj.source,
            "ADP": adp.get(pid),
            "AGE": player.age,
            "INJURY_STATUS": player.injury_status,
            "CONFIDENCE": projection_confidence(*history.get(pid, (0, 0.0)), proj.source),
        }
        rec.update(proj.stat_row())
        records.append(rec)
    columns = [
        "PLAYER_ID", "NAME", "POSITION_LIST", "POSITIONS", "TEAM", "SOURCE", "ADP", "AGE", "INJURY_STATUS",
        "CONFIDENCE", "GP", "MPG", *STAT_KEYS,
    ]
    return pd.DataFrame(records, columns=columns).set_index("PLAYER_ID")


def score_pool(pool: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    """Add FPG, SEASON_FP, VORP to a player pool and sort by VORP then SEASON_FP."""
    scored = pool.copy()
    if scored.empty:
        for c in ("FPG", "SEASON_FP", "VORP"):
            scored[c] = pd.Series(dtype=float)
        scored["RANK"] = pd.Series(dtype=int)
        return scored
    scored["FPG"] = fantasy_points_frame(scored, config.scoring)
    scored["SEASON_FP"] = scored["FPG"] * scored["GP"].astype(float)
    levels = replacement_levels(scored["SEASON_FP"], scored["POSITION_LIST"], config)
    scored["VORP"] = vorp(scored["SEASON_FP"], scored["POSITION_LIST"], levels)
    scored = scored.sort_values(["VORP", "SEASON_FP", "NAME"], ascending=[False, False, True])
    scored["RANK"] = range(1, len(scored) + 1)
    scored.attrs["replacement_levels"] = levels
    return scored


def rank_players(session: Session, config: LeagueConfig, include_inactive: bool = False) -> pd.DataFrame:
    return score_pool(player_pool(session, include_inactive=include_inactive), config)
