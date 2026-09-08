from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from legm.data.nba import RawCache, game_type, parse_schedule, season_schedule
from legm.data.schedule import (
    games_on,
    has_schedule,
    read_schedule_csv,
    schedule_path,
    teams_playing_on,
    upsert_games,
    write_schedule_csv,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAYLOAD = json.loads((FIXTURES / "scheduleleaguev2" / "2025-26.json").read_text())


def test_parse_schedule_flattens_and_drops_placeholders():
    frame = parse_schedule(PAYLOAD)
    assert list(frame.columns) == ["GAME_DATE", "HOME_TEAM", "AWAY_TEAM", "GAME_ID", "SEASON_TYPE"]
    assert len(frame) == 5  # the TBD play-in row is dropped
    assert frame.loc[0, "GAME_DATE"] == date(2025, 10, 5)
    assert set(frame["HOME_TEAM"]) == {"AAA", "CCC", "BBB"}
    assert list(frame["SEASON_TYPE"]) == ["preseason", "regular", "regular", "regular", "playoffs"]


def test_game_type_from_id():
    assert game_type("0022500001") == "regular"
    assert game_type("0012500001") == "preseason"
    assert game_type("0042500101") == "playoffs"
    assert game_type("0052500001") == "playin"
    # a hand-written CSV has no ids; those rows count
    assert game_type(None) == "regular" and game_type("") == "regular" and game_type("42") == "regular"


def test_season_schedule_keeps_only_the_regular_season():
    """Preseason opponents are not always NBA teams (MEL, HAP), and no other
    game type scores fantasy points."""
    cache = RawCache(raw_dir=FIXTURES, sleep_seconds=0)
    regular = season_schedule("2025-26", cache)
    assert len(regular) == 3 and set(regular["SEASON_TYPE"]) == {"regular"}
    assert "MEL" not in set(regular["AWAY_TEAM"])
    everything = season_schedule("2025-26", cache, ["preseason", "regular", "playoffs"])
    assert len(everything) == 5


def test_parse_schedule_empty_payload():
    assert parse_schedule({}).empty
    assert parse_schedule({"leagueSchedule": {"gameDates": []}}).empty


def test_season_schedule_uses_the_raw_cache(tmp_path):
    """A cached payload is never re-fetched, matching the stats endpoints."""
    cache = RawCache(raw_dir=FIXTURES, sleep_seconds=0)
    frame = season_schedule("2025-26", cache)
    assert not frame.empty and cache.live_calls == 0


def test_csv_round_trip(tmp_path):
    frame = parse_schedule(PAYLOAD)
    path = write_schedule_csv(frame, schedule_path("2025-26", tmp_path))
    assert path.name == "2025-26.csv"
    assert path.read_text().splitlines()[0] == "game_date,home_team,away_team,game_id,season_type"
    back = read_schedule_csv(path)
    assert list(back["GAME_DATE"]) == list(frame["GAME_DATE"])
    assert list(back["HOME_TEAM"]) == list(frame["HOME_TEAM"])
    assert list(back["AWAY_TEAM"]) == list(frame["AWAY_TEAM"])
    assert list(back["SEASON_TYPE"]) == list(frame["SEASON_TYPE"])


def test_read_schedule_csv_normalizes_and_validates(tmp_path):
    good = tmp_path / "s.csv"
    good.write_text("game_date,home_team,away_team\n2025-10-21, aaa , bbb\n")
    frame = read_schedule_csv(good)
    assert frame.loc[0, "HOME_TEAM"] == "AAA" and frame.loc[0, "AWAY_TEAM"] == "BBB"
    assert frame.loc[0, "GAME_DATE"] == date(2025, 10, 21)
    assert frame.loc[0, "SEASON_TYPE"] == "regular"  # no column: the row counts

    bad = tmp_path / "bad.csv"
    bad.write_text("game_date,home\n2025-10-21,AAA\n")
    with pytest.raises(ValueError, match="missing column"):
        read_schedule_csv(bad)


def test_upsert_games_is_idempotent(session):
    frame = parse_schedule(PAYLOAD)
    assert not has_schedule(session)
    assert upsert_games(session, frame, "2025-26") == 5
    assert upsert_games(session, frame, "2025-26") == 0  # same games, nothing added
    assert len(games_on(session, date(2025, 10, 21))) == 2
    assert has_schedule(session)
    # a different season is stored separately
    assert upsert_games(session, frame, "2026-27") == 5


def test_games_on_filters_out_non_fantasy_games(session):
    """Even with a full schedule stored, only regular-season games count."""
    upsert_games(session, parse_schedule(PAYLOAD), "2025-26")
    assert games_on(session, date(2025, 10, 5)) == []  # preseason
    assert games_on(session, date(2026, 4, 20)) == []  # playoffs
    assert teams_playing_on(session, date(2025, 10, 5)) == {}
    assert len(games_on(session, date(2025, 10, 5), ["preseason"])) == 1
    assert teams_playing_on(session, date(2026, 4, 20), ["playoffs"]) == {"AAA": "BBB", "BBB": "@AAA"}


def test_teams_playing_on_maps_both_sides(session):
    upsert_games(session, parse_schedule(PAYLOAD), "2025-26")
    day1 = teams_playing_on(session, date(2025, 10, 21))
    assert day1 == {"AAA": "BBB", "BBB": "@AAA", "CCC": "DDD", "DDD": "@CCC"}
    assert teams_playing_on(session, date(2025, 10, 22)) == {"BBB": "CCC", "CCC": "@BBB"}
    assert teams_playing_on(session, date(2025, 12, 25)) == {}
