from types import SimpleNamespace

import pytest

from legm.agent.chat import LLMUnavailable, run_chat
from legm.agent.tools import ToolContext
from legm.api.recommend import SurvivalCache


class StubClient:
    """Scripted Anthropic-like client: first turn calls a tool, second turn answers."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


def block(**kw):
    return SimpleNamespace(**kw)


def resp(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def ctx(draft, default_config):
    return ToolContext(state=draft, league=default_config, cache=SurvivalCache(), owner_id=1)


def test_tool_loop(ctx):
    client = StubClient([
        resp([block(type="tool_use", id="t1", name="get_my_roster", input={}), block(type="tool_use", id="t2", name="get_draft_state", input={})], "tool_use"),
        resp([block(type="text", text="Model says: ... My read: ...")], "end_turn"),
    ])
    out = run_chat(ctx, [{"role": "user", "content": "who should I take?"}], client=client)
    assert out.reply.startswith("Model says")
    assert [c["name"] for c in out.tool_calls] == ["get_my_roster", "get_draft_state"]
    assert out.usage == {"input_tokens": 20, "output_tokens": 10}
    # second request carried the assistant tool_use turn and both tool results in ONE user message
    second = client.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[2]["role"] == "user"
    assert [r["tool_use_id"] for r in second[2]["content"]] == ["t1", "t2"]
    assert client.calls[0]["tools"] and client.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_refusal_and_validation(ctx):
    client = StubClient([resp([], "refusal")])
    out = run_chat(ctx, [{"role": "user", "content": "x"}], client=client)
    assert out.stop_reason == "refusal"
    with pytest.raises(ValueError):
        run_chat(ctx, [{"role": "assistant", "content": "hi"}], client=StubClient([]))


def test_unavailable_without_key(ctx, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(LLMUnavailable):
        run_chat(ctx, [{"role": "user", "content": "x"}])
