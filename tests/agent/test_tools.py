import json

import pytest

from legm.agent.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS, ToolContext, execute_tool
from legm.api.recommend import SurvivalCache
from legm.draft.simulate import simulate


@pytest.fixture
def ctx(draft, default_config):
    state = simulate(draft, stop_before_user=True)
    return ToolContext(state=state, league=default_config, cache=SurvivalCache(), owner_id=1)


def test_definitions_match_functions():
    assert {t["name"] for t in TOOL_DEFINITIONS} == set(TOOL_FUNCTIONS)
    for t in TOOL_DEFINITIONS:
        assert t["input_schema"]["type"] == "object" and t["description"]


def test_every_tool_runs_and_is_json(ctx):
    samples = {
        "get_available_players": {"position": "C", "limit": 5},
        "get_player_projection": {"player": "Player 003"},
        "get_player_value": {"player": "Player 003"},
        "compare_players": {"players": ["Player 003", "Player 004", "Player 005"]},
        "get_roster_needs": {"team": 0},
        "simulate_until_next_pick": {"seed": 2},
        "get_probability_of_return": {"players": ["Player 003"]},
        "get_injury_context": {"player": "Player 003"},
        "generate_ranked_recommendations": {"top": 3},
    }
    for name in TOOL_FUNCTIONS:
        out = json.loads(execute_tool(ctx, name, samples.get(name, {})))
        assert "error" not in out, (name, out)
    recs = json.loads(execute_tool(ctx, "generate_ranked_recommendations", {"top": 3}))
    assert len(recs["recommendations"]) == 3 and recs["is_user_turn"]
    pr = json.loads(execute_tool(ctx, "get_probability_of_return", {"players": ["Player 003"]}))
    assert pr["players"][0]["name"] == "Player 003" and 0 <= pr["players"][0]["p_return"] <= 1
    state = json.loads(execute_tool(ctx, "get_draft_state", {}))
    assert state["clock"]["is_user_turn"] and state["picks_made"] == 2


def test_tool_errors_are_returned_not_raised(ctx):
    assert "unknown tool" in json.loads(execute_tool(ctx, "nope", {}))["error"]
    assert "bad arguments" in json.loads(execute_tool(ctx, "get_my_roster", {"x": 1}))["error"]
    assert "no player" in json.loads(execute_tool(ctx, "get_player_projection", {"player": "Nobody"}))["error"]
    assert "unresolved" in json.loads(execute_tool(ctx, "compare_players", {"players": ["Nobody", "Player 003"]}))
