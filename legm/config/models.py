"""Pydantic models for league configuration.

Everything about scoring, roster construction, team count and projection
parameters comes from config/league.yaml through these models.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Position(StrEnum):
    PG = "PG"
    SG = "SG"
    SF = "SF"
    PF = "PF"
    C = "C"


PLAYER_POSITIONS: tuple[Position, ...] = tuple(Position)

STAT_KEYS: tuple[str, ...] = (
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "FGM",
    "FGA",
    "FTM",
    "FTA",
    "FG3M",
)


MAX_TEAMS = 20  # Yahoo's ceiling; also the per-draft override limit.


class LeagueInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    num_teams: int = Field(gt=1, le=MAX_TEAMS)
    draft_type: Literal["snake", "auction"] = "snake"
    format: Literal["h2h_points", "h2h_categories", "roto"] = "h2h_points"


class RosterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slots: list[str] = Field(min_length=1)
    bench: int = Field(ge=0)
    il: int = Field(ge=0)
    eligibility: dict[str, list[Position]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_slots_resolvable(self) -> "RosterConfig":
        known = {p.value for p in Position}
        for slot in self.slots:
            if slot not in known and slot not in self.eligibility:
                raise ValueError(
                    f"roster slot {slot!r} is not a player position and has no "
                    f"eligibility entry"
                )
        return self

    def slot_positions(self, slot: str) -> tuple[Position, ...]:
        """Player positions that may fill a given slot."""
        if slot in self.eligibility:
            return tuple(self.eligibility[slot])
        return (Position(slot),)

    def starting_slots_for(self, position: Position) -> int:
        """Number of starting slots a player eligible at `position` may fill."""
        return sum(1 for slot in self.slots if position in self.slot_positions(slot))

    @property
    def num_starting_slots(self) -> int:
        return len(self.slots)


class ScoringConfig(BaseModel):
    """Fantasy points per unit of each stat. Missing stats score zero."""

    model_config = ConfigDict(extra="forbid")

    PTS: float = 0.0
    REB: float = 0.0
    AST: float = 0.0
    STL: float = 0.0
    BLK: float = 0.0
    TOV: float = 0.0
    FGM: float = 0.0
    FGA: float = 0.0
    FTM: float = 0.0
    FTA: float = 0.0
    FG3M: float = 0.0

    def weights(self) -> dict[str, float]:
        """Non-zero multipliers keyed by stat name."""
        return {k: v for k, v in self.model_dump().items() if v != 0.0}


class ProjectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_weights: list[float] = Field(min_length=1)
    gp_cap: int = Field(gt=0)

    @field_validator("season_weights")
    @classmethod
    def _positive(cls, v: list[float]) -> list[float]:
        if any(w <= 0 for w in v):
            raise ValueError("season_weights must all be positive")
        return v


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_sims: int = Field(default=500, ge=1, le=20000)
    adp_sigma: float = Field(default=6.0, gt=0)
    needs_bonus: float = Field(default=3.0, ge=0)
    candidate_window: int = Field(default=80, ge=5)


class RecommendationWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = 1.0
    fit: float = 0.15
    scarcity: float = 0.15
    gp: float = 0.10
    upside: float = 0.05
    adp: float = 0.05
    injury: float = 0.20
    uncertainty: float = 0.05
    return_: float = Field(default=0.35, alias="return")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecommendationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: RecommendationWeights = Field(default_factory=RecommendationWeights)


class LineupConfig(BaseModel):
    """Daily lineup optimizer settings.

    Injury status is free text from whatever source loaded it, so statuses are
    matched case-insensitively and anything unrecognised falls back to
    `default_probability` rather than silently benching a player.
    """

    model_config = ConfigDict(extra="forbid")

    play_probability: dict[str, float] = Field(default_factory=dict)
    default_probability: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("play_probability")
    @classmethod
    def _in_unit_interval(cls, v: dict[str, float]) -> dict[str, float]:
        for status, p in v.items():
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"play_probability[{status!r}] must be in [0, 1], got {p}")
        return {k.strip().lower(): float(p) for k, p in v.items()}

    def probability_for(self, status: str | None) -> float:
        """P(this player suits up), from their injury status."""
        if status is None:
            return self.default_probability
        return self.play_probability.get(status.strip().lower(), self.default_probability)


class LeagueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: LeagueInfo
    roster: RosterConfig
    scoring: ScoringConfig
    projection: ProjectionConfig
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)
    lineup: LineupConfig = Field(default_factory=LineupConfig)
