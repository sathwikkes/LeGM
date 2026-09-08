import pytest

from legm.draft.simulate import simulate
from legm.draft.state import available, make_pick
from legm.sim.montecarlo import picks_until_user_turn, survival
from legm.sim.opponents import OpponentModel, build_candidates


def test_window_before_and_at_user_turn(draft):
    # user is team 2 (picks 3, 14, 19 ...). At pick 1: window = picks 1, 2 (teams 0 and 1).
    start, until, between = picks_until_user_turn(draft)
    assert (start, until) == (1, 3) and between == [(1, 0), (2, 1)]
    s = simulate(draft, stop_before_user=True)  # now pick 3, user on the clock
    start, until, between = picks_until_user_turn(s)
    assert (start, until) == (4, 14)
    assert [p for p, _ in between] == list(range(4, 14))
    assert all(t != 2 for _, t in between)


def test_survival_deterministic_opponents(draft):
    # sigma ~ 0: the two opponents take the top two consensus players; everyone else survives.
    model = OpponentModel(adp_sigma=1e-9, needs_bonus=0.0)
    res = survival(draft, model, n_sims=20, seed=1)
    cands = build_candidates(draft, model)
    ids = [int(x) for x in cands.player_ids]
    assert res.p(ids[0]) == 0.0 and res.p(ids[1]) == 0.0
    assert res.p(ids[2]) == 1.0 and res.p(ids[10]) == 1.0
    assert res.p(999999) == 1.0  # outside the window


def test_survival_monotone_and_seeded(draft):
    s = simulate(draft, stop_before_user=True)  # 10 opponent picks before the user's next turn
    model = OpponentModel(adp_sigma=6.0)
    a = survival(s, model, n_sims=800, seed=3)
    b = survival(s, model, n_sims=800, seed=3)
    assert a.probabilities == b.probabilities
    cands = build_candidates(s, model)
    ids = [int(x) for x in cands.player_ids]
    top, mid, deep = a.p(ids[0]), a.p(ids[12]), a.p(ids[40])
    assert top < 0.2 and deep > 0.8 and top <= mid <= deep
    assert 0.0 <= min(a.probabilities.values()) and max(a.probabilities.values()) <= 1.0


def test_survival_complete_draft(draft):
    s = simulate(draft)
    res = survival(s, OpponentModel(), n_sims=5)
    assert res.until_pick is None and res.picks_between == []


def test_needs_bonus_changes_behaviour(draft):
    # Give team 0 four centers via manual picks so C is no longer an open slot, then
    # a center should be *more* likely to survive team 0's pick with a needs bonus than without.
    from legm.config.models import Position as P
    from legm.draft.state import team_on_the_clock

    s = draft
    centers = [c for c in available(s) if c.positions == (P.C,)]
    others = [c for c in available(s) if P.C not in c.positions]
    ci = oi = 0
    while len([p for p in s.picks if p.team_index == 0]) < 4:
        if team_on_the_clock(s) == 0:
            s = make_pick(s, centers[ci].player_id); ci += 1
        else:
            s = make_pick(s, others[oi].player_id); oi += 1
    while team_on_the_clock(s) != 0:
        s = make_pick(s, others[oi].player_id); oi += 1
    # Pretend the user is team 1 so team 0's pick is inside the window.
    s = s.model_copy(update={"config": s.config.model_copy(update={"user_team_index": 1})})
    best_c = centers[ci].player_id
    with_bonus = survival(s, OpponentModel(adp_sigma=3.0, needs_bonus=10.0), n_sims=600, seed=0).p(best_c)
    without = survival(s, OpponentModel(adp_sigma=3.0, needs_bonus=0.0), n_sims=600, seed=0).p(best_c)
    assert with_bonus >= without
