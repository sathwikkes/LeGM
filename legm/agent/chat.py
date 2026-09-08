"""Claude tool-calling loop for the draft assistant (Phase 7).

The model only calls the deterministic tools in legm.agent.tools. If the API
key is missing or the request fails, the caller gets LLMUnavailable and the
quantitative engine keeps working without it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from legm.agent.tools import TOOL_DEFINITIONS, ToolContext, execute_tool

DEFAULT_MODEL = "claude-opus-5"
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are LeGM, a fantasy basketball draft assistant for a Yahoo head-to-head points league.

You do not compute rankings, projections or probabilities yourself. Every number comes from the deterministic tools: call them, then explain. When the user asks who to draft, why one player beats another, whether a position is scarce, or who will still be there next pick, use the tools first.

Answer in two clearly separated parts when strategy is involved:
1. "Model says": the objective figures from the tools (scores, VORP, P(return), scarcity, GP).
2. "My read": your subjective strategic interpretation, labelled as such.

Be concise and specific. Name players, cite the numbers you used, and say which tool they came from when it matters. If the user asks you to ignore a factor (e.g. injury risk), say you are doing so and reason from the remaining components. Never invent a stat."""


class LLMUnavailable(Exception):
    pass


@dataclass
class ChatResult:
    reply: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = DEFAULT_MODEL
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client():
    """Anthropic client; None when no credentials are configured."""
    if not llm_available():
        return None
    import anthropic

    return anthropic.Anthropic()


def _text_of(response) -> str:
    return "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()


def run_chat(
    ctx: ToolContext,
    messages: list[dict[str, Any]],
    client=None,
    model: str | None = None,
    max_tokens: int = 4000,
) -> ChatResult:
    """messages: prior turns as [{role: user|assistant, content: str}], last one from the user."""
    client = client or make_client()
    if client is None:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set; the assistant is offline")
    model = model or os.environ.get("LEGM_LLM_MODEL", DEFAULT_MODEL)
    convo: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("content")]
    if not convo or convo[-1]["role"] != "user":
        raise ValueError("the last message must be from the user")

    import anthropic

    tool_calls: list[dict[str, Any]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                tools=TOOL_DEFINITIONS,
                messages=convo,
            )
            if getattr(response, "usage", None) is not None:
                usage["input_tokens"] += int(getattr(response.usage, "input_tokens", 0) or 0)
                usage["output_tokens"] += int(getattr(response.usage, "output_tokens", 0) or 0)
            if response.stop_reason == "refusal":
                return ChatResult(reply="I can't help with that request.", tool_calls=tool_calls, model=model, stop_reason="refusal", usage=usage)
            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                return ChatResult(reply=_text_of(response), tool_calls=tool_calls, model=model, stop_reason=response.stop_reason, usage=usage)
            convo.append({"role": "assistant", "content": response.content})
            results = []
            for tu in tool_uses:
                args = dict(tu.input or {})
                out = execute_tool(ctx, tu.name, args)
                tool_calls.append({"name": tu.name, "input": args, "output_chars": len(out)})
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            convo.append({"role": "user", "content": results})
        return ChatResult(reply="I ran out of tool calls before finishing; try a narrower question.", tool_calls=tool_calls, model=model, stop_reason="max_rounds", usage=usage)
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable(f"Anthropic authentication failed: {exc.message}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("Anthropic rate limit hit; try again shortly") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable(f"could not reach the Anthropic API: {exc}") from exc
