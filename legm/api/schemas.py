"""Response/request models for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlayerOut(BaseModel):
    player_id: int
    name: str
    positions: list[str]
    team: str | None
    gp: float
    fpg: float
    season_fp: float
    vorp: float
    adp: float | None = None


class AvailablePlayerOut(PlayerOut):
    pool_vorp: float
    legal_for_user: bool
    fills_open_slot: bool
    p_return: float | None = None
    injury_status: str | None = None
    confidence: float = 0.7


class PickOut(BaseModel):
    pick_number: int
    round: int
    team_index: int
    team_name: str
    player: PlayerOut
    made_at: datetime


class SlotOut(BaseModel):
    slot: str
    kind: str
    player: PlayerOut | None


class RosterOut(BaseModel):
    team_index: int
    name: str
    is_user: bool
    slots: list[SlotOut]
    open_positions: list[str]
    open_bench: int
    player_count: int


class ClockOut(BaseModel):
    current_pick: int
    current_round: int | None
    team_on_the_clock: int | None
    team_name_on_the_clock: str | None
    is_user_turn: bool
    user_next_pick: int | None
    picks_before_user: int | None
    is_complete: bool
    total_picks: int


class DraftConfigOut(BaseModel):
    num_teams: int
    rounds: int
    user_team_index: int
    team_names: list[str]
    draft_type: str
    slots: list[str]


class DraftOut(BaseModel):
    draft_id: str
    created_at: datetime
    config: DraftConfigOut
    clock: ClockOut
    picks: list[PickOut]
    rosters: list[RosterOut]
    replacement_levels: dict[str, float]


class DraftSummaryOut(BaseModel):
    draft_id: str
    created_at: datetime
    picks_made: int
    total_picks: int
    num_teams: int
    user_team_index: int
    is_complete: bool


class AvailableOut(BaseModel):
    players: list[AvailablePlayerOut]
    replacement_levels: dict[str, float]
    total: int


class RecommendationComponents(BaseModel):
    score: float | None
    value: float
    pool_vorp: float
    vorp: float
    season_fp: float
    fpg: float
    gp: float
    gp_norm: float
    fit: float
    open_positions_filled: list[str]
    scarcity: float
    upside: float
    adp: float | None
    adp_value: float
    injury_status: str | None
    injury_risk: float
    confidence: float
    p_return: float


class RecommendationOut(BaseModel):
    rank: int
    player: PlayerOut
    score: float
    components: RecommendationComponents
    reasons: list[str]


class RecommendationsOut(BaseModel):
    for_team: int
    is_user_turn: bool
    until_pick: int | None
    n_sims: int
    scarcity: dict[str, float]
    recommendations: list[RecommendationOut]


class SurvivalEntryOut(BaseModel):
    player: PlayerOut
    p_return: float
    consensus_rank: float


class SurvivalOut(BaseModel):
    from_pick: int
    until_pick: int | None
    n_sims: int
    picks_between: list[dict]
    players: list[SurvivalEntryOut]


class TargetOut(BaseModel):
    player: PlayerOut
    probability: float


class OpponentOut(BaseModel):
    team_index: int
    team_name: str
    pick_number: int
    open_positions: list[str]
    open_bench: int
    roster: list[PlayerOut]
    likely_targets: list[TargetOut]


class OpponentsOut(BaseModel):
    until_pick: int | None
    opponents: list[OpponentOut]


class ComparePlayerOut(BaseModel):
    player: PlayerOut
    drafted: bool
    legal_for_user: bool
    components: RecommendationComponents


class CompareOut(BaseModel):
    players: list[ComparePlayerOut]
    until_pick: int | None


class FeedbackIn(BaseModel):
    player_id: int
    vote: int = Field(ge=-1, le=1)


class PreferencesOut(BaseModel):
    risk_tolerance: float = 0.0
    rookie_preference: float = 0.0
    upside_preference: float = 0.0
    injury_aversion: float = 0.0
    veteran_preference: float = 0.0
    adp_sensitivity: float = 0.0


class PreferencesIn(PreferencesOut):
    pass


class CreateDraftIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    user_slot: int = Field(ge=1, description="1-based draft slot")
    team_names: list[str] | None = None
    include_inactive: bool = False


class PickIn(BaseModel):
    player_id: int


class SimulateIn(BaseModel):
    strategy: str = "needs"
    jitter: int = Field(default=3, ge=1, le=20)
    seed: int | None = None
    until_user: bool = True


class LeagueOut(BaseModel):
    name: str
    num_teams: int
    draft_type: str
    format: str
    slots: list[str]
    bench: int
    il: int
    scoring: dict[str, float]


class ChatMessageIn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


class ChatIn(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=40)


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[dict]
    model: str
    stop_reason: str | None
    usage: dict[str, int]


class LLMStatusOut(BaseModel):
    available: bool
    model: str
    tools: list[str]


class ImportPicksIn(BaseModel):
    format: str = Field(pattern="^(csv|json)$")
    content: str = Field(min_length=1, max_length=200_000)


class ImportReportOut(BaseModel):
    applied: int
    skipped: list[dict]
    draft: DraftOut
