"""Thumbs up/down storage and the preference-learning rule.

Each vote nudges the preferences implied by the player's components by
LEARNING_RATE, clipped to [-1, 1]. No LLM involvement; fully inspectable.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from legm.api.schemas import RecommendationComponents
from legm.data.models import Feedback, UserPreference
from legm.engine.opportunity import Preferences

LEARNING_RATE = 0.1


def get_preferences(session: Session, user_id: int) -> UserPreference:
    pref = session.get(UserPreference, user_id)
    if pref is None:
        pref = UserPreference(user_id=user_id)
        session.add(pref)
        session.flush()
    return pref


def to_preferences(pref: UserPreference) -> Preferences:
    return Preferences(**pref.as_dict())


def nudges(components: RecommendationComponents, age: float | None, vote: int) -> dict[str, float]:
    """Which preference each vote moves, and by how much (before the learning rate)."""
    out: dict[str, float] = {}
    if components.injury_risk > 0:
        out["injury_aversion"] = -vote  # liking an injured player lowers aversion
    if components.confidence < 0.6:
        out["risk_tolerance"] = vote
    if components.upside >= 0.5:
        out["upside_preference"] = vote
    if age is not None:
        if age < 23:
            out["rookie_preference"] = vote
        elif age >= 30:
            out["veteran_preference"] = vote
    if abs(components.adp_value) >= 0.5:
        out["adp_sensitivity"] = vote if components.adp_value > 0 else -vote
    return out


def record_feedback(
    session: Session,
    user_id: int,
    draft_id: str,
    player_id: int,
    vote: int,
    components: RecommendationComponents,
    age: float | None,
) -> UserPreference:
    session.add(
        Feedback(
            user_id=user_id,
            draft_id=draft_id,
            player_id=player_id,
            vote=vote,
            context_json=json.dumps(components.model_dump()),
        )
    )
    pref = get_preferences(session, user_id)
    for field, direction in nudges(components, age, vote).items():
        value = float(getattr(pref, field)) + LEARNING_RATE * direction
        setattr(pref, field, max(-1.0, min(1.0, value)))
    session.flush()
    return pref
