from __future__ import annotations

import itertools
from datetime import date

import pytest

from legm.config.models import LineupConfig
from legm.config.models import Position as P
from legm.draft.models import PlayerCard
from legm.draft.roster import build_slots
from legm.engine.lineup import (
    NO_GAME,
    OUTSCORED,
    RULED_OUT,
    optimize_lineup,
    player_days,
)

DAY = date(2025, 10, 21)


@pytest.fixture
def lineup_config() -> LineupConfig:
    return LineupConfig(
        play_probability={"out": 0.0, "doubtful": 0.25, "questionable": 0.5, "probable": 0.9},
        default_probability=1.0,
    )


def card(pid, name, positions, fpg, team="AAA", status=None):
    return PlayerCard(
        player_id=pid, name=name, positions=positions, team=team,
        gp=70, fpg=fpg, season_fp=fpg * 70, vorp=0.0, injury_status=status,
    )


def brute_force_best(players, slots):
    """Best achievable expected total, by trying every assignment. Only tractable
    for the tiny rosters used here, which is the point: it is an independent
    check on the matroid-greedy optimizer."""
    starting = [s for s in slots if s.kind == "start"]
    startable = [p for p in players.values() if p.startable]
    best = 0.0
    for r in range(min(len(startable), len(starting)) + 1):
        for chosen in itertools.combinations(startable, r):
            for assignment in itertools.permutations(range(len(starting)), r):
                if all(starting[si].accepts(p.positions) for p, si in zip(chosen, assignment, strict=True)):
                    best = max(best, sum(p.expected_points for p in chosen))
    return best


# ---- expected points --------------------------------------------------------

def test_expected_points_discounts_by_play_probability(lineup_config):
    roster = {
        1: card(1, "Healthy", (P.PG,), 40.0),
        2: card(2, "Questionable", (P.PG,), 40.0, status="questionable"),
        3: card(3, "Out", (P.PG,), 40.0, status="out"),
        4: card(4, "Unknown status", (P.PG,), 40.0, status="flu-ish"),
    }
    days = player_days(roster, {"AAA": "BBB"}, lineup_config)
    assert days[1].expected_points == 40.0
    assert days[2].expected_points == 20.0
    assert days[3].expected_points == 0.0 and not days[3].startable
    assert days[4].expected_points == 40.0  # unmapped status never silently benches


def test_idle_team_scores_nothing(lineup_config):
    roster = {1: card(1, "Plays", (P.PG,), 40.0, team="AAA"), 2: card(2, "Idle", (P.PG,), 50.0, team="ZZZ")}
    days = player_days(roster, {"AAA": "@BBB"}, lineup_config)
    assert days[1].has_game and days[1].opponent == "@BBB"
    assert not days[2].has_game and days[2].expected_points == 0.0 and not days[2].startable


def test_player_without_a_team_is_idle(lineup_config):
    days = player_days({1: card(1, "Free agent", (P.PG,), 40.0, team=None)}, {"AAA": "BBB"}, lineup_config)
    assert not days[1].has_game


def test_team_code_matching_is_case_insensitive(lineup_config):
    days = player_days({1: card(1, "X", (P.PG,), 40.0, team="aaa")}, {"AAA": "BBB"}, lineup_config)
    assert days[1].has_game


# ---- the optimizer ----------------------------------------------------------

def test_only_players_with_games_start(default_config, lineup_config):
    slots = build_slots(default_config)
    roster = {
        1: card(1, "Idle star", (P.PG,), 60.0, team="ZZZ"),
        2: card(2, "Playing scrub", (P.PG,), 10.0, team="AAA"),
        3: card(3, "Ruled out", (P.C,), 55.0, team="AAA", status="out"),
    }
    lineup = optimize_lineup(player_days(roster, {"AAA": "BBB"}, lineup_config), slots, DAY)
    assert [p.name for p in lineup.starters] == ["Playing scrub"]
    assert {b.player.name: b.reason for b in lineup.bench} == {"Idle star": NO_GAME, "Ruled out": RULED_OUT}
    assert lineup.expected_points == 10.0
    assert lineup.points_left_on_bench == 0.0  # nothing lost to congestion
    assert lineup.players_without_games == 1


def test_probability_flips_who_starts(default_config, lineup_config):
    """One PG slot in a 3-slot league: the healthy 30 beats the questionable 50."""
    cfg = default_config.model_copy(deep=True)
    cfg.roster.slots = ["PG"]
    slots = build_slots(cfg)
    roster = {
        1: card(1, "Questionable star", (P.PG,), 50.0, status="questionable"),  # 25.0
        2: card(2, "Healthy starter", (P.PG,), 30.0),  # 30.0
    }
    lineup = optimize_lineup(player_days(roster, {"AAA": "BBB"}, lineup_config), slots, DAY)
    assert [p.name for p in lineup.starters] == ["Healthy starter"]
    assert lineup.expected_points == 30.0
    assert lineup.points_left_on_bench == 25.0  # the star's expected points, lost to congestion
    assert [b.reason for b in lineup.bench] == [OUTSCORED]

    # a healthier star wins the same slot back
    roster[1] = card(1, "Probable star", (P.PG,), 50.0, status="probable")  # 45.0
    lineup = optimize_lineup(player_days(roster, {"AAA": "BBB"}, lineup_config), slots, DAY)
    assert [p.name for p in lineup.starters] == ["Probable star"]


def test_multi_position_player_shifts_to_admit_a_better_one(default_config, lineup_config):
    """The G slot exists so a second guard can play: PG1 must slide to G."""
    cfg = default_config.model_copy(deep=True)
    cfg.roster.slots = ["PG", "G"]
    slots = build_slots(cfg)
    roster = {
        1: card(1, "Combo guard", (P.PG, P.SG), 30.0),
        2: card(2, "Pure PG", (P.PG,), 40.0),
    }
    lineup = optimize_lineup(player_days(roster, {"AAA": "BBB"}, lineup_config), slots, DAY)
    placed = {s.slot: s.player.name for s in lineup.slots if s.player}
    assert placed == {"PG": "Pure PG", "G": "Combo guard"}
    assert lineup.expected_points == 70.0 and not lineup.bench


def test_lineup_is_optimal_against_brute_force(default_config, lineup_config):
    """The greedy matroid argument, checked exhaustively on a small roster."""
    cfg = default_config.model_copy(deep=True)
    cfg.roster.slots = ["PG", "G", "C", "UTIL"]
    slots = build_slots(cfg)
    roster = {
        1: card(1, "A", (P.PG,), 44.0),
        2: card(2, "B", (P.PG, P.SG), 41.0),
        3: card(3, "C", (P.SG,), 38.0, status="questionable"),
        4: card(4, "D", (P.C,), 36.0),
        5: card(5, "E", (P.C, P.PF), 33.0),
        6: card(6, "F", (P.SF,), 30.0, status="probable"),
        7: card(7, "G", (P.PG,), 28.0),
        8: card(8, "H", (P.PF,), 25.0, team="ZZZ"),  # idle
        9: card(9, "I", (P.C,), 50.0, status="out"),  # ruled out
    }
    days = player_days(roster, {"AAA": "BBB"}, lineup_config)
    lineup = optimize_lineup(days, slots, DAY)
    assert lineup.expected_points == pytest.approx(brute_force_best(days, slots))


@pytest.mark.parametrize("seed", range(25))
def test_optimal_on_random_rosters(default_config, lineup_config, seed):
    """Randomised rosters, each verified against brute force."""
    import random

    rng = random.Random(seed)
    pos_sets = [(P.PG,), (P.SG,), (P.SF,), (P.PF,), (P.C,), (P.PG, P.SG), (P.SF, P.PF), (P.PF, P.C)]
    statuses = [None, "questionable", "probable", "doubtful", "out"]
    cfg = default_config.model_copy(deep=True)
    cfg.roster.slots = rng.sample(["PG", "SG", "G", "F", "C", "UTIL"], k=rng.randint(2, 4))
    slots = build_slots(cfg)
    roster = {
        i: card(i, f"P{i}", rng.choice(pos_sets), round(rng.uniform(5, 50), 1),
                team=rng.choice(["AAA", "BBB", "ZZZ"]), status=rng.choice(statuses))
        for i in range(1, 9)
    }
    days = player_days(roster, {"AAA": "BBB", "BBB": "@AAA"}, lineup_config)
    lineup = optimize_lineup(days, slots, DAY)
    assert lineup.expected_points == pytest.approx(brute_force_best(days, slots))
    # a player is either started exactly once or benched with a reason
    started = [p.player_id for p in lineup.starters]
    assert len(started) == len(set(started))
    assert set(started) | {b.player.player_id for b in lineup.bench} == set(roster)


def test_deterministic_on_ties(default_config, lineup_config):
    """Equal expected points must not make the lineup wobble between calls."""
    cfg = default_config.model_copy(deep=True)
    cfg.roster.slots = ["PG"]
    slots = build_slots(cfg)
    roster = {i: card(i, f"P{i}", (P.PG,), 30.0) for i in range(1, 6)}
    days = player_days(roster, {"AAA": "BBB"}, lineup_config)
    picks = {optimize_lineup(days, slots, DAY).starters[0].player_id for _ in range(5)}
    assert picks == {1}  # lowest id wins a tie


def test_empty_and_idle_rosters(default_config, lineup_config):
    slots = build_slots(default_config)
    empty = optimize_lineup({}, slots, DAY)
    assert not empty.starters and not empty.bench and empty.expected_points == 0.0
    assert len(empty.empty_slots) == default_config.roster.num_starting_slots

    idle = optimize_lineup(
        player_days({1: card(1, "Idle", (P.PG,), 40.0, team="ZZZ")}, {}, lineup_config), slots, DAY
    )
    assert not idle.starters and idle.bench[0].reason == NO_GAME


def test_bench_and_il_slots_are_not_lineup_decisions(default_config, lineup_config):
    """Only starting slots are filled; BN/IL are roster storage, not a lineup."""
    slots = build_slots(default_config)
    roster = {i: card(i, f"P{i}", (P.PG,), 40.0 - i) for i in range(1, 15)}
    lineup = optimize_lineup(player_days(roster, {"AAA": "BBB"}, lineup_config), slots, DAY)
    assert {s.slot for s in lineup.slots}.isdisjoint({"BN1", "BN2", "BN3", "IL1"})
    assert len(lineup.slots) == default_config.roster.num_starting_slots
    # 14 PGs, but only PG/G/UTIL1/UTIL2 accept them
    assert len(lineup.starters) == 4
    assert all(b.reason == OUTSCORED for b in lineup.bench)
    assert lineup.points_left_on_bench > 0
