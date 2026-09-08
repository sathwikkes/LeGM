import pytest
from sqlalchemy import select

from legm.data.csv_io import load_adp_csv, load_projection_csv
from legm.data.models import Adp, Projection


def test_load_projection_csv(seeded_session, tmp_path):
    f = tmp_path / "proj.csv"
    f.write_text(
        "Name,GP,MPG,PTS,REB,AST,STL,BLK,TOV,FG3M\n"
        "Star Guard,72,35,30,5,9,1.5,0.5,3,3.1\n"
        "Wing Player,65,30,16,4,3,1,0.5,1.5,\n"
        "Ghost,10,10,1,1,1,1,1,1,1\n"
    )
    loaded, unmatched = load_projection_csv(seeded_session, f)
    assert loaded == 2
    assert unmatched["name"].tolist() == ["Ghost"]
    rows = {p.player_id: p for p in seeded_session.execute(select(Projection)).scalars()}
    assert rows[1].source == "csv:proj.csv" and rows[1].pts == 30 and rows[1].fg3m == 3.1
    assert rows[3].fg3m is None and rows[3].fgm is None
    # Reloading the same file replaces rather than duplicates.
    load_projection_csv(seeded_session, f)
    assert len(seeded_session.execute(select(Projection)).scalars().all()) == 2


def test_projection_csv_missing_column(seeded_session, tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("name,gp,pts\nStar Guard,70,30\n")
    with pytest.raises(ValueError):
        load_projection_csv(seeded_session, f)


def test_load_adp_csv(seeded_session, tmp_path):
    f = tmp_path / "adp.csv"
    f.write_text("player,adp\nBig Center,3.5\nStar Guard,1.2\nGhost,99\n")
    loaded, unmatched = load_adp_csv(seeded_session, f)
    assert loaded == 2 and unmatched["name"].tolist() == ["Ghost"]
    adp = {a.player_id: a.adp for a in seeded_session.execute(select(Adp)).scalars()}
    assert adp == {2: 3.5, 1: 1.2}
    f.write_text("name,adp\nBig Center,4\n")
    load_adp_csv(seeded_session, f)
    assert {a.player_id for a in seeded_session.execute(select(Adp)).scalars()} == {2}
