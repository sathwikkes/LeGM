"""Draft value objects. DraftState is immutable: operations return new states."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from legm.config.models import LeagueConfig, Position


class PlayerCard(BaseModel):
    """Snapshot of a Phase 1 ranking row. The draft never re-reads the database."""

    model_config = ConfigDict(frozen=True)

    player_id: int
    name: str
    positions: tuple[Position, ...] = ()
    team: str | None = None
    gp: float
    fpg: float
    season_fp: float
    vorp: float
    adp: float | None = None
    age: float | None = None
    injury_status: str | None = None  # e.g. "out", "questionable", "day-to-day"; None = healthy/unknown
    confidence: float = 0.7  # projection confidence in [0, 1]
    projection_source: str | None = None


class DraftConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    num_teams: int = Field(gt=1)
    rounds: int = Field(gt=0)
    user_team_index: int = Field(ge=0)
    team_names: tuple[str, ...]
    draft_type: str = "snake"

    @property
    def total_picks(self) -> int:
        return self.num_teams * self.rounds


class Pick(BaseModel):
    model_config = ConfigDict(frozen=True)

    pick_number: int
    round: int
    team_index: int
    player_id: int
    made_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DraftState(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    config: DraftConfig
    league: LeagueConfig
    pool: dict[int, PlayerCard]
    picks: tuple[Pick, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TeamRoster(BaseModel):
    """Derived view of one team's roster at a point in the draft."""

    model_config = ConfigDict(frozen=True)

    team_index: int
    name: str
    player_ids: tuple[int, ...]
    slots: dict[str, int | None]
    open_positions: tuple[Position, ...]
    open_bench: int
