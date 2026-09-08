"""Build the draft pool from Phase 1 rankings."""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from legm.config.models import LeagueConfig
from legm.draft.models import PlayerCard
from legm.engine.rankings import rank_players


def pool_from_rankings(ranked: pd.DataFrame) -> dict[int, PlayerCard]:
    pool: dict[int, PlayerCard] = {}
    for pid, r in ranked.iterrows():
        adp = r.get("ADP")
        pool[int(pid)] = PlayerCard(
            player_id=int(pid),
            name=str(r["NAME"]),
            positions=tuple(r["POSITION_LIST"]),
            team=None if r["TEAM"] is None or pd.isna(r["TEAM"]) else str(r["TEAM"]),
            gp=float(r["GP"]),
            fpg=float(r["FPG"]),
            season_fp=float(r["SEASON_FP"]),
            vorp=float(r["VORP"]),
            adp=None if adp is None or pd.isna(adp) else float(adp),
            age=None if r.get("AGE") is None or pd.isna(r.get("AGE")) else float(r["AGE"]),
            injury_status=None if r.get("INJURY_STATUS") is None or pd.isna(r.get("INJURY_STATUS")) else str(r["INJURY_STATUS"]),
            confidence=float(r.get("CONFIDENCE", 0.7)) if r.get("CONFIDENCE") is not None and not pd.isna(r.get("CONFIDENCE")) else 0.7,
            projection_source=None if r.get("SOURCE") is None else str(r["SOURCE"]),
        )
    return pool


def load_pool(session: Session, league: LeagueConfig, include_inactive: bool = False) -> dict[int, PlayerCard]:
    return pool_from_rankings(rank_players(session, league, include_inactive=include_inactive))
