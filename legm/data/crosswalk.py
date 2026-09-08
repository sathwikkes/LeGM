"""Position crosswalk: NBA.com positions -> Yahoo eligibility.

Yahoo eligibility is set by Yahoo each season and does not derive cleanly
from NBA.com's coarse "G / F / C / G-F / F-C" labels. The authoritative
source is a Yahoo export loaded with `legm load-positions file.csv`
(columns: name or nba_id, positions as "PG,SG"). Until that is loaded,
`fallback_positions` maps the NBA label as follows:

    G    -> PG, SG        F    -> SF, PF        C   -> C
    G-F  -> SG, SF        F-G  -> SF, SG
    F-C  -> PF, C         C-F  -> C, PF
    missing/unknown -> no positional eligibility (UTIL only)
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from legm.config.models import Position
from legm.data.models import Player
from legm.data.names import normalize_name

FALLBACK_MAP: dict[str, tuple[Position, ...]] = {
    "G": (Position.PG, Position.SG),
    "F": (Position.SF, Position.PF),
    "C": (Position.C,),
    "G-F": (Position.SG, Position.SF),
    "F-G": (Position.SF, Position.SG),
    "F-C": (Position.PF, Position.C),
    "C-F": (Position.C, Position.PF),
}


def fallback_positions(nba_position: str | None) -> tuple[Position, ...]:
    if not nba_position:
        return ()
    return FALLBACK_MAP.get(nba_position.strip().upper(), ())


def parse_positions(text: str | None) -> tuple[Position, ...]:
    """'PG,SG' / 'PG/SG' / 'PG, SG' -> (PG, SG). Unknown tokens raise."""
    if text is None or (isinstance(text, float) and pd.isna(text)) or not str(text).strip():
        return ()
    tokens = [t.strip().upper() for t in str(text).replace("/", ",").split(",")]
    return tuple(Position(t) for t in tokens if t)


def format_positions(positions: Iterable[Position]) -> str:
    return ",".join(p.value for p in positions)


def effective_positions(player: Player) -> tuple[Position, ...]:
    """Yahoo positions if loaded, else the fallback from nba_position."""
    loaded = player.yahoo_position_list()
    if loaded:
        return tuple(loaded)
    return fallback_positions(player.nba_position)


def match_players(session: Session, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach PLAYER_ID to frame rows by nba_id column if present, else normalized name.

    Returns (matched, unmatched). Ambiguous normalized names are left unmatched.
    """
    frame = frame.copy()
    players = session.execute(select(Player.nba_id, Player.normalized_name)).all()
    by_id = {pid for pid, _ in players}
    by_name: dict[str, list[int]] = {}
    for pid, norm in players:
        by_name.setdefault(norm, []).append(pid)

    ids: list[int | None] = []
    for _, row in frame.iterrows():
        pid = None
        raw_id = row.get("nba_id")
        if raw_id is not None and not pd.isna(raw_id) and int(raw_id) in by_id:
            pid = int(raw_id)
        elif "name" in row and isinstance(row["name"], str):
            candidates = by_name.get(normalize_name(row["name"]), [])
            if len(candidates) == 1:
                pid = candidates[0]
        ids.append(pid)
    frame["PLAYER_ID"] = ids
    matched = frame[frame["PLAYER_ID"].notna()].copy()
    matched["PLAYER_ID"] = matched["PLAYER_ID"].astype(int)
    unmatched = frame[frame["PLAYER_ID"].isna()].drop(columns=["PLAYER_ID"])
    return matched, unmatched


def load_yahoo_positions(session: Session, frame: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """Set Player.yahoo_positions from a frame with (name|nba_id, positions).

    Returns (updated_count, unmatched_rows).
    """
    if "positions" not in frame.columns:
        raise ValueError("positions CSV needs a 'positions' column")
    matched, unmatched = match_players(session, frame)
    updated = 0
    for _, row in matched.iterrows():
        player = session.get(Player, int(row["PLAYER_ID"]))
        player.yahoo_positions = format_positions(parse_positions(row["positions"]))
        updated += 1
    session.flush()
    return updated, unmatched
