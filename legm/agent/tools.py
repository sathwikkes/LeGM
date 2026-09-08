"""Deterministic tools exposed to the LLM (Phase 7).

Every tool is a thin, read-only view over the engine and the API's own
recommendation code. Nothing here computes a ranking or a projection: the LLM
explains and interrogates numbers the deterministic layer already produced.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from legm.api.recommend import SurvivalCache, compare_out, opponents_out, recommend, survival_out
from legm.api.views import available_out, draft_out
from legm.config.models import LeagueConfig, Position
from legm.data.names import normalize_name
from legm.draft.models import DraftState
from legm.draft.simulate import simulate_until_user
from legm.draft.state import team_roster
from legm.draft.strategies import NeedsAware
from legm.engine.opportunity import Preferences, position_scarcity


@dataclass
class ToolContext:
    state: DraftState
    league: LeagueConfig
    cache: SurvivalCache
    owner_id: int
    prefs: Preferences = Preferences()


def _card(ctx: ToolContext, query: str | int):
    """Resolve a player by id or name (drafted or not)."""
    pool = ctx.state.pool
    if isinstance(query, int) or str(query).isdigit():
        return pool.get(int(query))
    q = normalize_name(str(query))
    exact = [c for c in pool.values() if normalize_name(c.name) == q]
    if exact:
        return exact[0]
    partial = [c for c in pool.values() if q in normalize_name(c.name)]
    return partial[0] if len(partial) == 1 else None


def _player_dict(c) -> dict[str, Any]:
    return {
        "player_id": c.player_id, "name": c.name, "positions": [p.value for p in c.positions], "team": c.team,
        "gp": round(c.gp, 1), "fpg": round(c.fpg, 2), "season_fp": round(c.season_fp, 1), "vorp": round(c.vorp, 1),
        "adp": c.adp, "age": c.age, "injury_status": c.injury_status, "confidence": c.confidence,
    }


def get_draft_state(ctx: ToolContext) -> dict:
    d = draft_out(ctx.state)
    return {
        "draft_id": d.draft_id, "clock": d.clock.model_dump(), "config": d.config.model_dump(),
        "recent_picks": [{"pick": p.pick_number, "team": p.team_name, "player": p.player.name} for p in d.picks[-12:]],
        "picks_made": len(d.picks),
    }


def get_my_roster(ctx: ToolContext) -> dict:
    r = team_roster(ctx.state, ctx.state.config.user_team_index)
    return {
        "team": r.name,
        "slots": {slot: (ctx.state.pool[pid].name if pid else None) for slot, pid in r.slots.items()},
        "open_positions": [p.value for p in r.open_positions], "open_bench": r.open_bench,
        "players": [_player_dict(ctx.state.pool[pid]) for pid in r.player_ids],
    }


def get_available_players(ctx: ToolContext, position: str | None = None, query: str | None = None, limit: int = 15) -> dict:
    out = available_out(ctx.state, query=query, position=position, limit=min(int(limit), 50))
    _, surv = ctx.cache.get_or_compute(ctx.owner_id, ctx.state, ctx.league)
    return {
        "total_available": out.total,
        "players": [
            {**p.model_dump(exclude={"p_return"}), "p_return": surv.p(p.player_id)} for p in out.players
        ],
    }


def get_player_projection(ctx: ToolContext, player: str) -> dict:
    c = _card(ctx, player)
    if c is None:
        return {"error": f"no player matching {player!r} in this draft's pool"}
    drafted = next((p for p in ctx.state.picks if p.player_id == c.player_id), None)
    return {**_player_dict(c), "projection_source": c.projection_source,
            "drafted_by": None if drafted is None else ctx.state.config.team_names[drafted.team_index],
            "drafted_at_pick": None if drafted is None else drafted.pick_number}


def get_player_value(ctx: ToolContext, player: str) -> dict:
    c = _card(ctx, player)
    if c is None:
        return {"error": f"no player matching {player!r}"}
    cmp_ = compare_out(ctx.state, ctx.league, ctx.cache, ctx.owner_id, [c.player_id, c.player_id], ctx.prefs)
    return {"player": c.name, **cmp_.players[0].model_dump(exclude={"player"})}


def compare_players(ctx: ToolContext, players: list[str]) -> dict:
    ids = []
    missing = []
    for q in players[:5]:
        c = _card(ctx, q)
        (ids.append(c.player_id) if c else missing.append(q))
    if len(ids) < 2:
        return {"error": "need at least two resolvable players", "unresolved": missing}
    cmp_ = compare_out(ctx.state, ctx.league, ctx.cache, ctx.owner_id, ids, ctx.prefs)
    return {"until_pick": cmp_.until_pick, "unresolved": missing, "players": [p.model_dump() for p in cmp_.players]}


def get_roster_needs(ctx: ToolContext, team: int | None = None) -> dict:
    idx = ctx.state.config.user_team_index if team is None else int(team)
    r = team_roster(ctx.state, idx)
    return {"team": r.name, "open_positions": [p.value for p in r.open_positions], "open_bench": r.open_bench,
            "filled": {s: (ctx.state.pool[pid].name if pid else None) for s, pid in r.slots.items()}}


def get_position_scarcity(ctx: ToolContext) -> dict:
    from legm.draft.state import available_frame

    frame = available_frame(ctx.state, recompute_vorp=True)
    demand = {p: ctx.league.league.num_teams * ctx.league.roster.starting_slots_for(p) for p in Position}
    scar = position_scarcity(list(frame["POSITION_LIST"]), frame["ORIGINAL_VORP"].to_numpy(dtype=float), demand)
    levels = frame.attrs.get("replacement_levels", {})
    return {
        "scarcity": {p.value: round(v, 3) for p, v in scar.items()},
        "replacement_level_season_fp": {k: round(float(v), 1) for k, v in levels.items()},
        "above_replacement_remaining": {
            p.value: int(sum(1 for ps, v in zip(frame["POSITION_LIST"], frame["ORIGINAL_VORP"], strict=True) if p in ps and v > 0))
            for p in Position
        },
        "explanation": "scarcity = 1 - remaining above-original-replacement players / (teams x eligible starting slots)",
    }


def simulate_until_next_pick(ctx: ToolContext, seed: int = 0) -> dict:
    """One deterministic mock of opponents' picks until the user's next turn (needs-aware, jitter 3)."""
    s = simulate_until_user(ctx.state, seed=int(seed), default=NeedsAware(jitter=3))
    new = s.picks[len(ctx.state.picks):]
    return {"seed": seed, "picks": [{"pick": p.pick_number, "team": ctx.state.config.team_names[p.team_index],
                                     "player": ctx.state.pool[p.player_id].name} for p in new],
            "note": "one sample path; use get_probability_of_return for probabilities"}


def get_probability_of_return(ctx: ToolContext, players: list[str] | None = None, limit: int = 15) -> dict:
    surv = survival_out(ctx.state, ctx.league, ctx.cache, ctx.owner_id)
    entries = surv.players
    if players:
        wanted = {c.player_id for q in players if (c := _card(ctx, q))}
        entries = [e for e in entries if e.player.player_id in wanted]
    return {"from_pick": surv.from_pick, "until_pick": surv.until_pick, "n_sims": surv.n_sims,
            "players": [{"name": e.player.name, "p_return": round(e.p_return, 3), "consensus_rank": e.consensus_rank}
                        for e in entries[: int(limit)]]}


def get_opponent_rosters(ctx: ToolContext) -> dict:
    opp = opponents_out(ctx.state, ctx.league, ctx.cache, ctx.owner_id)
    return {"until_pick": opp.until_pick, "opponents": [
        {"team": o.team_name, "pick": o.pick_number, "open_positions": o.open_positions,
         "roster": [p.name for p in o.roster],
         "likely_targets": [{"player": t.player.name, "probability": round(t.probability, 3)} for t in o.likely_targets]}
        for o in opp.opponents]}


def get_injury_context(ctx: ToolContext, player: str | None = None) -> dict:
    cards = [c for c in ctx.state.pool.values() if c.injury_status]
    if player:
        c = _card(ctx, player)
        if c is None:
            return {"error": f"no player matching {player!r}"}
        return {"player": c.name, "injury_status": c.injury_status, "projected_gp": c.gp, "confidence": c.confidence}
    return {"flagged": [{"player": c.name, "injury_status": c.injury_status, "projected_gp": c.gp} for c in cards[:30]],
            "note": "injury data comes from `legm load-injuries`; empty means no report loaded or nobody flagged"}


def generate_ranked_recommendations(ctx: ToolContext, top: int = 5) -> dict:
    recs = recommend(ctx.state, ctx.league, ctx.cache, ctx.owner_id, ctx.prefs, None, min(int(top), 10))
    return recs.model_dump()


TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_draft_state": get_draft_state,
    "get_my_roster": get_my_roster,
    "get_available_players": get_available_players,
    "get_player_projection": get_player_projection,
    "get_player_value": get_player_value,
    "compare_players": compare_players,
    "get_roster_needs": get_roster_needs,
    "get_position_scarcity": get_position_scarcity,
    "simulate_until_next_pick": simulate_until_next_pick,
    "get_probability_of_return": get_probability_of_return,
    "get_opponent_rosters": get_opponent_rosters,
    "get_injury_context": get_injury_context,
    "generate_ranked_recommendations": generate_ranked_recommendations,
}

_PLAYER = {"type": "string", "description": "Player name (fuzzy) or numeric player id"}
_NOARGS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOL_DEFINITIONS: list[dict] = [
    {"name": "get_draft_state", "description": "Current pick, round, team on the clock, the user's next pick and recent picks.", "input_schema": _NOARGS},
    {"name": "get_my_roster", "description": "The user's roster by slot, open starting positions and bench space.", "input_schema": _NOARGS},
    {"name": "get_available_players", "description": "Best available players by VORP on the remaining pool, with P(return) and roster-fit flags. Optional position filter (PG/SG/SF/PF/C) and name query.",
     "input_schema": {"type": "object", "properties": {"position": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "additionalProperties": False}},
    {"name": "get_player_projection", "description": "Projected per-game stats, games played, fantasy points and draft status for one player.",
     "input_schema": {"type": "object", "properties": {"player": _PLAYER}, "required": ["player"], "additionalProperties": False}},
    {"name": "get_player_value", "description": "Full Draft Opportunity Score breakdown for one player relative to the user's roster: value, fit, scarcity, GP, injury, confidence, P(return).",
     "input_schema": {"type": "object", "properties": {"player": _PLAYER}, "required": ["player"], "additionalProperties": False}},
    {"name": "compare_players", "description": "Side-by-side quantitative comparison of 2-5 players (projection, VORP, GP, fit, scarcity, injury, ADP, P(return), score).",
     "input_schema": {"type": "object", "properties": {"players": {"type": "array", "items": _PLAYER, "minItems": 2, "maxItems": 5}}, "required": ["players"], "additionalProperties": False}},
    {"name": "get_roster_needs", "description": "Open starting positions and filled slots for a team (default: the user).",
     "input_schema": {"type": "object", "properties": {"team": {"type": "integer", "description": "0-based team index"}}, "additionalProperties": False}},
    {"name": "get_position_scarcity", "description": "Positional scarcity on the remaining pool, replacement levels and above-replacement counts.", "input_schema": _NOARGS},
    {"name": "simulate_until_next_pick", "description": "One sample mock of opponents' picks until the user's next turn.",
     "input_schema": {"type": "object", "properties": {"seed": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "get_probability_of_return", "description": "Monte Carlo P(player is still available at the user's next pick). Optionally restrict to named players.",
     "input_schema": {"type": "object", "properties": {"players": {"type": "array", "items": _PLAYER}, "limit": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "get_opponent_rosters", "description": "Rosters, open positions and likely targets for every opponent picking before the user's next turn.", "input_schema": _NOARGS},
    {"name": "get_injury_context", "description": "Injury status for one player or every flagged player.",
     "input_schema": {"type": "object", "properties": {"player": _PLAYER}, "additionalProperties": False}},
    {"name": "generate_ranked_recommendations", "description": "The engine's ranked recommendations for the team on the clock, with component scores and reasons.",
     "input_schema": {"type": "object", "properties": {"top": {"type": "integer", "minimum": 1, "maximum": 10}}, "additionalProperties": False}},
]


def execute_tool(ctx: ToolContext, name: str, args: dict) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(fn(ctx, **(args or {})), default=str)
    except TypeError as exc:
        return json.dumps({"error": f"bad arguments for {name}: {exc}"})
    except Exception as exc:  # tool errors go back to the model, never crash the request
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
