"""Draft Opportunity Score (DOS): the explainable recommendation score.

Pure function over a candidate frame plus per-player survival probabilities.
Every component is returned alongside the score so the UI and the LLM layer
can explain a recommendation without recomputing anything.

    score = 100 * ( w.value * value + w.fit * fit + w.scarcity * scarcity + w.gp * gp
                    + w.upside * upside + w.adp * adp_value
                    - w.injury * injury - w.uncertainty * (1 - confidence)
                    - w.return * p_return * value )

`value` is pool VORP relative to the best remaining player, so the score is
scale-free across scoring formats. The `return` term is the opportunity cost of
spending this pick on a player who would likely still be there next turn.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from legm.config.models import Position, RecommendationWeights

INJURY_RISK: dict[str, float] = {
    "out": 1.0,
    "out for season": 1.0,
    "season": 1.0,
    "injured": 0.8,
    "doubtful": 0.6,
    "questionable": 0.35,
    "day-to-day": 0.25,
    "probable": 0.1,
}


def injury_risk(status: str | None) -> float:
    if status is None or not isinstance(status, str) or not status.strip():
        return 0.0
    s = status.strip().lower()
    for key, risk in INJURY_RISK.items():
        if key in s:
            return risk
    return 0.3  # unknown non-empty status: mild penalty


def upside_from_age(age: float | None) -> float:
    """Youth-driven upside in [0, 1]: 1 at 20 or younger, 0 at 27 or older."""
    if age is None or np.isnan(age):
        return 0.3
    return float(np.clip((27.0 - age) / 7.0, 0.0, 1.0))


def adp_value(adp: float | None, current_pick: int, num_teams: int) -> float:
    """Positive when a player has fallen past their ADP, negative when it would be a reach. Clipped to [-1, 1]."""
    if adp is None or np.isnan(adp):
        return 0.0
    return float(np.clip((current_pick - adp) / num_teams, -1.0, 1.0))


def position_scarcity(
    available_positions: list[tuple[Position, ...]],
    available_original_vorp: np.ndarray,
    demand: dict[Position, int],
) -> dict[Position, float]:
    """1 - (remaining above-original-replacement players at P) / (num_teams x slots at P), clipped to [0, 1].
    Uses the pool's original VORP (from draft start) so scarcity measures depletion."""
    out: dict[Position, float] = {}
    for pos, need in demand.items():
        supply = sum(1 for ps, v in zip(available_positions, available_original_vorp, strict=True) if pos in ps and v > 0)
        out[pos] = float(np.clip(1.0 - supply / max(need, 1), 0.0, 1.0)) if need > 0 else 0.0
    return out


@dataclass(frozen=True)
class Preferences:
    """Learned user preferences in [-1, 1]; zero is neutral."""

    risk_tolerance: float = 0.0
    rookie_preference: float = 0.0
    upside_preference: float = 0.0
    injury_aversion: float = 0.0
    veteran_preference: float = 0.0
    adp_sensitivity: float = 0.0


def effective_weights(base: RecommendationWeights, prefs: Preferences) -> RecommendationWeights:
    """Scale base weights by preferences. Each preference moves its weight by up to +/-50%."""
    def scale(w: float, p: float) -> float:
        return w * (1.0 + 0.5 * float(np.clip(p, -1.0, 1.0)))

    return RecommendationWeights(
        value=base.value,
        fit=base.fit,
        scarcity=base.scarcity,
        gp=scale(base.gp, prefs.injury_aversion),
        upside=scale(base.upside, prefs.upside_preference + prefs.rookie_preference - prefs.veteran_preference),
        adp=scale(base.adp, prefs.adp_sensitivity),
        injury=scale(base.injury, prefs.injury_aversion - prefs.risk_tolerance),
        uncertainty=scale(base.uncertainty, -prefs.risk_tolerance),
        **{"return": base.return_},
    )


def opportunity_scores(
    cands: pd.DataFrame,
    p_return: pd.Series,
    weights: RecommendationWeights,
    open_positions: set[Position],
    scarcity: dict[Position, float],
    current_pick: int,
    num_teams: int,
    gp_cap: int,
) -> pd.DataFrame:
    """Score every row of `cands` (index = player id).

    Required columns: POSITION_LIST, VORP (pool), GP, ADP, AGE, INJURY_STATUS, CONFIDENCE.
    Returns a frame with SCORE and one column per component, sorted by SCORE desc.
    """
    if cands.empty:
        return cands.assign(SCORE=pd.Series(dtype=float))
    top = float(cands["VORP"].max())
    value = (cands["VORP"] / top).clip(lower=0.0) if top > 0 else pd.Series(0.0, index=cands.index)
    fit = cands["POSITION_LIST"].map(lambda ps: 1.0 if open_positions & set(ps) else 0.0)
    scar = cands["POSITION_LIST"].map(lambda ps: max((scarcity.get(p, 0.0) for p in ps), default=0.0))
    gp = (cands["GP"].astype(float) / float(gp_cap)).clip(0.0, 1.0)
    upside = cands["AGE"].map(upside_from_age) if "AGE" in cands else pd.Series(0.3, index=cands.index)
    adpv = cands["ADP"].map(lambda a: adp_value(a, current_pick, num_teams)) if "ADP" in cands else pd.Series(0.0, index=cands.index)
    injury = cands["INJURY_STATUS"].map(injury_risk) if "INJURY_STATUS" in cands else pd.Series(0.0, index=cands.index)
    conf = cands["CONFIDENCE"].astype(float).clip(0.0, 1.0) if "CONFIDENCE" in cands else pd.Series(0.7, index=cands.index)
    pret = p_return.reindex(cands.index).fillna(1.0).astype(float)

    score = 100.0 * (
        weights.value * value
        + weights.fit * fit
        + weights.scarcity * scar
        + weights.gp * gp
        + weights.upside * upside
        + weights.adp * adpv
        - weights.injury * injury
        - weights.uncertainty * (1.0 - conf)
        - weights.return_ * pret * value
    )
    out = cands.copy()
    out["C_VALUE"] = value
    out["C_FIT"] = fit
    out["C_SCARCITY"] = scar
    out["C_GP"] = gp
    out["C_UPSIDE"] = upside
    out["C_ADP"] = adpv
    out["C_INJURY"] = injury
    out["C_CONFIDENCE"] = conf
    out["P_RETURN"] = pret
    out["SCORE"] = score
    return out.sort_values(["SCORE", "VORP"], ascending=[False, False])
