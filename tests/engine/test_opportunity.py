import numpy as np
import pandas as pd
import pytest

from legm.config.models import Position as P
from legm.config.models import RecommendationWeights
from legm.engine.opportunity import (
    Preferences,
    adp_value,
    effective_weights,
    injury_risk,
    opportunity_scores,
    position_scarcity,
    upside_from_age,
)


def test_component_helpers():
    assert injury_risk(None) == 0.0 and injury_risk("Out") == 1.0 and injury_risk("questionable") == 0.35
    assert injury_risk("weird") == 0.3
    assert upside_from_age(20) == 1.0 and upside_from_age(27) == 0.0 and upside_from_age(23.5) == 0.5
    assert upside_from_age(None) == 0.3
    assert adp_value(None, 10, 8) == 0.0
    assert adp_value(2.0, 10, 8) == 1.0  # fallen a full round: capped
    assert adp_value(14.0, 10, 8) == -0.5  # half-round reach
    assert adp_value(10.0, 10, 8) == 0.0


def test_scarcity():
    positions = [(P.C,), (P.C, P.PF), (P.PG,), (P.PG,), (P.SG,)]
    vorp = np.array([100, 50, 10, -5, 20])
    scar = position_scarcity(positions, vorp, {P.C: 4, P.PG: 2, P.SG: 1, P.SF: 2})
    assert scar[P.C] == pytest.approx(1 - 2 / 4)
    assert scar[P.PG] == pytest.approx(1 - 1 / 2)  # only one PG above replacement
    assert scar[P.SG] == 0.0
    assert scar[P.SF] == 1.0  # nobody left


def frame():
    return pd.DataFrame(
        {
            "POSITION_LIST": [(P.C,), (P.PG,), (P.SF,)],
            "VORP": [1000.0, 800.0, 500.0],
            "GP": [72.0, 36.0, 72.0],
            "ADP": [None, None, 30.0],
            "AGE": [30.0, 21.0, 27.0],
            "INJURY_STATUS": [None, None, "out"],
            "CONFIDENCE": [1.0, 1.0, 1.0],
        },
        index=[1, 2, 3],
    )


def test_hand_computed_scores():
    w = RecommendationWeights(value=1.0, fit=0.2, scarcity=0.0, gp=0.1, upside=0.0, adp=0.0, injury=0.5, uncertainty=0.0, **{"return": 0.4})
    p_return = pd.Series({1: 0.0, 2: 1.0, 3: 0.5})
    out = opportunity_scores(frame(), p_return, w, open_positions={P.PG}, scarcity={}, current_pick=10, num_teams=8, gp_cap=72)
    # Player 1: value 1.0, fit 0, gp 1.0, injury 0, return 0*1 -> 100*(1 + 0.1) = 110
    assert out.loc[1, "SCORE"] == pytest.approx(110.0)
    # Player 2: value .8, fit 1 (.2), gp .5 (.05), return 1.0*.8*.4 = .32 -> 100*(.8+.2+.05-.32) = 73
    assert out.loc[2, "SCORE"] == pytest.approx(73.0)
    # Player 3: value .5, gp .1, injury .5*1=.5, return .5*.5*.4=.1 -> 100*(.5+.1-.5-.1) = 0
    assert out.loc[3, "SCORE"] == pytest.approx(0.0)
    assert list(out.index) == [1, 2, 3]
    assert out.loc[2, "C_FIT"] == 1.0 and out.loc[3, "C_INJURY"] == 1.0 and out.loc[2, "P_RETURN"] == 1.0


def test_return_term_prefers_player_who_wont_be_there():
    w = RecommendationWeights()
    f = frame().iloc[:2].copy()
    f["VORP"] = [900.0, 900.0]
    f["GP"] = [72.0, 72.0]
    f["AGE"] = [25.0, 25.0]
    out = opportunity_scores(f, pd.Series({1: 0.1, 2: 0.9}), w, set(), {}, 5, 8, 72)
    assert out.index[0] == 1 and out.loc[1, "SCORE"] > out.loc[2, "SCORE"]


def test_effective_weights():
    base = RecommendationWeights()
    same = effective_weights(base, Preferences())
    assert same.injury == base.injury and same.upside == base.upside
    averse = effective_weights(base, Preferences(injury_aversion=1.0))
    assert averse.injury == pytest.approx(base.injury * 1.5) and averse.gp == pytest.approx(base.gp * 1.5)
    risky = effective_weights(base, Preferences(risk_tolerance=1.0))
    assert risky.uncertainty == pytest.approx(base.uncertainty * 0.5) and risky.injury == pytest.approx(base.injury * 0.5)
    assert effective_weights(base, Preferences(adp_sensitivity=-2.0)).adp == pytest.approx(base.adp * 0.5)


def test_empty_frame():
    out = opportunity_scores(frame().iloc[:0], pd.Series(dtype=float), RecommendationWeights(), set(), {}, 1, 8, 72)
    assert out.empty and "SCORE" in out.columns
