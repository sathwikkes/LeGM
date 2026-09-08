import pandas as pd
import pytest

from legm.config.models import Position
from legm.data.crosswalk import (
    effective_positions,
    fallback_positions,
    load_yahoo_positions,
    match_players,
    parse_positions,
)
from legm.data.models import Player


@pytest.mark.parametrize(
    "nba, expected",
    [
        ("G", (Position.PG, Position.SG)),
        ("F", (Position.SF, Position.PF)),
        ("C", (Position.C,)),
        ("G-F", (Position.SG, Position.SF)),
        ("F-G", (Position.SF, Position.SG)),
        ("F-C", (Position.PF, Position.C)),
        ("C-F", (Position.C, Position.PF)),
        ("", ()),
        (None, ()),
        ("??", ()),
    ],
)
def test_fallback_positions(nba, expected):
    assert fallback_positions(nba) == expected


def test_parse_positions():
    assert parse_positions("PG,SG") == (Position.PG, Position.SG)
    assert parse_positions("PG/SF") == (Position.PG, Position.SF)
    assert parse_positions(" c ") == (Position.C,)
    assert parse_positions(None) == ()
    with pytest.raises(ValueError):
        parse_positions("PG,QB")


def test_yahoo_positions_override_fallback(seeded_session):
    p = seeded_session.get(Player, 3)
    assert effective_positions(p) == (Position.SG, Position.SF)
    updated, unmatched = load_yahoo_positions(
        seeded_session,
        pd.DataFrame({"name": ["Wing Player Jr", "Nobody Here"], "positions": ["SF,PF", "PG"]}),
    )
    assert updated == 1
    assert unmatched["name"].tolist() == ["Nobody Here"]
    assert effective_positions(p) == (Position.SF, Position.PF)


def test_match_by_id_beats_name(seeded_session):
    frame = pd.DataFrame({"nba_id": [2, 999], "name": ["Star Guard", "Star Guard"]})
    matched, unmatched = match_players(seeded_session, frame)
    # id 2 exists -> matched to 2 even though the name says Star Guard;
    # id 999 doesn't exist -> falls back to the name -> player 1.
    assert matched["PLAYER_ID"].tolist() == [2, 1]
    assert unmatched.empty


def test_ambiguous_name_left_unmatched(seeded_session):
    seeded_session.add(Player(nba_id=5, name="Star Guard", normalized_name="star guard"))
    seeded_session.flush()
    matched, unmatched = match_players(seeded_session, pd.DataFrame({"name": ["Star Guard"]}))
    assert matched.empty and len(unmatched) == 1
