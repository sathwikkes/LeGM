import pandas as pd
import pytest

from legm.data.csv_io import load_adp_csv, load_projection_csv
from legm.data.ingest import rebuild_v0_projections
from legm.engine.rankings import RANK_COLUMNS, rank_players


@pytest.fixture
def ranked_session(seeded_session, default_config):
    rebuild_v0_projections(seeded_session, ["2025-26", "2024-25"], default_config.projection)
    return seeded_session


def test_rank_order_and_columns(ranked_session, default_config):
    ranked = rank_players(ranked_session, default_config)
    assert set(RANK_COLUMNS) <= set(ranked.columns)
    # Old Forward has no 2025-26 games -> excluded by default.
    assert ranked["NAME"].tolist() == ["Star Guard", "Big Center", "Wing Player Jr."]
    assert ranked["RANK"].tolist() == [1, 2, 3]
    assert ranked["ADP"].isna().all()
    # Star Guard: blend of 70/34 and 65/33 seasons. Check FPG is between the two seasons' FPG.
    fpg_recent = 28 + 5 * 1.2 + 8 * 1.5 + 1.5 * 3 + 0.5 * 3 - 3
    fpg_prior = 26 + 5 * 1.2 + 7 * 1.5 + 1.2 * 3 + 0.4 * 3 - 3
    star = ranked.iloc[0]
    assert fpg_prior < star["FPG"] < fpg_recent
    assert star["SEASON_FP"] == pytest.approx(star["FPG"] * star["GP"])
    assert star["POSITIONS"] == "PG,SG"
    assert ranked.iloc[1]["POSITIONS"] == "C"


def test_include_inactive(ranked_session, default_config):
    ranked = rank_players(ranked_session, default_config, include_inactive=True)
    assert "Old Forward" in ranked["NAME"].tolist()


def test_csv_projection_takes_precedence(ranked_session, default_config, tmp_path):
    f = tmp_path / "ext.csv"
    f.write_text("name,gp,mpg,pts,reb,ast,stl,blk,tov\nWing Player,70,36,40,10,10,3,3,1\n")
    load_projection_csv(ranked_session, f)
    ranked = rank_players(ranked_session, default_config)
    wing = ranked.set_index("NAME").loc["Wing Player Jr."]
    assert wing["SOURCE"] == "csv:ext.csv" and wing["RANK"] == 1
    assert ranked.set_index("NAME").loc["Star Guard", "SOURCE"] == "v0_blend"


def test_adp_shown_after_load(ranked_session, default_config, tmp_path):
    f = tmp_path / "adp.csv"
    f.write_text("name,adp\nBig Center,2.0\n")
    load_adp_csv(ranked_session, f)
    ranked = rank_players(ranked_session, default_config).set_index("NAME")
    assert ranked.loc["Big Center", "ADP"] == 2.0
    assert pd.isna(ranked.loc["Star Guard", "ADP"])


def test_scoring_change_reorders(ranked_session, default_config):
    # Make blocks worth a fortune: Big Center (2.0 blk) must become the top FP/G player.
    # (VORP is degenerate on a 3-player pool, so compare FP/G rather than rank.)
    before = rank_players(ranked_session, default_config).set_index("NAME")
    assert before["FPG"].idxmax() == "Star Guard"
    cfg = default_config.model_copy(deep=True)
    cfg.scoring.BLK = 50
    after = rank_players(ranked_session, cfg).set_index("NAME")
    assert after["FPG"].idxmax() == "Big Center"
    assert after.loc["Big Center", "FPG"] == pytest.approx(before.loc["Big Center", "FPG"] + 2.0 * 47)
