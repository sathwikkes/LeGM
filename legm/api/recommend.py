"""Recommendations for the team on the clock: Draft Opportunity Score over the candidate
window, with Monte Carlo survival probabilities and per-component explanations."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import pandas as pd

from legm.api.schemas import (
    CompareOut,
    ComparePlayerOut,
    OpponentOut,
    OpponentsOut,
    RecommendationComponents,
    RecommendationOut,
    RecommendationsOut,
    SurvivalEntryOut,
    SurvivalOut,
    TargetOut,
)
from legm.api.views import player_out
from legm.config.models import LeagueConfig, Position
from legm.draft.models import DraftState, PlayerCard
from legm.draft.state import current_pick, is_legal_pick, team_on_the_clock, team_roster
from legm.engine.opportunity import Preferences, effective_weights, opportunity_scores, position_scarcity
from legm.sim.montecarlo import SurvivalResult, survival
from legm.sim.opponents import Candidates, OpponentModel, build_candidates, pick_probabilities


class SurvivalCache:
    """Memoize survival results per draft moment (owner, draft, picks so far)."""

    def __init__(self, maxsize: int = 128):
        self._data: OrderedDict[str, tuple[Candidates, SurvivalResult]] = OrderedDict()
        self._lock = threading.Lock()
        self.maxsize = maxsize

    @staticmethod
    def key(owner_id: int, state: DraftState) -> str:
        h = hashlib.sha1(",".join(str(p.player_id) for p in state.picks).encode()).hexdigest()[:16]
        return f"{owner_id}:{state.draft_id}:{len(state.picks)}:{h}"

    def get_or_compute(self, owner_id: int, state: DraftState, league: LeagueConfig, seed: int = 0):
        k = self.key(owner_id, state)
        with self._lock:
            if k in self._data:
                self._data.move_to_end(k)
                return self._data[k]
        model = OpponentModel.from_config(league)
        cands = build_candidates(state, model)
        res = survival(state, model, n_sims=league.simulation.n_sims, seed=seed, candidates=cands)
        with self._lock:
            self._data[k] = (cands, res)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
        return cands, res


def _demand(league: LeagueConfig) -> dict[Position, int]:
    return {p: league.league.num_teams * league.roster.starting_slots_for(p) for p in Position}


def score_candidates(
    state: DraftState,
    league: LeagueConfig,
    cands: Candidates,
    surv: SurvivalResult,
    team_index: int,
    prefs: Preferences,
) -> tuple[pd.DataFrame, dict[Position, float], set[Position]]:
    roster = team_roster(state, team_index)
    open_pos = set(roster.open_positions)
    frame = cands.frame
    scarcity = position_scarcity(list(frame["POSITION_LIST"]), frame["ORIGINAL_VORP"].to_numpy(dtype=float), _demand(league))
    bench_open = roster.open_bench > 0
    legal = pd.Series(
        [bench_open or bool(open_pos & set(ps)) or is_legal_pick(state, team_index, int(pid)) for pid, ps in zip(frame.index, frame["POSITION_LIST"], strict=True)],
        index=frame.index,
    )
    p_return = pd.Series({int(pid): surv.p(int(pid)) for pid in frame.index})
    weights = effective_weights(league.recommendation.weights, prefs)
    scored = opportunity_scores(
        frame[legal], p_return, weights, open_pos, scarcity, current_pick(state), league.league.num_teams, league.projection.gp_cap
    )
    return scored, scarcity, open_pos


def _components(row: pd.Series, card: PlayerCard, open_pos: set[Position]) -> RecommendationComponents:
    filled = sorted(open_pos & set(card.positions), key=lambda p: p.value)
    return RecommendationComponents(
        score=float(row["SCORE"]),
        value=float(row["C_VALUE"]),
        pool_vorp=float(row["VORP"]),
        vorp=card.vorp,
        season_fp=card.season_fp,
        fpg=card.fpg,
        gp=card.gp,
        gp_norm=float(row["C_GP"]),
        fit=float(row["C_FIT"]),
        open_positions_filled=[p.value for p in filled],
        scarcity=float(row["C_SCARCITY"]),
        upside=float(row["C_UPSIDE"]),
        adp=card.adp,
        adp_value=float(row["C_ADP"]),
        injury_status=card.injury_status,
        injury_risk=float(row["C_INJURY"]),
        confidence=float(row["C_CONFIDENCE"]),
        p_return=float(row["P_RETURN"]),
    )


def _reasons(c: RecommendationComponents, card: PlayerCard, open_pos: set[Position]) -> list[str]:
    out = [f"Pool VORP {c.pool_vorp:.0f} ({c.value:.0%} of the best remaining), {c.season_fp:.0f} projected season FP"]
    if c.fit:
        out.append("fills your open " + "/".join(c.open_positions_filled) + " slot")
    elif open_pos:
        out.append("no open starting slot at " + ",".join(p.value for p in card.positions) + ": would sit on the bench")
    if c.p_return <= 0.35:
        out.append(f"only {c.p_return:.0%} chance of surviving to your next pick")
    elif c.p_return >= 0.75:
        out.append(f"likely still there next turn ({c.p_return:.0%}); you could wait")
    if c.scarcity >= 0.5:
        out.append(f"position getting thin ({c.scarcity:.0%} of above-replacement players gone)")
    if card.gp < 60:
        out.append(f"games-played risk: projected {card.gp:.0f} GP")
    if c.injury_risk > 0:
        out.append(f"injury status: {card.injury_status}")
    if c.adp_value >= 0.5:
        out.append(f"value vs ADP {c.adp:.1f}: falling past their draft position")
    elif c.adp_value <= -0.5:
        out.append(f"reach vs ADP {c.adp:.1f}")
    if c.confidence < 0.6:
        out.append(f"low projection confidence ({c.confidence:.0%})")
    return out


def recommend(
    state: DraftState,
    league: LeagueConfig,
    cache: SurvivalCache,
    owner_id: int,
    prefs: Preferences = Preferences(),
    team_index: int | None = None,
    top: int = 3,
) -> RecommendationsOut:
    clock_team = team_on_the_clock(state)
    team = team_index if team_index is not None else (clock_team if clock_team is not None else state.config.user_team_index)
    cands, surv = cache.get_or_compute(owner_id, state, league)
    scored, scarcity, open_pos = score_candidates(state, league, cands, surv, team, prefs)
    recs = []
    for i, (pid, row) in enumerate(scored.head(top).iterrows(), start=1):
        card = state.pool[int(pid)]
        comps = _components(row, card, open_pos)
        recs.append(RecommendationOut(rank=i, player=player_out(card), score=comps.score, components=comps, reasons=_reasons(comps, card, open_pos)))
    return RecommendationsOut(
        for_team=team,
        is_user_turn=clock_team == state.config.user_team_index,
        until_pick=surv.until_pick,
        n_sims=surv.n_sims,
        scarcity={p.value: v for p, v in scarcity.items()},
        recommendations=recs,
    )


def survival_out(state: DraftState, league: LeagueConfig, cache: SurvivalCache, owner_id: int) -> SurvivalOut:
    cands, surv = cache.get_or_compute(owner_id, state, league)
    entries = [
        SurvivalEntryOut(player=player_out(state.pool[int(pid)]), p_return=surv.p(int(pid)), consensus_rank=float(r))
        for pid, r in zip(cands.player_ids, cands.consensus_rank, strict=True)
    ]
    return SurvivalOut(
        from_pick=surv.from_pick,
        until_pick=surv.until_pick,
        n_sims=surv.n_sims,
        picks_between=[{"pick_number": p, "team_index": t, "team_name": state.config.team_names[t]} for p, t in surv.picks_between],
        players=entries,
    )


def opponents_out(state: DraftState, league: LeagueConfig, cache: SurvivalCache, owner_id: int, top: int = 4) -> OpponentsOut:
    _, surv = cache.get_or_compute(owner_id, state, league)
    model = OpponentModel.from_config(league)
    seen: dict[int, OpponentOut] = {}
    for pick_no, team in surv.picks_between:
        if team in seen:
            continue
        roster = team_roster(state, team)
        probs = pick_probabilities(state, team, model, n_draws=1500, seed=pick_no, top=top)
        seen[team] = OpponentOut(
            team_index=team,
            team_name=state.config.team_names[team],
            pick_number=pick_no,
            open_positions=[p.value for p in roster.open_positions],
            open_bench=roster.open_bench,
            roster=[player_out(state.pool[pid]) for pid in roster.player_ids],
            likely_targets=[TargetOut(player=player_out(state.pool[pid]), probability=p) for pid, p in probs],
        )
    return OpponentsOut(until_pick=surv.until_pick, opponents=list(seen.values()))


def compare_out(
    state: DraftState,
    league: LeagueConfig,
    cache: SurvivalCache,
    owner_id: int,
    player_ids: list[int],
    prefs: Preferences = Preferences(),
) -> CompareOut:
    team = state.config.user_team_index
    cands, surv = cache.get_or_compute(owner_id, state, league)
    scored, scarcity, open_pos = score_candidates(state, league, cands, surv, team, prefs)
    drafted = {p.player_id for p in state.picks}
    out = []
    for pid in player_ids:
        card = state.pool.get(pid)
        if card is None:
            continue
        if pid in scored.index:
            comps = _components(scored.loc[pid], card, open_pos)
        else:
            # Outside the candidate window or illegal: report raw figures without a score.
            comps = RecommendationComponents(
                score=None, value=0.0, pool_vorp=card.vorp, vorp=card.vorp, season_fp=card.season_fp, fpg=card.fpg, gp=card.gp,
                gp_norm=min(1.0, card.gp / league.projection.gp_cap), fit=1.0 if open_pos & set(card.positions) else 0.0,
                open_positions_filled=[p.value for p in sorted(open_pos & set(card.positions), key=lambda p: p.value)],
                scarcity=max((scarcity.get(p, 0.0) for p in card.positions), default=0.0), upside=0.0, adp=card.adp,
                adp_value=0.0, injury_status=card.injury_status, injury_risk=0.0, confidence=card.confidence,
                p_return=surv.p(pid),
            )
        out.append(
            ComparePlayerOut(
                player=player_out(card),
                drafted=pid in drafted,
                legal_for_user=pid not in drafted and (pid in scored.index or is_legal_pick(state, team, pid)),
                components=comps,
            )
        )
    return CompareOut(players=out, until_pick=surv.until_pick)
