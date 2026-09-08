"""Convert engine objects into API schemas."""

from __future__ import annotations

import pandas as pd

from legm.config.models import LeagueConfig
from legm.draft.models import DraftState, PlayerCard
from legm.draft.roster import build_slots
from legm.draft.state import (
    all_rosters,
    available_frame,
    current_pick,
    current_round,
    is_complete,
    is_legal_pick,
    picks_before_user,
    team_on_the_clock,
    team_roster,
    user_next_pick,
)
from legm.engine.vorp import replacement_levels

from legm.api.schemas import (
    AvailableOut,
    AvailablePlayerOut,
    BenchedPlayerOut,
    ClockOut,
    DraftConfigOut,
    DraftOut,
    DraftSummaryOut,
    LeagueOut,
    LineupOut,
    LineupPlayerOut,
    LineupSlotOut,
    PickOut,
    PlayerOut,
    RosterOut,
    SlotOut,
)
from legm.engine.lineup import Lineup, PlayerDay


def player_out(card: PlayerCard, **overrides) -> PlayerOut:
    return PlayerOut(
        player_id=card.player_id,
        name=card.name,
        positions=[p.value for p in card.positions],
        team=card.team,
        gp=card.gp,
        fpg=card.fpg,
        season_fp=card.season_fp,
        vorp=card.vorp,
        adp=card.adp,
        **overrides,
    )


def player_out_from_row(pid: int, r: pd.Series) -> PlayerOut:
    adp = r.get("ADP")
    return PlayerOut(
        player_id=int(pid),
        name=str(r["NAME"]),
        positions=[p.value for p in r["POSITION_LIST"]],
        team=None if r["TEAM"] is None or pd.isna(r["TEAM"]) else str(r["TEAM"]),
        gp=float(r["GP"]),
        fpg=float(r["FPG"]),
        season_fp=float(r["SEASON_FP"]),
        vorp=float(r["VORP"]),
        adp=None if adp is None or pd.isna(adp) else float(adp),
    )


def clock_out(state: DraftState) -> ClockOut:
    team = team_on_the_clock(state)
    return ClockOut(
        current_pick=current_pick(state),
        current_round=current_round(state),
        team_on_the_clock=team,
        team_name_on_the_clock=None if team is None else state.config.team_names[team],
        is_user_turn=team is not None and team == state.config.user_team_index,
        user_next_pick=user_next_pick(state),
        picks_before_user=picks_before_user(state),
        is_complete=is_complete(state),
        total_picks=state.config.total_picks,
    )


def draft_out(state: DraftState) -> DraftOut:
    slots = build_slots(state.league)
    kinds = {s.label: s.kind for s in slots}
    rosters = []
    for r in all_rosters(state):
        rosters.append(
            RosterOut(
                team_index=r.team_index,
                name=r.name,
                is_user=r.team_index == state.config.user_team_index,
                slots=[
                    SlotOut(slot=label, kind=kinds[label], player=None if pid is None else player_out(state.pool[pid]))
                    for label, pid in r.slots.items()
                ],
                open_positions=[p.value for p in r.open_positions],
                open_bench=r.open_bench,
                player_count=len(r.player_ids),
            )
        )
    frame = available_frame(state, recompute_vorp=False)
    levels = (
        replacement_levels(frame["SEASON_FP"], frame["POSITION_LIST"], state.league) if not frame.empty else {}
    )
    return DraftOut(
        draft_id=state.draft_id,
        created_at=state.created_at,
        config=DraftConfigOut(
            num_teams=state.config.num_teams,
            rounds=state.config.rounds,
            user_team_index=state.config.user_team_index,
            team_names=list(state.config.team_names),
            draft_type=state.config.draft_type,
            slots=[s.label for s in slots],
        ),
        clock=clock_out(state),
        picks=[
            PickOut(
                pick_number=p.pick_number,
                round=p.round,
                team_index=p.team_index,
                team_name=state.config.team_names[p.team_index],
                player=player_out(state.pool[p.player_id]),
                made_at=p.made_at,
            )
            for p in state.picks
        ],
        rosters=rosters,
        replacement_levels={k: float(v) for k, v in levels.items()},
    )


def summary_out(state: DraftState) -> DraftSummaryOut:
    return DraftSummaryOut(
        draft_id=state.draft_id,
        created_at=state.created_at,
        picks_made=len(state.picks),
        total_picks=state.config.total_picks,
        num_teams=state.config.num_teams,
        user_team_index=state.config.user_team_index,
        is_complete=is_complete(state),
    )


def available_out(
    state: DraftState,
    team_index: int | None = None,
    query: str | None = None,
    position: str | None = None,
    limit: int = 50,
    offset: int = 0,
    p_return: dict[int, float] | None = None,
) -> AvailableOut:
    """Available players with VORP recomputed on the remaining pool, flagged for legality
    and roster fit relative to `team_index` (defaults to the user's team)."""
    from legm.data.names import normalize_name

    team = state.config.user_team_index if team_index is None else team_index
    frame = available_frame(state, recompute_vorp=True)
    levels = {k: float(v) for k, v in frame.attrs.get("replacement_levels", {}).items()}
    if query:
        q = normalize_name(query)
        frame = frame[frame["NAME"].map(lambda n: q in normalize_name(n))]
    if position:
        pos = position.upper()
        frame = frame[frame["POSITIONS"].map(lambda s: pos in s.split(","))]
    total = len(frame)
    roster = team_roster(state, team)
    open_pos = set(roster.open_positions)
    bench_open = roster.open_bench > 0
    players = []
    for pid, r in frame.iloc[offset : offset + limit].iterrows():
        card = state.pool[int(pid)]
        fills = bool(open_pos & set(card.positions))
        legal = bench_open or fills or is_legal_pick(state, team, int(pid))
        base = player_out_from_row(int(pid), r).model_dump()
        players.append(
            AvailablePlayerOut(
                **base,
                pool_vorp=float(r["VORP"]),
                legal_for_user=legal,
                fills_open_slot=fills,
                p_return=None if p_return is None else p_return.get(int(pid), 1.0),
                injury_status=card.injury_status,
                confidence=card.confidence,
            )
        )
    return AvailableOut(players=players, replacement_levels=levels, total=total)


def lineup_player_out(p: PlayerDay) -> LineupPlayerOut:
    return LineupPlayerOut(
        player_id=p.player_id,
        name=p.name,
        positions=[x.value for x in p.positions],
        team=p.team,
        fpg=p.fpg,
        injury_status=p.injury_status,
        opponent=p.opponent,
        play_probability=p.play_probability,
        expected_points=p.expected_points,
    )


def lineup_out(
    state: DraftState,
    team_index: int,
    lineup: Lineup,
    games_scheduled: int,
    schedule_loaded: bool,
) -> LineupOut:
    return LineupOut(
        date=lineup.day.isoformat(),
        team_index=team_index,
        team_name=state.config.team_names[team_index],
        slots=[
            LineupSlotOut(slot=s.slot, player=None if s.player is None else lineup_player_out(s.player))
            for s in lineup.slots
        ],
        bench=[BenchedPlayerOut(player=lineup_player_out(b.player), reason=b.reason) for b in lineup.bench],
        expected_points=lineup.expected_points,
        raw_points=lineup.raw_points,
        points_left_on_bench=lineup.points_left_on_bench,
        empty_slots=list(lineup.empty_slots),
        players_without_games=lineup.players_without_games,
        games_scheduled=games_scheduled,
        schedule_loaded=schedule_loaded,
    )


def league_out(league: LeagueConfig) -> LeagueOut:
    return LeagueOut(
        name=league.league.name,
        num_teams=league.league.num_teams,
        draft_type=league.league.draft_type,
        format=league.league.format,
        slots=list(league.roster.slots),
        bench=league.roster.bench,
        il=league.roster.il,
        scoring=league.scoring.weights(),
    )
