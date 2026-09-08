"""DraftState operations. All functions are pure: they return new states or views."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

import pandas as pd
from pydantic import ValidationError

from legm.config.models import MAX_TEAMS, LeagueConfig, LeagueInfo, Position
from legm.draft.models import DraftConfig, DraftState, Pick, PlayerCard, TeamRoster
from legm.draft.order import next_pick_for_team, pick_to_round_team, picks_until_team
from legm.draft.roster import assign, build_slots, can_add, open_bench_slots, open_positions
from legm.engine.vorp import replacement_levels, vorp


class DraftError(Exception):
    pass


class PlayerUnavailableError(DraftError):
    pass


class IllegalRosterError(DraftError):
    pass


class DraftCompleteError(DraftError):
    pass


def new_draft(
    league: LeagueConfig,
    pool: Mapping[int, PlayerCard],
    user_team_index: int,
    team_names: Sequence[str] | None = None,
    draft_id: str | None = None,
    rounds: int | None = None,
    num_teams: int | None = None,
) -> DraftState:
    """Start a draft. `num_teams` overrides the configured league size for this
    draft only: the override is snapshotted onto the state's own league config,
    so replacement levels, scarcity and opponent modelling all follow it."""
    if num_teams is not None and num_teams != league.league.num_teams:
        try:
            info = LeagueInfo.model_validate({**league.league.model_dump(), "num_teams": num_teams})
        except ValidationError as exc:
            raise DraftError(f"num_teams must be in [2, {MAX_TEAMS}], got {num_teams}") from exc
        league = league.model_copy(update={"league": info})
    n = league.league.num_teams
    if not 0 <= user_team_index < n:
        raise DraftError(f"user_team_index must be in [0, {n})")
    names = tuple(team_names) if team_names else tuple(f"Team {i + 1}" for i in range(n))
    if len(names) != n:
        raise DraftError(f"expected {n} team names, got {len(names)}")
    rounds = rounds or (league.roster.num_starting_slots + league.roster.bench)
    config = DraftConfig(
        num_teams=n,
        rounds=rounds,
        user_team_index=user_team_index,
        team_names=names,
        draft_type=league.league.draft_type,
    )
    return DraftState(draft_id=draft_id or uuid.uuid4().hex[:8], config=config, league=league, pool=dict(pool))


# ---- derived scalars -------------------------------------------------------

def current_pick(state: DraftState) -> int:
    return len(state.picks) + 1


def is_complete(state: DraftState) -> bool:
    return len(state.picks) >= state.config.total_picks


def current_round(state: DraftState) -> int | None:
    if is_complete(state):
        return None
    return pick_to_round_team(current_pick(state), state.config.num_teams)[0]


def team_on_the_clock(state: DraftState) -> int | None:
    if is_complete(state):
        return None
    return pick_to_round_team(current_pick(state), state.config.num_teams)[1]


def user_next_pick(state: DraftState) -> int | None:
    if is_complete(state):
        return None
    return next_pick_for_team(
        state.config.user_team_index, current_pick(state), state.config.num_teams, state.config.rounds
    )


def picks_before_user(state: DraftState) -> int | None:
    if is_complete(state):
        return None
    return picks_until_team(
        state.config.user_team_index, current_pick(state), state.config.num_teams, state.config.rounds
    )


# ---- pool views ------------------------------------------------------------

def drafted_ids(state: DraftState) -> set[int]:
    return {p.player_id for p in state.picks}


def available(state: DraftState) -> list[PlayerCard]:
    taken = drafted_ids(state)
    cards = [c for pid, c in state.pool.items() if pid not in taken]
    return sorted(cards, key=lambda c: (-c.vorp, -c.season_fp, c.name))


def available_frame(state: DraftState, recompute_vorp: bool = True) -> pd.DataFrame:
    """Available players as a frame. With recompute_vorp, replacement levels are
    re-derived from the remaining pool so VORP reflects what is left."""
    cards = available(state)
    frame = pd.DataFrame(
        [
            {
                "PLAYER_ID": c.player_id,
                "NAME": c.name,
                "POSITION_LIST": c.positions,
                "POSITIONS": ",".join(p.value for p in c.positions),
                "TEAM": c.team,
                "GP": c.gp,
                "FPG": c.fpg,
                "SEASON_FP": c.season_fp,
                "VORP": c.vorp,
                "ADP": c.adp,
                "AGE": c.age,
                "INJURY_STATUS": c.injury_status,
                "CONFIDENCE": c.confidence,
                "SOURCE": c.projection_source,
                "ORIGINAL_VORP": c.vorp,
            }
            for c in cards
        ],
        columns=[
            "PLAYER_ID", "NAME", "POSITION_LIST", "POSITIONS", "TEAM", "GP", "FPG", "SEASON_FP", "VORP", "ADP",
            "AGE", "INJURY_STATUS", "CONFIDENCE", "SOURCE", "ORIGINAL_VORP",
        ],
    ).set_index("PLAYER_ID")
    if recompute_vorp and not frame.empty:
        levels = replacement_levels(frame["SEASON_FP"], frame["POSITION_LIST"], state.league)
        frame["VORP"] = vorp(frame["SEASON_FP"], frame["POSITION_LIST"], levels)
        frame = frame.sort_values(["VORP", "SEASON_FP", "NAME"], ascending=[False, False, True])
        frame.attrs["replacement_levels"] = levels
    return frame


# ---- rosters ---------------------------------------------------------------

def team_player_ids(state: DraftState, team_index: int) -> tuple[int, ...]:
    return tuple(p.player_id for p in state.picks if p.team_index == team_index)


def _positions_of(state: DraftState, pids: Sequence[int]) -> dict[int, tuple[Position, ...]]:
    return {pid: state.pool[pid].positions for pid in pids}


def team_roster(state: DraftState, team_index: int) -> TeamRoster:
    slots = build_slots(state.league)
    pids = team_player_ids(state, team_index)
    players = _positions_of(state, pids)
    slot_map = assign(players, slots)
    if slot_map is None:  # cannot happen through make_pick, but be defensive
        raise IllegalRosterError(f"team {team_index} roster does not fit its slots")
    return TeamRoster(
        team_index=team_index,
        name=state.config.team_names[team_index],
        player_ids=pids,
        slots=slot_map,
        open_positions=tuple(open_positions(players, slots)),
        open_bench=open_bench_slots(players, slots),
    )


def all_rosters(state: DraftState) -> list[TeamRoster]:
    return [team_roster(state, i) for i in range(state.config.num_teams)]


# ---- transitions -----------------------------------------------------------

def is_legal_pick(state: DraftState, team_index: int, player_id: int) -> bool:
    slots = build_slots(state.league)
    players = _positions_of(state, team_player_ids(state, team_index))
    return can_add(players, player_id, state.pool[player_id].positions, slots)


def make_pick(state: DraftState, player_id: int) -> DraftState:
    """Record the pick for the team on the clock. Returns the new state."""
    if is_complete(state):
        raise DraftCompleteError("draft is complete")
    if player_id not in state.pool:
        raise PlayerUnavailableError(f"player {player_id} is not in the draft pool")
    if player_id in drafted_ids(state):
        raise PlayerUnavailableError(f"{state.pool[player_id].name} has already been drafted")
    pick_no = current_pick(state)
    rnd, team = pick_to_round_team(pick_no, state.config.num_teams)
    if not is_legal_pick(state, team, player_id):
        raise IllegalRosterError(
            f"{state.pool[player_id].name} does not fit {state.config.team_names[team]}'s open slots"
        )
    pick = Pick(pick_number=pick_no, round=rnd, team_index=team, player_id=player_id)
    return state.model_copy(update={"picks": (*state.picks, pick)})


def undo(state: DraftState) -> DraftState:
    """Remove the most recent pick. Rosters are derived from picks, so nothing else changes."""
    if not state.picks:
        raise DraftError("nothing to undo")
    return state.model_copy(update={"picks": state.picks[:-1]})
