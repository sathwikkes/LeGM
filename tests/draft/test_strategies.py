import random

import pytest

from legm.config.models import Position as P
from legm.draft.models import PlayerCard
from legm.draft.state import available, make_pick, new_draft, team_on_the_clock, team_roster
from legm.draft.strategies import AdpOrder, BestAvailable, NeedsAware, make_strategy


def test_best_available_takes_top_vorp(draft):
    rng = random.Random(0)
    assert BestAvailable()(draft, 0, rng) == available(draft)[0].player_id


def test_adp_order_takes_lowest_adp(draft):
    rng = random.Random(0)
    pid = AdpOrder()(draft, 0, rng)
    lowest = min((c for c in available(draft) if c.adp is not None), key=lambda c: c.adp)
    assert pid == lowest.player_id
    # Player 7 has adp 11 while player 8 has adp 9 (deliberate inversion): adp order differs from vorp.
    s = draft
    for _ in range(7):
        s = make_pick(s, AdpOrder()(s, 0, rng))
    assert AdpOrder()(s, 0, rng) != BestAvailable()(s, 0, rng)


def test_needs_aware_skips_bench_when_starters_open(default_config):
    cfg = default_config.model_copy(deep=True)
    cfg.league.num_teams = 2
    pool = {
        i: PlayerCard(player_id=i, name=f"C{i}", positions=(P.C,), gp=70, fpg=40 - i, season_fp=(40 - i) * 70, vorp=1000 - i)
        for i in range(1, 13)
    }
    pool[20] = PlayerCard(player_id=20, name="Guard", positions=(P.PG,), gp=70, fpg=10, season_fp=700, vorp=-500)
    s = new_draft(cfg, pool, user_team_index=1)
    rng = random.Random(0)
    # 2-team snake: t0, t1, t1, t0, t0, t1, t1, t0, t0, t1 ...
    for _ in range(9):
        s = make_pick(s, BestAvailable()(s, team_on_the_clock(s), rng))
    assert team_on_the_clock(s) == 1
    assert P.C not in team_roster(s, 1).open_positions  # C1, C2, UTIL1, UTIL2 all centers
    assert BestAvailable()(s, 1, rng) != 20  # a center still has the higher VORP
    assert NeedsAware()(s, 1, rng) == 20  # but only the guard fills an open starting slot


def test_needs_aware_prefers_starter_over_higher_vorp_bench(draft):
    # Fill user team's guard slots by drafting only PG/SG players onto team 0, then check.
    rng = random.Random(1)
    s = draft
    guards = [c for c in available(s) if set(c.positions) <= {P.PG, P.SG}]
    # Team 0 picks at 1, 16, 17, 32, 33 ... we only control team 0's picks here by making
    # every other team pick a non-guard.
    non_guards = [c for c in available(s) if not (set(c.positions) & {P.PG, P.SG})]
    gi = ni = 0
    while len(team_roster(s, 0).player_ids) < 5:  # PG, SG, G, UTIL1, UTIL2
        if team_on_the_clock(s) == 0:
            s = make_pick(s, guards[gi].player_id)
            gi += 1
        else:
            s = make_pick(s, non_guards[ni].player_id)
            ni += 1
    roster = team_roster(s, 0)
    assert P.PG not in roster.open_positions and P.SG not in roster.open_positions
    # Advance to team 0's turn.
    while team_on_the_clock(s) != 0:
        s = make_pick(s, non_guards[ni].player_id)
        ni += 1
    pick = NeedsAware()(s, 0, rng)
    chosen = s.pool[pick]
    assert set(chosen.positions) & {P.SF, P.PF, P.C}
    best = BestAvailable()(s, 0, rng)
    if set(s.pool[best].positions) <= {P.PG, P.SG}:
        assert pick != best


def test_jitter_is_seeded(draft):
    a = BestAvailable(jitter=5)(draft, 0, random.Random(42))
    b = BestAvailable(jitter=5)(draft, 0, random.Random(42))
    c = BestAvailable(jitter=5)(draft, 0, random.Random(43))
    assert a == b
    top5 = {x.player_id for x in available(draft)[:5]}
    assert a in top5 and c in top5


def test_make_strategy():
    assert isinstance(make_strategy("needs", jitter=3), NeedsAware)
    with pytest.raises(ValueError):
        make_strategy("chaos")
