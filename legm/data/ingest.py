"""Ingest season stats from nba_api into the database and build v0 projections."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from legm.config.models import STAT_KEYS, ProjectionConfig
from legm.data.models import V0_SOURCE, Player, Projection, SeasonStat
from legm.data.names import normalize_name
from legm.data.nba import RawCache, season_player_index, season_player_stats
from legm.engine.projection import build_v0_projections

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    seasons: list[str]
    players_upserted: int
    season_rows_upserted: int
    projections_built: int
    live_calls: int


def sort_seasons_desc(seasons: Sequence[str]) -> list[str]:
    """'2024-25' style strings sort lexically in chronological order."""
    return sorted(set(seasons), reverse=True)


def _stat_values(row: pd.Series) -> dict[str, float | None]:
    values: dict[str, float | None] = {"gp": float(row["GP"]), "mpg": float(row["MPG"])}
    for key in STAT_KEYS:
        v = row.get(key)
        values[key.lower()] = None if v is None or pd.isna(v) else float(v)
    return values


def upsert_players_and_stats(
    session: Session,
    stats_by_season: dict[str, pd.DataFrame],
    index_by_season: dict[str, pd.DataFrame],
) -> tuple[int, int]:
    """Upsert Player rows (identity from the most recent season they appear in)
    and SeasonStat rows (one per player-season)."""
    seasons = sort_seasons_desc(stats_by_season)

    # Position/team directory: most recent season wins.
    directory: dict[int, dict[str, str | None]] = {}
    for season in seasons:
        idx = index_by_season.get(season)
        if idx is None:
            continue
        for _, r in idx.iterrows():
            pid = int(r["PLAYER_ID"])
            if pid in directory:
                continue
            directory[pid] = {
                "position": r["POSITION"] if isinstance(r["POSITION"], str) and r["POSITION"] else None,
                "team": r["TEAM_ABBREVIATION"] if isinstance(r["TEAM_ABBREVIATION"], str) and r["TEAM_ABBREVIATION"] else None,
            }

    existing_players = {p.nba_id: p for p in session.execute(select(Player)).scalars()}
    existing_stats = {
        (s.player_id, s.season): s for s in session.execute(select(SeasonStat)).scalars()
    }
    seen_players: set[int] = set()
    stat_rows = 0
    for season in seasons:
        frame = stats_by_season[season]
        for _, r in frame.iterrows():
            pid = int(r["PLAYER_ID"])
            name = str(r["PLAYER_NAME"]).strip()
            stats_team = r["TEAM_ABBREVIATION"] if isinstance(r["TEAM_ABBREVIATION"], str) else None
            age = None if pd.isna(r["AGE"]) else float(r["AGE"])
            if pid not in seen_players:
                seen_players.add(pid)
                entry = directory.get(pid, {})
                player = existing_players.get(pid)
                if player is None:
                    player = Player(nba_id=pid, name=name, normalized_name=normalize_name(name))
                    session.add(player)
                    existing_players[pid] = player
                player.name = name
                player.normalized_name = normalize_name(name)
                player.team = entry.get("team") or stats_team
                player.age = age
                player.nba_position = entry.get("position") or player.nba_position
            values = _stat_values(r)
            stat = existing_stats.get((pid, season))
            if stat is None:
                stat = SeasonStat(player_id=pid, season=season)
                session.add(stat)
                existing_stats[(pid, season)] = stat
            stat.team = stats_team
            stat.age = age
            for k, v in values.items():
                setattr(stat, k, v)
            stat_rows += 1
    session.flush()
    return len(seen_players), stat_rows


def season_stats_frame(session: Session, seasons: Sequence[str]) -> pd.DataFrame:
    """Long frame of per-game stats for the given seasons in engine column names."""
    rows = session.execute(select(SeasonStat).where(SeasonStat.season.in_(list(seasons)))).scalars()
    records = []
    for s in rows:
        rec = {"PLAYER_ID": s.player_id, "SEASON": s.season}
        rec.update(s.stat_row())
        records.append(rec)
    columns = ["PLAYER_ID", "SEASON", "GP", "MPG", *STAT_KEYS]
    return pd.DataFrame(records, columns=columns)


def rebuild_v0_projections(session: Session, seasons: Sequence[str], config: ProjectionConfig) -> int:
    """Replace all v0_blend projections from the stored season stats."""
    ordered = sort_seasons_desc(seasons)
    stats = season_stats_frame(session, ordered)
    projected = build_v0_projections(stats, ordered, config)
    session.execute(delete(Projection).where(Projection.source == V0_SOURCE))
    for pid, row in projected.iterrows():
        values = {"gp": float(row["GP"]), "mpg": float(row["MPG"])}
        for key in STAT_KEYS:
            v = row[key]
            values[key.lower()] = None if pd.isna(v) else float(v)
        session.add(Projection(player_id=int(pid), source=V0_SOURCE, **values))
    session.flush()
    return len(projected)


def ingest_seasons(
    session: Session,
    seasons: Sequence[str],
    cache: RawCache,
    projection_config: ProjectionConfig,
) -> IngestReport:
    ordered = sort_seasons_desc(seasons)
    stats_by_season = {s: season_player_stats(s, cache) for s in ordered}
    index_by_season = {s: season_player_index(s, cache) for s in ordered}
    players, stat_rows = upsert_players_and_stats(session, stats_by_season, index_by_season)
    built = rebuild_v0_projections(session, ordered, projection_config)
    return IngestReport(
        seasons=ordered,
        players_upserted=players,
        season_rows_upserted=stat_rows,
        projections_built=built,
        live_calls=cache.live_calls,
    )
