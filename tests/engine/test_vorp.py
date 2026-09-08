import pytest

from legm.config.models import Position
from legm.engine.vorp import OVERALL, nth_best, replacement_levels, vorp


def test_nth_best():
    assert nth_best([1, 5, 3], 1) == 5
    assert nth_best([1, 5, 3], 3) == 1
    assert nth_best([1, 5, 3], 10) == 1  # fewer than n: smallest
    assert nth_best([], 3) == 0.0
    with pytest.raises(ValueError):
        nth_best([1], 0)


def test_replacement_levels_tiny_pool(tiny_config, tiny_pool):
    levels = replacement_levels(tiny_pool["SEASON_FP"], tiny_pool["POSITIONS"], tiny_config)
    # PG-eligible: 1200, 1100, 1000 (p3), 600 -> 4th best = 600
    assert levels["PG"] == 600.0
    # C-eligible: 850, 800, 750 (p7 PF/C), 700 -> 4th best = 700
    assert levels["C"] == 700.0
    # SG-eligible: 1000 (p3), 900 -> 2nd best = 900 (UTIL is the only slot)
    assert levels["SG"] == 900.0
    # SF-eligible: 650, 500 -> 2nd = 500
    assert levels["SF"] == 500.0
    # PF-eligible: 750, 550, 500 -> 2nd = 550
    assert levels["PF"] == 550.0
    # overall: 2 teams x 3 slots = 6th best = 800
    assert levels[OVERALL] == 800.0


def test_multi_position_player_counts_toward_each(tiny_config, tiny_pool):
    # Remove player 3 (PG/SG): SG pool becomes just 900 -> 2nd best falls back to 900 (only one),
    # PG pool 4th best becomes 600 still? PG: 1200,1100,600 -> 3 players, 4th best = 600.
    pool = tiny_pool.drop(index=3)
    levels = replacement_levels(pool["SEASON_FP"], pool["POSITIONS"], tiny_config)
    assert levels["SG"] == 900.0
    assert levels["PG"] == 600.0
    # And with player 3 present it changes SG's 2nd best to 900 vs ... confirm by adding a SG:
    pool2 = tiny_pool.copy()
    pool2.loc[13] = [950.0, (Position.SG,)]
    levels2 = replacement_levels(pool2["SEASON_FP"], pool2["POSITIONS"], tiny_config)
    # SG-eligible now: 1000 (p3), 950, 900 -> 2nd best = 950. Player 3 counted.
    assert levels2["SG"] == 950.0


def test_vorp_uses_lowest_eligible_replacement(tiny_config, tiny_pool):
    levels = replacement_levels(tiny_pool["SEASON_FP"], tiny_pool["POSITIONS"], tiny_config)
    v = vorp(tiny_pool["SEASON_FP"], tiny_pool["POSITIONS"], levels)
    assert v.loc[1] == 1200 - 600  # PG
    assert v.loc[3] == 1000 - 600  # PG/SG: min(600, 900) = 600
    assert v.loc[7] == 750 - 550  # PF/C: min(550, 700) = 550
    assert v.loc[12] == 500 - 500  # SF/PF: min(500, 550) = 500


def test_no_position_falls_back_to_overall(tiny_config, tiny_pool):
    pool = tiny_pool.copy()
    pool.loc[14] = [1000.0, ()]
    levels = replacement_levels(pool["SEASON_FP"], pool["POSITIONS"], tiny_config)
    v = vorp(pool["SEASON_FP"], pool["POSITIONS"], levels)
    assert v.loc[14] == 1000.0 - levels[OVERALL]


def test_default_config_slot_counts(default_config):
    # Yahoo default: every position can fill 4 starting slots -> 32nd best.
    for pos in Position:
        assert default_config.league.num_teams * default_config.roster.starting_slots_for(pos) == 32
    assert default_config.league.num_teams * default_config.roster.num_starting_slots == 80
