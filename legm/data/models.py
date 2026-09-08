"""ORM models. Per-game stats only; totals are derivable from GP.

Fantasy points are never stored: they are computed from the scoring config
at query time so a config change automatically re-values every player.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from legm.config.models import STAT_KEYS, Position

V0_SOURCE = "v0_blend"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class StatColumnsMixin:
    """Per-game rate columns shared by season stats and projections."""

    gp: Mapped[float] = mapped_column(Float, nullable=False)
    mpg: Mapped[float] = mapped_column(Float, nullable=False)
    pts: Mapped[float] = mapped_column(Float, nullable=False)
    reb: Mapped[float] = mapped_column(Float, nullable=False)
    ast: Mapped[float] = mapped_column(Float, nullable=False)
    stl: Mapped[float] = mapped_column(Float, nullable=False)
    blk: Mapped[float] = mapped_column(Float, nullable=False)
    tov: Mapped[float] = mapped_column(Float, nullable=False)
    fgm: Mapped[float | None] = mapped_column(Float)
    fga: Mapped[float | None] = mapped_column(Float)
    ftm: Mapped[float | None] = mapped_column(Float)
    fta: Mapped[float | None] = mapped_column(Float)
    fg3m: Mapped[float | None] = mapped_column(Float)

    def stat_row(self) -> dict[str, float | None]:
        """Stats keyed the way the engine expects (upper-case STAT_KEYS + GP/MPG)."""
        out: dict[str, float | None] = {"GP": self.gp, "MPG": self.mpg}
        for key in STAT_KEYS:
            out[key] = getattr(self, key.lower())
        return out


class Player(Base):
    __tablename__ = "players"

    nba_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    team: Mapped[str | None] = mapped_column(String(8))
    age: Mapped[float | None] = mapped_column(Float)
    nba_position: Mapped[str | None] = mapped_column(String(8))
    # Comma-separated Yahoo eligibility, e.g. "PG,SG". NULL until loaded from a
    # Yahoo export; legm.data.crosswalk provides the fallback from nba_position.
    yahoo_positions: Mapped[str | None] = mapped_column(String(32))
    injury_status: Mapped[str | None] = mapped_column(String(32))
    injury_note: Mapped[str | None] = mapped_column(String(255))

    season_stats: Mapped[list["SeasonStat"]] = relationship(back_populates="player")
    projections: Mapped[list["Projection"]] = relationship(back_populates="player")

    def yahoo_position_list(self) -> list[Position] | None:
        if not self.yahoo_positions:
            return None
        return [Position(p.strip()) for p in self.yahoo_positions.split(",") if p.strip()]


class SeasonStat(StatColumnsMixin, Base):
    __tablename__ = "season_stats"
    __table_args__ = (UniqueConstraint("player_id", "season", name="uq_season_stats_player_season"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.nba_id"), nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    team: Mapped[str | None] = mapped_column(String(8))
    age: Mapped[float | None] = mapped_column(Float)

    player: Mapped[Player] = relationship(back_populates="season_stats")


class Projection(StatColumnsMixin, Base):
    __tablename__ = "projections"
    __table_args__ = (UniqueConstraint("player_id", "source", name="uq_projections_player_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.nba_id"), nullable=False, index=True)
    # "v0_blend" or "csv:<filename>". CSV sources take precedence at rank time.
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    player: Mapped[Player] = relationship(back_populates="projections")


class Game(Base):
    """One scheduled NBA game. Team codes are tricodes (LAL, BOS), matching
    Player.team, so "does my player have a game tonight" is a set lookup."""

    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("season", "game_date", "home_team", "away_team", name="uq_games_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    game_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    home_team: Mapped[str] = mapped_column(String(8), nullable=False)
    away_team: Mapped[str] = mapped_column(String(8), nullable=False)
    nba_game_id: Mapped[str | None] = mapped_column(String(20))
    # preseason | regular | allstar | playin | playoffs | cup. Only "regular"
    # scores fantasy points; see legm.data.nba.GAME_TYPES.
    season_type: Mapped[str] = mapped_column(String(16), nullable=False, default="regular")


class Adp(Base):
    __tablename__ = "adp"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.nba_id"), primary_key=True, autoincrement=False)
    adp: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)


# ---- users, drafts, feedback (API-facing tables) ------------------------------

from sqlalchemy import Boolean, DateTime, Text  # noqa: E402


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class DraftRecord(Base):
    """A user's draft, stored as the DraftState JSON blob (portable across SQLite/Postgres)."""

    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("owner_id", "draft_id", name="uq_drafts_owner_draft"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    picks_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class Feedback(Base):
    """Thumbs up/down on a recommendation, with the context needed to learn preferences."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vote: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 / -1
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class UserPreference(Base):
    """Learned strategy preferences in [-1, 1]; 0 is neutral. Adjust recommendation weights."""

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, autoincrement=False)
    risk_tolerance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rookie_preference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    upside_preference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    injury_aversion: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    veteran_preference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    adp_sensitivity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    FIELDS = (
        "risk_tolerance",
        "rookie_preference",
        "upside_preference",
        "injury_aversion",
        "veteran_preference",
        "adp_sensitivity",
    )

    def as_dict(self) -> dict[str, float]:
        return {f: float(getattr(self, f)) for f in self.FIELDS}
