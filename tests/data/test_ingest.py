import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from legm.config.models import ProjectionConfig
from legm.data.ingest import ingest_seasons
from legm.data.models import V0_SOURCE, Player, Projection, SeasonStat
from legm.data.nba import RawCache

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CFG = ProjectionConfig(season_weights=[0.65, 0.35], gp_cap=72)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    shutil.copytree(FIXTURES, raw)
    # Any live call would be a bug: make nba_api unusable.
    monkeypatch.setattr("legm.data.nba._fetch_player_stats", lambda s: (_ for _ in ()).throw(AssertionError("live call")))
    monkeypatch.setattr("legm.data.nba._fetch_player_index", lambda s: (_ for _ in ()).throw(AssertionError("live call")))
    return RawCache(raw_dir=raw, sleep_seconds=0)


def test_ingest_from_cache(session, cache):
    report = ingest_seasons(session, ["2024-25", "2025-26"], cache, CFG)
    assert report.seasons == ["2025-26", "2024-25"]
    assert report.live_calls == 0
    assert report.players_upserted == 4
    assert report.season_rows_upserted == 6

    players = {p.nba_id: p for p in session.execute(select(Player)).scalars()}
    jokic = players[1]
    assert jokic.name == "Nikola Jokić" and jokic.normalized_name == "nikola jokic"
    assert jokic.nba_position == "C" and jokic.team == "DEN" and jokic.age == 31
    assert players[2].nba_position == "F-C"  # most recent index wins over "F"
    assert players[2].normalized_name == "jaren jackson"
    assert players[4].nba_position == "G-F"  # only in 2024-25 index
    assert players[3].yahoo_positions is None

    stats = {(s.player_id, s.season): s for s in session.execute(select(SeasonStat)).scalars()}
    assert stats[(1, "2025-26")].gp == 70 and stats[(1, "2025-26")].mpg == 34.5
    assert stats[(1, "2024-25")].pts == 29.0
    assert stats[(3, "2025-26")].fg3m == pytest.approx(0.9)

    projections = {p.player_id: p for p in session.execute(select(Projection)).scalars()}
    assert report.projections_built == 4 and set(projections) == {1, 2, 3, 4}
    assert all(p.source == V0_SOURCE for p in projections.values())
    # Jokic GP: 0.65*70 + 0.35*78 = 45.5 + 27.3 = 72.8 -> capped at 72
    assert projections[1].gp == 72
    # Rookie: single season
    assert projections[3].pts == 9.0 and projections[3].gp == 55


def test_ingest_is_idempotent(session, cache):
    ingest_seasons(session, ["2024-25", "2025-26"], cache, CFG)
    ingest_seasons(session, ["2025-26", "2024-25"], cache, CFG)
    assert len(session.execute(select(Player)).scalars().all()) == 4
    assert len(session.execute(select(SeasonStat)).scalars().all()) == 6
    assert len(session.execute(select(Projection)).scalars().all()) == 4


def test_cache_writes_and_reads(tmp_path):
    cache = RawCache(raw_dir=tmp_path, sleep_seconds=0)
    calls = []

    def fetch():
        calls.append(1)
        return {"hello": "world"}

    assert cache.get_or_fetch("ep", "2025-26", fetch) == {"hello": "world"}
    assert cache.get_or_fetch("ep", "2025-26", fetch) == {"hello": "world"}
    assert len(calls) == 1 and cache.live_calls == 1
    assert (tmp_path / "ep" / "2025-26.json").exists()
