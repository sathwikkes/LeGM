import pandas as pd
import pytest

from legm.config.models import STAT_KEYS, ProjectionConfig
from legm.engine.projection import PROJECTION_COLUMNS, build_v0_projections, season_weight_map

SEASONS = ["2025-26", "2024-25"]
CFG = ProjectionConfig(season_weights=[0.65, 0.35], gp_cap=72)


def row(pid, season, gp, mpg, pts, reb=5.0, ast=3.0):
    r = {"PLAYER_ID": pid, "SEASON": season, "GP": gp, "MPG": mpg}
    r.update({k: 0.0 for k in STAT_KEYS})
    r.update(PTS=pts, REB=reb, AST=ast)
    return r


def test_two_season_blend_hand_computed():
    # Recent: 60 GP x 30 MPG = 1800 min, 20 pts.  Prior: 80 GP x 35 MPG = 2800 min, 25 pts.
    # Effective weights: 0.65*1800 = 1170 ; 0.35*2800 = 980  (sum 2150)
    # PTS = (1170*20 + 980*25) / 2150 = (23400 + 24500)/2150 = 22.27906...
    # MPG = (1170*30 + 980*35)/2150 = (35100 + 34300)/2150 = 32.27906...
    # GP  = 0.65*60 + 0.35*80 = 39 + 28 = 67
    stats = pd.DataFrame([row(1, "2025-26", 60, 30, 20.0), row(1, "2024-25", 80, 35, 25.0)])
    proj = build_v0_projections(stats, SEASONS, CFG)
    assert list(proj.columns) == list(PROJECTION_COLUMNS)
    p = proj.loc[1]
    assert p["PTS"] == pytest.approx(47900 / 2150)
    assert p["MPG"] == pytest.approx(69400 / 2150)
    assert p["GP"] == pytest.approx(67.0)


def test_single_season_player_uses_that_season_only():
    stats = pd.DataFrame([row(7, "2025-26", 50, 20, 12.0)])
    p = build_v0_projections(stats, SEASONS, CFG).loc[7]
    assert p["PTS"] == pytest.approx(12.0)
    assert p["GP"] == pytest.approx(50.0)
    stats = pd.DataFrame([row(8, "2024-25", 50, 20, 12.0)])
    p = build_v0_projections(stats, SEASONS, CFG).loc[8]
    assert p["PTS"] == pytest.approx(12.0)
    assert p["GP"] == pytest.approx(50.0)


def test_gp_capped():
    stats = pd.DataFrame([row(1, "2025-26", 82, 30, 20.0), row(1, "2024-25", 82, 30, 20.0)])
    assert build_v0_projections(stats, SEASONS, CFG).loc[1, "GP"] == 72


def test_minutes_weighting_favours_heavier_season():
    # Prior season has 10x the minutes; despite lower nominal weight it should dominate.
    stats = pd.DataFrame([row(1, "2025-26", 5, 10, 10.0), row(1, "2024-25", 80, 30, 30.0)])
    p = build_v0_projections(stats, SEASONS, CFG).loc[1]
    # eff: 0.65*50 = 32.5 ; 0.35*2400 = 840 -> PTS = (325 + 25200)/872.5
    assert p["PTS"] == pytest.approx(25525 / 872.5)
    assert p["PTS"] > 25.0


def test_zero_minutes_player_does_not_nan():
    stats = pd.DataFrame([row(1, "2025-26", 0, 0, 0.0)])
    p = build_v0_projections(stats, SEASONS, CFG).loc[1]
    assert p["PTS"] == 0.0 and p["GP"] == 0.0


def test_unconfigured_season_ignored_and_too_many_seasons_rejected():
    stats = pd.DataFrame([row(1, "2025-26", 60, 30, 20.0), row(1, "2023-24", 80, 35, 25.0)])
    p = build_v0_projections(stats, SEASONS, CFG).loc[1]
    assert p["PTS"] == pytest.approx(20.0)
    with pytest.raises(ValueError):
        season_weight_map(["a", "b", "c"], [0.65, 0.35])
