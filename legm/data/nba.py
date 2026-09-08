"""nba_api access with a raw-response disk cache.

Every call is cached as JSON under data/raw/<endpoint>/<season>.json. A
cached response is never re-downloaded. A polite sleep separates live calls.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data") / "raw"
DEFAULT_SLEEP_SECONDS = 1.5
REQUEST_TIMEOUT = 60

STATS_COLUMNS = [
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ABBREVIATION",
    "AGE",
    "GP",
    "MIN",
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    "FG3M",
]
INDEX_COLUMNS = [
    "PERSON_ID",
    "PLAYER_FIRST_NAME",
    "PLAYER_LAST_NAME",
    "TEAM_ABBREVIATION",
    "POSITION",
    "ROSTER_STATUS",
]


class RawCache:
    def __init__(self, raw_dir: Path = DEFAULT_RAW_DIR, sleep_seconds: float = DEFAULT_SLEEP_SECONDS):
        self.raw_dir = Path(raw_dir)
        self.sleep_seconds = sleep_seconds
        self._live_calls = 0

    def path(self, endpoint: str, season: str) -> Path:
        return self.raw_dir / endpoint / f"{season}.json"

    def get_or_fetch(self, endpoint: str, season: str, fetch: Callable[[], dict]) -> dict:
        target = self.path(endpoint, season)
        if target.exists():
            log.info("cache hit %s", target)
            with open(target, encoding="utf-8") as fh:
                return json.load(fh)
        if self._live_calls > 0:
            time.sleep(self.sleep_seconds)
        log.info("fetching %s %s", endpoint, season)
        payload = fetch()
        self._live_calls += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return payload

    @property
    def live_calls(self) -> int:
        return self._live_calls


def _frame_from_payload(payload: dict, result_set_name: str) -> pd.DataFrame:
    for rs in payload["resultSets"]:
        if rs["name"] == result_set_name:
            return pd.DataFrame(rs["rowSet"], columns=rs["headers"])
    raise KeyError(f"result set {result_set_name!r} not in payload")


def _fetch_player_stats(season: str) -> dict:
    from nba_api.stats.endpoints import leaguedashplayerstats

    ep = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed="PerGame",
        season_type_all_star="Regular Season",
        timeout=REQUEST_TIMEOUT,
    )
    return ep.get_dict()


def _fetch_player_index(season: str) -> dict:
    from nba_api.stats.endpoints import playerindex

    ep = playerindex.PlayerIndex(season=season, timeout=REQUEST_TIMEOUT)
    return ep.get_dict()


def season_player_stats(season: str, cache: RawCache) -> pd.DataFrame:
    """Per-game stats for every player who appeared in `season` (regular season)."""
    payload = cache.get_or_fetch("leaguedashplayerstats", season, lambda: _fetch_player_stats(season))
    frame = _frame_from_payload(payload, "LeagueDashPlayerStats")[STATS_COLUMNS].copy()
    frame = frame.rename(columns={"MIN": "MPG"})
    frame["SEASON"] = season
    return frame


def season_player_index(season: str, cache: RawCache) -> pd.DataFrame:
    """Player directory for `season`: position and team for everyone on a roster."""
    payload = cache.get_or_fetch("playerindex", season, lambda: _fetch_player_index(season))
    frame = _frame_from_payload(payload, "PlayerIndex")[INDEX_COLUMNS].copy()
    frame["PLAYER_NAME"] = (frame["PLAYER_FIRST_NAME"].fillna("") + " " + frame["PLAYER_LAST_NAME"].fillna("")).str.strip()
    return frame.rename(columns={"PERSON_ID": "PLAYER_ID"})
