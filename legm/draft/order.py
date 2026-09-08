"""Snake draft pick order. Picks and rounds are 1-indexed; team indexes are 0-indexed."""

from __future__ import annotations


def pick_to_round_team(pick_number: int, num_teams: int) -> tuple[int, int]:
    """(round, team_index) on the clock for a given overall pick number."""
    if pick_number < 1:
        raise ValueError("pick_number is 1-indexed")
    rnd = (pick_number - 1) // num_teams + 1
    offset = (pick_number - 1) % num_teams
    team = offset if rnd % 2 == 1 else num_teams - 1 - offset
    return rnd, team


def round_team_to_pick(rnd: int, team_index: int, num_teams: int) -> int:
    if rnd < 1 or not 0 <= team_index < num_teams:
        raise ValueError("bad round or team index")
    offset = team_index if rnd % 2 == 1 else num_teams - 1 - team_index
    return (rnd - 1) * num_teams + offset + 1


def team_picks(team_index: int, num_teams: int, rounds: int) -> list[int]:
    return [round_team_to_pick(r, team_index, num_teams) for r in range(1, rounds + 1)]


def next_pick_for_team(team_index: int, current_pick: int, num_teams: int, rounds: int) -> int | None:
    """The team's next pick number at or after `current_pick`, or None if it has none left."""
    for p in team_picks(team_index, num_teams, rounds):
        if p >= current_pick:
            return p
    return None


def picks_until_team(team_index: int, current_pick: int, num_teams: int, rounds: int) -> int | None:
    """How many other teams pick before `team_index` is on the clock (0 if it is now)."""
    nxt = next_pick_for_team(team_index, current_pick, num_teams, rounds)
    return None if nxt is None else nxt - current_pick
