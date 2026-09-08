import pandas as pd
import pytest

from legm.config.models import ScoringConfig
from legm.engine.scoring import (
    MissingStatError,
    fantasy_points_frame,
    fantasy_points_per_game,
    season_fantasy_points,
)

# Jokic-like line: 26.4 pts, 12.4 reb, 9.0 ast, 1.4 stl, 0.9 blk, 3.3 tov
JOKIC = {"PTS": 26.4, "REB": 12.4, "AST": 9.0, "STL": 1.4, "BLK": 0.9, "TOV": 3.3}
# Hand: 26.4 + 14.88 + 13.5 + 4.2 + 2.7 - 3.3 = 58.38
JOKIC_FPG = 58.38

# Bench-ish line: 8.0 pts, 3.0 reb, 1.0 ast, 0.5 stl, 0.5 blk, 1.0 tov
BENCH = {"PTS": 8.0, "REB": 3.0, "AST": 1.0, "STL": 0.5, "BLK": 0.5, "TOV": 1.0}
# Hand: 8 + 3.6 + 1.5 + 1.5 + 1.5 - 1.0 = 15.1
BENCH_FPG = 15.1


def test_fpg_hand_computed(yahoo_scoring):
    assert fantasy_points_per_game(JOKIC, yahoo_scoring) == pytest.approx(JOKIC_FPG)
    assert fantasy_points_per_game(BENCH, yahoo_scoring) == pytest.approx(BENCH_FPG)


def test_fpg_accepts_series(yahoo_scoring):
    assert fantasy_points_per_game(pd.Series(JOKIC), yahoo_scoring) == pytest.approx(JOKIC_FPG)


def test_season_fp():
    assert season_fantasy_points(58.38, 70) == pytest.approx(4086.6)
    assert season_fantasy_points(15.1, 0) == 0.0


def test_zero_weight_stats_not_required(yahoo_scoring):
    # FGM/FGA etc. are weighted 0 by default and absent from the row: fine.
    assert "FGA" not in JOKIC
    fantasy_points_per_game(JOKIC, yahoo_scoring)


def test_missing_weighted_stat_raises(yahoo_scoring):
    row = dict(JOKIC)
    del row["BLK"]
    with pytest.raises(MissingStatError):
        fantasy_points_per_game(row, yahoo_scoring)


def test_null_weighted_stat_raises(yahoo_scoring):
    row = dict(JOKIC, STL=None)
    with pytest.raises(MissingStatError):
        fantasy_points_per_game(row, yahoo_scoring)


def test_alternate_scoring_uses_shooting_stats():
    scoring = ScoringConfig(PTS=1, FGM=2, FGA=-1, FTM=1, FTA=-1, FG3M=1)
    row = {"PTS": 20, "FGM": 8, "FGA": 16, "FTM": 2, "FTA": 3, "FG3M": 2}
    # 20 + 16 - 16 + 2 - 3 + 2 = 21
    assert fantasy_points_per_game(row, scoring) == pytest.approx(21.0)


def test_frame_matches_rowwise(yahoo_scoring):
    frame = pd.DataFrame([JOKIC, BENCH], index=[1, 2])
    fpg = fantasy_points_frame(frame, yahoo_scoring)
    assert fpg.loc[1] == pytest.approx(JOKIC_FPG)
    assert fpg.loc[2] == pytest.approx(BENCH_FPG)


def test_frame_missing_column_raises(yahoo_scoring):
    frame = pd.DataFrame([JOKIC]).drop(columns=["AST"])
    with pytest.raises(MissingStatError):
        fantasy_points_frame(frame, yahoo_scoring)
