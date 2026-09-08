import pytest

from legm.config.models import Position as P
from legm.draft.roster import (
    assign,
    build_slots,
    can_add,
    draftable_slots,
    fits,
    open_bench_slots,
    open_positions,
    open_starting_slots,
)


@pytest.fixture
def slots(default_config):
    return build_slots(default_config)


def test_slot_labels_and_kinds(slots):
    assert [s.label for s in slots] == [
        "PG", "SG", "G", "SF", "PF", "F", "C1", "C2", "UTIL1", "UTIL2", "BN1", "BN2", "BN3", "IL1",
    ]
    assert draftable_slots(slots) == 13
    assert slots[2].positions == (P.PG, P.SG)
    assert slots[-1].kind == "il" and not slots[-1].accepts([P.C])


def test_pg_fills_pg_then_g_then_util(slots):
    a = assign({1: (P.PG,)}, slots)
    assert a["PG"] == 1
    a = assign({1: (P.PG,), 2: (P.PG,)}, slots)
    assert a["PG"] == 1 and a["G"] == 2
    a = assign({1: (P.PG,), 2: (P.PG,), 3: (P.PG,)}, slots)
    assert {a["PG"], a["G"], a["UTIL1"]} == {1, 2, 3}
    a = assign({1: (P.PG,), 2: (P.PG,), 3: (P.PG,), 4: (P.PG,)}, slots)
    assert {a["PG"], a["G"], a["UTIL1"], a["UTIL2"]} == {1, 2, 3, 4}
    # Fifth PG goes to the bench.
    a = assign({i: (P.PG,) for i in range(1, 6)}, slots)
    assert a["BN1"] == 5 and a["SG"] is None


def test_center_only_fills_c_c_util(slots):
    a = assign({i: (P.C,) for i in range(1, 5)}, slots)
    assert {a["C1"], a["C2"], a["UTIL1"], a["UTIL2"]} == {1, 2, 3, 4}
    assert a["BN1"] is None
    a = assign({i: (P.C,) for i in range(1, 8)}, slots)  # 4 starters + 3 bench
    assert a["BN3"] == 7
    assert not fits({i: (P.C,) for i in range(1, 9)}, slots)  # 8th center has nowhere to go


def test_resolve_shifts_earlier_player(slots):
    # PG/SG player took PG; three pure PGs fill G, UTIL1, UTIL2; a fifth pure PG
    # can only start if the PG/SG player is shifted to SG. The re-solve does that.
    players = {1: (P.PG, P.SG), 2: (P.PG,), 3: (P.PG,), 4: (P.PG,)}
    a = assign(players, slots)
    assert a["PG"] == 1 and a["G"] == 2 and {a["UTIL1"], a["UTIL2"]} == {3, 4}
    players[5] = (P.PG,)
    a = assign(players, slots)
    assert a["SG"] == 1 and a["PG"] == 5 and a["BN1"] is None
    # Earlier players keep their slots when a free one serves the newcomer.
    b = assign({1: (P.PG,), 2: (P.PG,)}, slots)
    assert b["PG"] == 1 and b["G"] == 2


def test_open_positions_and_bench(slots):
    players = {}
    assert open_positions(players, slots) == list(P)
    assert open_bench_slots(players, slots) == 3
    players = {i: (P.PG,) for i in range(1, 5)}  # PG, G, UTIL1, UTIL2 used
    assert open_positions(players, slots) == [P.SG, P.SF, P.PF, P.C]
    labels = [s.label for s in open_starting_slots(players, slots)]
    assert labels == ["SG", "SF", "PF", "F", "C1", "C2"]
    players[5] = (P.PG,)  # bench
    assert open_bench_slots(players, slots) == 2


def test_can_add_and_full_roster(slots):
    players = {i: (P.PG,) for i in range(1, 5)}
    players.update({i: (P.C,) for i in range(5, 9)})  # C1, C2 + 2 bench... wait UTIL taken by PGs
    # PGs occupy PG, G, UTIL1, UTIL2; centers: C1, C2, BN1, BN2 -> 1 bench left.
    assert open_bench_slots(players, slots) == 1
    assert can_add(players, 9, (P.C,), slots)  # last bench slot
    players[9] = (P.C,)
    assert not can_add(players, 10, (P.C,), slots)
    assert can_add(players, 10, (P.SF,), slots)  # SF slot is open
    assert not can_add(players, 1, (P.SF,), slots)  # duplicate id


def test_no_position_player_takes_util_or_bench(slots):
    a = assign({1: ()}, slots)
    assert a["UTIL1"] == 1
    players = {1: (P.PG,), 2: (P.PG,), 3: (P.PG,), 4: (P.PG,), 5: ()}
    assert assign(players, slots)["BN1"] == 5
