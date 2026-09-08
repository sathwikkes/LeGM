"""NBA schedule storage.

The raw scheduleleaguev2 payload is megabytes of broadcaster metadata, so it is
never committed. What is committed is the slim CSV this module writes
(data/schedule/<season>.csv: game_date, home_team, away_team, game_id), which
`legm load-schedule` reads back. That keeps the deployed container and CI
offline, the same way data/raw does for player stats.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from legm.data.models import Game
from legm.data.nba import REGULAR_SEASON

DEFAULT_SCHEDULE_DIR = Path("data") / "schedule"
CSV_COLUMNS = ["game_date", "home_team", "away_team", "game_id", "season_type"]
REQUIRED_CSV_COLUMNS = ["game_date", "home_team", "away_team"]


def schedule_path(season: str, directory: str | Path = DEFAULT_SCHEDULE_DIR) -> Path:
    return Path(directory) / f"{season}.csv"


def write_schedule_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    """Persist a parsed schedule frame as the slim committed CSV."""
    out = pd.DataFrame(
        {
            "game_date": [d.isoformat() for d in frame["GAME_DATE"]],
            "home_team": frame["HOME_TEAM"],
            "away_team": frame["AWAY_TEAM"],
            "game_id": frame["GAME_ID"],
            "season_type": frame["SEASON_TYPE"],
        }
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False)
    return target


def read_schedule_csv(path: str | Path) -> pd.DataFrame:
    """Read the slim CSV back into the frame shape parse_schedule produces."""
    raw = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"schedule csv is missing column(s): {', '.join(missing)}")
    return pd.DataFrame(
        {
            "GAME_DATE": [pd.to_datetime(d).date() for d in raw["game_date"]],
            "HOME_TEAM": raw["home_team"].str.strip().str.upper(),
            "AWAY_TEAM": raw["away_team"].str.strip().str.upper(),
            "GAME_ID": raw["game_id"].replace("", None) if "game_id" in raw.columns else None,
            # A hand-written CSV without the column is taken at face value: the
            # user loaded it to drive lineups, so every row counts.
            "SEASON_TYPE": (
                raw["season_type"].str.strip().str.lower().replace("", REGULAR_SEASON)
                if "season_type" in raw.columns
                else REGULAR_SEASON
            ),
        }
    )


def upsert_games(session: Session, frame: pd.DataFrame, season: str) -> int:
    """Insert games for `season`, skipping ones already stored. Idempotent."""
    existing = {
        (d, h, a)
        for d, h, a in session.execute(
            select(Game.game_date, Game.home_team, Game.away_team).where(Game.season == season)
        ).all()
    }
    added = 0
    for row in frame.itertuples(index=False):
        key = (row.GAME_DATE, row.HOME_TEAM, row.AWAY_TEAM)
        if key in existing:
            continue
        existing.add(key)
        session.add(
            Game(
                season=season,
                game_date=row.GAME_DATE,
                home_team=row.HOME_TEAM,
                away_team=row.AWAY_TEAM,
                nba_game_id=getattr(row, "GAME_ID", None) or None,
                season_type=getattr(row, "SEASON_TYPE", REGULAR_SEASON) or REGULAR_SEASON,
            )
        )
        added += 1
    session.flush()
    return added


def games_on(session: Session, day: date, season_types: Sequence[str] | None = None) -> list[Game]:
    """Games scheduled on `day`, across seasons.

    Defaults to the regular season: preseason, All-Star, play-in, NBA Cup final
    and playoff games score no fantasy points, and preseason opponents are not
    always NBA teams.
    """
    wanted = list(season_types) if season_types is not None else [REGULAR_SEASON]
    stmt = select(Game).where(Game.game_date == day, Game.season_type.in_(wanted)).order_by(Game.home_team)
    return list(session.execute(stmt).scalars())


def teams_playing_on(session: Session, day: date, season_types: Sequence[str] | None = None) -> dict[str, str]:
    """Team tricode -> the opponent it faces on `day`, away games marked "@HOME".

    A team appearing twice in one day (never in a real schedule, but possible in
    hand-made CSVs) keeps its first opponent.
    """
    out: dict[str, str] = {}
    for game in games_on(session, day, season_types):
        out.setdefault(game.home_team, game.away_team)
        out.setdefault(game.away_team, f"@{game.home_team}")
    return out


def has_schedule(session: Session) -> bool:
    return session.execute(select(Game.id).limit(1)).scalar_one_or_none() is not None
