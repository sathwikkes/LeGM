"""nba_api access with a raw-response disk cache.

Every call is cached as JSON under data/raw/<endpoint>/<season>.json. A
cached response is never re-downloaded. A polite sleep separates live calls.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
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


def _fetch_schedule(season: str) -> dict:
    from nba_api.stats.endpoints import scheduleleaguev2

    ep = scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=REQUEST_TIMEOUT)
    return ep.get_dict()


# NBA game-id prefixes. A 2025-26 payload holds 71 preseason games (including
# ones against non-NBA clubs like MEL and HAP), 1230 regular-season games, the
# All-Star weekend, the NBA Cup final, the play-in and the playoffs. Only the
# regular season scores fantasy points, so the type travels with every game.
GAME_TYPES = {
    "001": "preseason",
    "002": "regular",
    "003": "allstar",
    "004": "playoffs",
    "005": "playin",
    "006": "cup",
}
REGULAR_SEASON = "regular"


def game_type(game_id: str | None) -> str:
    """Season type from an NBA game id. Unknown or missing ids read as regular
    season, so a hand-written schedule CSV without ids still works."""
    if not game_id or len(str(game_id)) < 3:
        return REGULAR_SEASON
    return GAME_TYPES.get(str(game_id)[:3], REGULAR_SEASON)


def parse_schedule(payload: dict) -> pd.DataFrame:
    """Flatten a scheduleleaguev2 payload to GAME_DATE / HOME_TEAM / AWAY_TEAM /
    GAME_ID / SEASON_TYPE.

    This endpoint answers with nested JSON (leagueSchedule.gameDates[].games[])
    rather than the resultSets shape the other endpoints use, so it needs its
    own parser. Games without both tricodes (placeholder play-in and finals
    rows) are dropped.
    """
    rows = []
    for game_date in payload.get("leagueSchedule", {}).get("gameDates", []):
        for game in game_date.get("games", []):
            home = (game.get("homeTeam") or {}).get("teamTricode")
            away = (game.get("awayTeam") or {}).get("teamTricode")
            # gameDateEst is ISO ("2025-10-21T00:00:00Z"); gameDate is US-style.
            raw_date = game.get("gameDateEst") or game.get("gameDate") or game_date.get("gameDate")
            if not home or not away or not raw_date:
                continue
            game_id = str(game.get("gameId")) if game.get("gameId") else None
            rows.append(
                {
                    "GAME_DATE": pd.to_datetime(raw_date, format="mixed").date(),
                    "HOME_TEAM": str(home).upper(),
                    "AWAY_TEAM": str(away).upper(),
                    "GAME_ID": game_id,
                    "SEASON_TYPE": game_type(game_id),
                }
            )
    frame = pd.DataFrame(rows, columns=["GAME_DATE", "HOME_TEAM", "AWAY_TEAM", "GAME_ID", "SEASON_TYPE"])
    return frame.drop_duplicates(subset=["GAME_DATE", "HOME_TEAM", "AWAY_TEAM"]).sort_values(
        ["GAME_DATE", "HOME_TEAM"], ignore_index=True
    )


def season_schedule(season: str, cache: RawCache, season_types: Sequence[str] | None = None) -> pd.DataFrame:
    """Scheduled games in `season`, one row per game.

    Defaults to the regular season only: preseason opponents are not always NBA
    teams, and no other game type scores fantasy points.
    """
    payload = cache.get_or_fetch("scheduleleaguev2", season, lambda: _fetch_schedule(season))
    frame = parse_schedule(payload)
    wanted = set(season_types) if season_types is not None else {REGULAR_SEASON}
    return frame[frame["SEASON_TYPE"].isin(wanted)].reset_index(drop=True)


def season_player_index(season: str, cache: RawCache) -> pd.DataFrame:
    """Player directory for `season`: position and team for everyone on a roster."""
    payload = cache.get_or_fetch("playerindex", season, lambda: _fetch_player_index(season))
    frame = _frame_from_payload(payload, "PlayerIndex")[INDEX_COLUMNS].copy()
    frame["PLAYER_NAME"] = (frame["PLAYER_FIRST_NAME"].fillna("") + " " + frame["PLAYER_LAST_NAME"].fillna("")).str.strip()
    return frame.rename(columns={"PERSON_ID": "PLAYER_ID"})
