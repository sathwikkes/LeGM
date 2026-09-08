import pytest

from legm.config.models import Position as P
from legm.draft.models import PlayerCard
from legm.draft.pool import picks_needed, pool_shortfall
from tests.conftest import make_pool
from legm.draft.state import (
    DraftCompleteError,
    DraftError,
    IllegalRosterError,
    PlayerUnavailableError,
    all_rosters,
    available,
    available_frame,
    current_pick,
    current_round,
    is_complete,
    make_pick,
    new_draft,
    picks_before_user,
    team_on_the_clock,
    team_roster,
    undo,
    user_next_pick,
)


def test_new_draft_defaults(draft):
    assert draft.config.num_teams == 8 and draft.config.rounds == 13
    assert draft.config.total_picks == 104
    assert draft.config.team_names[2] == "Team 3"
    assert current_pick(draft) == 1 and current_round(draft) == 1 and team_on_the_clock(draft) == 0
    assert user_next_pick(draft) == 3 and picks_before_user(draft) == 2
    assert not is_complete(draft)


def test_new_draft_validation(default_config, pool):
    with pytest.raises(DraftError):
        new_draft(default_config, pool, user_team_index=8)
    with pytest.raises(DraftError):
        new_draft(default_config, pool, user_team_index=0, team_names=["a", "b"])


def test_make_pick_advances_and_removes(draft):
    top = available(draft)[0]
    s1 = make_pick(draft, top.player_id)
    assert draft.picks == ()  # original untouched
    assert s1.picks[0].player_id == top.player_id
    assert s1.picks[0].pick_number == 1 and s1.picks[0].round == 1 and s1.picks[0].team_index == 0
    assert top.player_id not in {c.player_id for c in available(s1)}
    assert current_pick(s1) == 2 and team_on_the_clock(s1) == 1
    assert picks_before_user(s1) == 1
    assert team_roster(s1, 0).player_ids == (top.player_id,)


def test_pick_unavailable_raises(draft):
    top = available(draft)[0]
    s1 = make_pick(draft, top.player_id)
    with pytest.raises(PlayerUnavailableError):
        make_pick(s1, top.player_id)
    with pytest.raises(PlayerUnavailableError):
        make_pick(s1, 999999)


def test_undo_restores_exact_state(draft):
    a = available(draft)
    s1 = make_pick(draft, a[0].player_id)
    s2 = make_pick(s1, a[1].player_id)
    back = undo(s2)
    assert back.picks == s1.picks
    assert available(back) == available(s1)
    assert team_on_the_clock(back) == 1
    assert undo(back).picks == ()
    with pytest.raises(DraftError):
        undo(draft)


def test_illegal_roster_pick_raises(default_config):
    cfg = default_config.model_copy(deep=True)
    cfg.league.num_teams = 2
    pool = {
        i: PlayerCard(player_id=i, name=f"C{i}", positions=(P.C,), gp=70, fpg=30, season_fp=2100, vorp=500)
        for i in range(1, 20)
    }
    pool.update({
        i: PlayerCard(player_id=i, name=f"W{i}", positions=(P.SF,), gp=70, fpg=20, season_fp=1400, vorp=100)
        for i in range(50, 70)
    })
    pool.update({
        i: PlayerCard(player_id=i, name=f"G{i}", positions=(P.PG,), gp=70, fpg=20, season_fp=1400, vorp=100)
        for i in range(70, 90)
    })
    s = new_draft(cfg, pool, user_team_index=0)
    centers = iter(range(1, 20))
    others = iter(x for pair in zip(range(50, 70), range(70, 90), strict=True) for x in pair)  # wing, guard, ...
    # Team 0 takes centers until it holds 7 (C1, C2, UTIL1, UTIL2, BN1-3); team 1 alternates wings/guards.
    while len(team_roster(s, 0).player_ids) < 7:
        s = make_pick(s, next(centers) if team_on_the_clock(s) == 0 else next(others))
    while team_on_the_clock(s) != 0:
        s = make_pick(s, next(others))
    with pytest.raises(IllegalRosterError):
        make_pick(s, next(centers))  # 8th center has nowhere to go
    s = make_pick(s, 60)  # a wing still fits the SF slot
    assert team_roster(s, 0).slots["SF"] == 60


def test_draft_completes(draft):
    s = draft
    for _ in range(104):
        s = make_pick(s, available(s)[0].player_id)
    assert is_complete(s) and current_round(s) is None and team_on_the_clock(s) is None
    assert user_next_pick(s) is None
    with pytest.raises(DraftCompleteError):
        make_pick(s, available(s)[0].player_id)
    for r in all_rosters(s):
        assert len(r.player_ids) == 13
        assert r.open_bench == 0
    assert len({p.player_id for p in s.picks}) == 104


def test_available_frame_recomputes_vorp(draft):
    before = available_frame(draft)
    assert "replacement_levels" in before.attrs
    s = draft
    for _ in range(20):
        s = make_pick(s, available(s)[0].player_id)
    after = available_frame(s)
    assert len(after) == len(before) - 20
    # Replacement levels drop as the pool thins, so every remaining VORP goes up or stays.
    common = after.index
    assert (after.loc[common, "VORP"] >= before.loc[common, "VORP"] - 1e-9).all()
    raw = available_frame(s, recompute_vorp=False)
    assert raw.loc[common[0], "VORP"] == draft.pool[int(common[0])].vorp


def test_num_teams_override(default_config):
    """The override is snapshotted onto the draft's own league config so every
    derived quantity (replacement levels, scarcity, opponents) follows it."""
    pool = make_pool(200)
    s = new_draft(default_config, pool, user_team_index=0, num_teams=12)
    assert s.config.num_teams == 12
    assert s.league.league.num_teams == 12
    assert default_config.league.num_teams == 8  # caller's config untouched
    assert s.config.team_names == tuple(f"Team {i + 1}" for i in range(12))
    assert s.config.rounds == 13 and s.config.total_picks == 156


def test_num_teams_override_shifts_replacement_levels(default_config):
    """More teams draft deeper, so the replacement baseline falls and VORP rises.
    This is the whole reason the override has to reach the league config."""
    pool = make_pool(200)
    eight = available_frame(new_draft(default_config, pool, user_team_index=0, num_teams=8))
    twelve = available_frame(new_draft(default_config, pool, user_team_index=0, num_teams=12))
    top = eight["VORP"].idxmax()
    assert twelve.loc[top, "VORP"] > eight.loc[top, "VORP"]


def test_num_teams_override_validation(default_config, pool):
    for bad in (1, 0, -3, 21):
        with pytest.raises(DraftError):
            new_draft(default_config, pool, user_team_index=0, num_teams=bad)
    with pytest.raises(DraftError):  # slot outside the overridden team count
        new_draft(default_config, pool, user_team_index=5, num_teams=4)
    with pytest.raises(DraftError):  # team names must match the overridden count
        new_draft(default_config, pool, user_team_index=0, num_teams=3, team_names=["a", "b"])


def test_num_teams_override_none_uses_config(default_config, pool):
    s = new_draft(default_config, pool, user_team_index=0, num_teams=None)
    assert s.config.num_teams == default_config.league.num_teams


def test_pool_shortfall_reports_only_when_short(default_config, pool):
    """13 rounds x 20 teams = 260 picks; the 130-player pool cannot cover it.
    new_draft itself stays permissive: the check guards the API and CLI, where a
    real pool meets a real team count."""
    assert pool_shortfall(pool, default_config, 8) is None
    assert "too few for 20 teams" in pool_shortfall(pool, default_config, 20)
    assert picks_needed(default_config, 12) == 156
    assert picks_needed(default_config) == 104  # falls back to the configured size
