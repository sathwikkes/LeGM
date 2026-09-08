import pytest

from legm.draft.order import (
    next_pick_for_team,
    pick_to_round_team,
    picks_until_team,
    round_team_to_pick,
    team_picks,
)


def test_snake_mapping_8_teams():
    assert pick_to_round_team(1, 8) == (1, 0)
    assert pick_to_round_team(8, 8) == (1, 7)
    assert pick_to_round_team(9, 8) == (2, 7)
    assert pick_to_round_team(16, 8) == (2, 0)
    assert pick_to_round_team(17, 8) == (3, 0)
    assert pick_to_round_team(104, 8) == (13, 7)
    assert pick_to_round_team(97, 8) == (13, 0)


def test_inverse_mapping():
    for p in range(1, 105):
        r, t = pick_to_round_team(p, 8)
        assert round_team_to_pick(r, t, 8) == p
    with pytest.raises(ValueError):
        pick_to_round_team(0, 8)
    with pytest.raises(ValueError):
        round_team_to_pick(1, 8, 8)


def test_team_picks():
    assert team_picks(0, 8, 3) == [1, 16, 17]
    assert team_picks(7, 8, 3) == [8, 9, 24]
    assert team_picks(2, 8, 2) == [3, 14]


def test_next_pick_and_picks_until():
    # Team 2 picks at 3, 14, 19, 30 ...
    assert next_pick_for_team(2, 1, 8, 13) == 3
    assert picks_until_team(2, 1, 8, 13) == 2
    assert picks_until_team(2, 3, 8, 13) == 0
    assert next_pick_for_team(2, 4, 8, 13) == 14
    assert picks_until_team(2, 4, 8, 13) == 10
    # Team 7 picks 8 then 9: zero picks in between.
    assert picks_until_team(7, 9, 8, 13) == 0
    assert picks_until_team(7, 10, 8, 13) == 24 - 10
    # Out of picks.
    assert next_pick_for_team(0, 105, 8, 13) is None
    assert picks_until_team(0, 105, 8, 13) is None
