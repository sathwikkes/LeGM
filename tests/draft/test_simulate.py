from legm.draft.simulate import simulate, simulate_until_user
from legm.draft.state import all_rosters, current_pick, is_complete, team_on_the_clock
from legm.draft.strategies import AdpOrder, BestAvailable, NeedsAware


def test_full_mock_draft_completes(draft):
    s = simulate(draft, default=NeedsAware(jitter=3), seed=7)
    assert is_complete(s)
    assert len(s.picks) == 104
    assert len({p.player_id for p in s.picks}) == 104
    for r in all_rosters(s):
        assert len(r.player_ids) == 13 and r.open_bench == 0
        assert all(v is not None for k, v in r.slots.items() if not k.startswith("IL"))


def test_same_seed_same_result(draft):
    a = simulate(draft, default=BestAvailable(jitter=4), seed=11)
    b = simulate(draft, default=BestAvailable(jitter=4), seed=11)
    c = simulate(draft, default=BestAvailable(jitter=4), seed=12)
    assert [p.player_id for p in a.picks] == [p.player_id for p in b.picks]
    assert [p.player_id for p in a.picks] != [p.player_id for p in c.picks]


def test_per_team_strategies_and_stop_before_user(draft):
    s = simulate(draft, strategies={1: AdpOrder()}, stop_before_user=True, seed=0)
    assert current_pick(s) == 3 and team_on_the_clock(s) == 2
    s2 = simulate_until_user(s)  # already user's turn: no-op
    assert s2.picks == s.picks
    s3 = simulate(s, until_pick=5, seed=0)
    assert current_pick(s3) == 5


def test_simulate_until_user_after_user_pick(draft):
    from legm.draft.state import available, make_pick

    s = simulate(draft, stop_before_user=True)
    s = make_pick(s, available(s)[0].player_id)  # user picks at 3
    s = simulate_until_user(s)
    assert current_pick(s) == 14 and team_on_the_clock(s) == 2
