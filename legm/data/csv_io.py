"""External CSV loaders: projections and ADP.

Projection CSV columns: name (or nba_id), gp, mpg, pts, reb, ast, stl, blk, tov
and optionally fgm, fga, ftm, fta, fg3m. Column names are case-insensitive.

ADP CSV columns: name (or nba_id), adp.

Rows are matched to players by nba_id when present, else by normalized name.
Unmatched rows are returned so the CLI can report them.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from legm.config.models import STAT_KEYS
from legm.data.crosswalk import match_players
from legm.data.models import Adp, Projection

REQUIRED_PROJECTION_COLUMNS = ("gp", "mpg", "pts", "reb", "ast", "stl", "blk", "tov")
OPTIONAL_PROJECTION_COLUMNS = ("fgm", "fga", "ftm", "fta", "fg3m")


def read_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    if "player" in frame.columns and "name" not in frame.columns:
        frame = frame.rename(columns={"player": "name"})
    if "nba_id" not in frame.columns and "name" not in frame.columns:
        raise ValueError("CSV needs a 'name' or 'nba_id' column")
    return frame


def csv_source_name(path: str | Path) -> str:
    return f"csv:{Path(path).name}"


def load_projection_csv(session: Session, path: str | Path) -> tuple[int, pd.DataFrame]:
    """Upsert projections from a CSV under source 'csv:<filename>'.

    Replaces any previous rows from the same source. Returns (loaded, unmatched).
    """
    frame = read_csv(path)
    missing = [c for c in REQUIRED_PROJECTION_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"projection CSV missing columns: {missing}")
    matched, unmatched = match_players(session, frame)
    source = csv_source_name(path)
    session.execute(delete(Projection).where(Projection.source == source))
    for _, row in matched.iterrows():
        values = {c: float(row[c]) for c in REQUIRED_PROJECTION_COLUMNS}
        for c in OPTIONAL_PROJECTION_COLUMNS:
            values[c] = float(row[c]) if c in frame.columns and not pd.isna(row[c]) else None
        session.add(Projection(player_id=int(row["PLAYER_ID"]), source=source, **values))
    session.flush()
    return len(matched), unmatched


def load_adp_csv(session: Session, path: str | Path) -> tuple[int, pd.DataFrame]:
    """Replace the ADP table with the contents of a CSV. Returns (loaded, unmatched)."""
    frame = read_csv(path)
    if "adp" not in frame.columns:
        raise ValueError("ADP CSV missing 'adp' column")
    matched, unmatched = match_players(session, frame)
    source = csv_source_name(path)
    session.execute(delete(Adp))
    for _, row in matched.iterrows():
        session.add(Adp(player_id=int(row["PLAYER_ID"]), adp=float(row["adp"]), source=source))
    session.flush()
    return len(matched), unmatched


def load_injuries_csv(session: Session, path: str | Path) -> tuple[int, pd.DataFrame]:
    """Set Player.injury_status/injury_note from a CSV (name|nba_id, status, note?).
    Clears every player's status first, so the CSV is the full current injury report."""
    from legm.data.models import Player

    frame = read_csv(path)
    if "status" not in frame.columns:
        raise ValueError("injury CSV missing 'status' column")
    matched, unmatched = match_players(session, frame)
    for player in session.execute(select(Player)).scalars():
        player.injury_status = None
        player.injury_note = None
    for _, row in matched.iterrows():
        player = session.get(Player, int(row["PLAYER_ID"]))
        status = str(row["status"]).strip().lower()
        player.injury_status = status or None
        note = row.get("note")
        player.injury_note = None if note is None or pd.isna(note) else str(note)[:255]
    session.flush()
    return len(matched), unmatched


def csv_sources(session: Session) -> list[str]:
    rows = session.execute(select(Projection.source).distinct()).scalars().all()
    return sorted(s for s in rows if s.startswith("csv:"))


__all__ = [
    "STAT_KEYS",
    "csv_source_name",
    "csv_sources",
    "load_adp_csv",
    "load_injuries_csv",
    "load_projection_csv",
    "read_csv",
]
