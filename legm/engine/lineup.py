"""Daily lineup optimization.

Given a roster, a day's NBA schedule and injury statuses, choose the legal
assignment of players to starting slots that maximizes expected fantasy points.

    expected points = FP/G x P(the player suits up)

P(play) comes from config/league.yaml's `lineup.play_probability`, keyed by
injury status; a player whose NBA team is idle scores nothing that day.

The optimizer is exact, not a heuristic. Sets of players that can be matched to
distinct starting slots form a transversal matroid, so offering players to
`match_in_order` in descending expected-points order yields a maximum-weight
basis -- the best possible lineup. Ties break on player id, so the result is
deterministic.

Every function here is pure: the caller supplies the roster and the day's
schedule, so nothing depends on DraftState or the database. Swapping the drafted
roster for an editable season roster later changes only the caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from legm.config.models import LineupConfig, Position
from legm.draft.models import PlayerCard
from legm.draft.roster import Slot, match_in_order

# Why a player is not in the starting lineup.
NO_GAME = "no_game"  # their NBA team is idle
RULED_OUT = "ruled_out"  # P(play) is zero, e.g. status "out"
OUTSCORED = "outscored"  # eligible and playing, but the slots were worth more


@dataclass(frozen=True)
class PlayerDay:
    """One rostered player's outlook for a single date."""

    player_id: int
    name: str
    positions: tuple[Position, ...]
    team: str | None
    fpg: float
    injury_status: str | None
    opponent: str | None  # None when the team is idle
    play_probability: float

    @property
    def has_game(self) -> bool:
        return self.opponent is not None

    @property
    def expected_points(self) -> float:
        """FP/G discounted by the chance the player actually suits up."""
        if not self.has_game:
            return 0.0
        return self.fpg * self.play_probability

    @property
    def startable(self) -> bool:
        return self.has_game and self.play_probability > 0.0


@dataclass(frozen=True)
class LineupSlot:
    slot: str
    player: PlayerDay | None


@dataclass(frozen=True)
class BenchedPlayer:
    player: PlayerDay
    reason: str


@dataclass(frozen=True)
class Lineup:
    day: date
    slots: tuple[LineupSlot, ...]
    bench: tuple[BenchedPlayer, ...]

    @property
    def starters(self) -> tuple[PlayerDay, ...]:
        return tuple(s.player for s in self.slots if s.player is not None)

    @property
    def expected_points(self) -> float:
        """Expected fantasy points from the chosen starters."""
        return sum(p.expected_points for p in self.starters)

    @property
    def raw_points(self) -> float:
        """Starters' FP/G before the injury discount, for comparison."""
        return sum(p.fpg for p in self.starters)

    @property
    def points_left_on_bench(self) -> float:
        """Expected points from players who could have started but had no slot.

        This is the SPEC's "usable fantasy points" gap: production lost to
        lineup congestion rather than to the schedule or an injury.
        """
        return sum(b.player.expected_points for b in self.bench if b.reason == OUTSCORED)

    @property
    def empty_slots(self) -> tuple[str, ...]:
        return tuple(s.slot for s in self.slots if s.player is None)

    @property
    def players_without_games(self) -> int:
        return sum(1 for b in self.bench if b.reason == NO_GAME)


def player_days(
    roster: Mapping[int, PlayerCard],
    opponents: Mapping[str, str],
    config: LineupConfig,
) -> dict[int, PlayerDay]:
    """Combine a roster with one day's schedule.

    `opponents` maps an NBA team code to who it plays that day (see
    legm.data.schedule.teams_playing_on); a player whose team is absent is idle.
    """
    out: dict[int, PlayerDay] = {}
    for pid, card in roster.items():
        team = card.team.upper() if card.team else None
        out[pid] = PlayerDay(
            player_id=pid,
            name=card.name,
            positions=tuple(card.positions),
            team=team,
            fpg=float(card.fpg),
            injury_status=card.injury_status,
            opponent=opponents.get(team) if team else None,
            play_probability=config.probability_for(card.injury_status),
        )
    return out


def _bench_reason(player: PlayerDay) -> str:
    if not player.has_game:
        return NO_GAME
    if player.play_probability <= 0.0:
        return RULED_OUT
    return OUTSCORED


def optimize_lineup(
    players: Mapping[int, PlayerDay],
    slots: Sequence[Slot],
    day: date,
) -> Lineup:
    """The highest expected-points legal lineup for `day`.

    Only starting slots are filled; bench and IL slots are not lineup decisions.
    """
    starting = [s for s in slots if s.kind == "start"]
    candidates = [p for p in players.values() if p.startable]
    # Descending expected points, then player id: greedy over a transversal
    # matroid is optimal, and the tie-break keeps the result deterministic.
    order = [p.player_id for p in sorted(candidates, key=lambda p: (-p.expected_points, p.player_id))]
    eligible = {p.player_id: p.positions for p in candidates}

    matched = match_in_order(eligible, starting, order)

    filled = {starting[si].label: players[pid] for pid, si in matched.items()}
    lineup_slots = tuple(LineupSlot(slot=s.label, player=filled.get(s.label)) for s in starting)
    bench = tuple(
        BenchedPlayer(player=p, reason=_bench_reason(p))
        for p in sorted(players.values(), key=lambda p: (-p.expected_points, p.player_id))
        if p.player_id not in matched
    )
    return Lineup(day=day, slots=lineup_slots, bench=bench)
