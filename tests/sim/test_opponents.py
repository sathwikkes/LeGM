import numpy as np
import pandas as pd

from legm.draft.state import available_frame
from legm.sim.opponents import OpponentModel, build_candidates, consensus_ranks, pick_probabilities


def test_consensus_rank_prefers_adp_then_vorp(draft):
    frame = available_frame(draft)
    ranks = consensus_ranks(frame)
    with_adp = frame["ADP"].notna()
    assert (ranks[with_adp] == frame.loc[with_adp, "ADP"]).all()
    # players without ADP get their VORP-order rank
    no_adp = frame.index[~with_adp]
    assert (ranks.loc[no_adp] == pd.Series(np.arange(1, len(frame) + 1, dtype=float), index=frame.index).loc[no_adp]).all()


def test_candidate_window(draft):
    cands = build_candidates(draft, OpponentModel(candidate_window=10))
    assert len(cands.player_ids) == 10
    assert list(cands.consensus_rank) == sorted(cands.consensus_rank)
    assert cands.index_of(int(cands.player_ids[3])) == 3 and cands.index_of(-1) is None


def test_zero_noise_picks_best_consensus(draft):
    probs = pick_probabilities(draft, 0, OpponentModel(adp_sigma=1e-9, needs_bonus=0.0), n_draws=50)
    cands = build_candidates(draft, OpponentModel())
    assert probs[0] == (int(cands.player_ids[0]), 1.0)


def test_noise_spreads_probability(draft):
    probs = pick_probabilities(draft, 0, OpponentModel(adp_sigma=6.0), n_draws=4000, top=10)
    assert len(probs) > 3
    assert abs(sum(p for _, p in probs) - 1.0) < 0.2  # top-10 covers most of the mass
    assert probs[0][1] < 1.0
