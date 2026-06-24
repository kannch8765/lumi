"""Outcome-based unit tests for the L5 Synthesizer Agent.

Tests cover three concerns (per CONTEXT.md #18-22):

  1. Schema validation — :class:`RecommendationResponse` accepts the
     shapes L5 emits and rejects forbidden phrases / oversized strings.
  2. Factory construction — ``create_l5_synthesizer_agent()`` returns
     a valid ``LlmAgent`` with the right name, zero tools, output
     schema, and output key.
  3. Fallback renderer — ``_render_fallback_markdown`` builds a
     deterministic markdown summary grouped by urgency.

Lumi test policy (CONTEXT.md #7): no mocks, observe return value
and observable state mutation.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from google.adk.agents import LlmAgent
from google.genai import types as genai_types
from pydantic import ValidationError

from app.agents.l5_synthesizer import (
    _DEFAULT_L5_MODEL,
    _L5_INSTRUCTION,
    STATE_KEY_FINAL_RECOMMENDATION,
    _render_fallback_markdown,
    create_l5_synthesizer_agent,
)
from app.agents.schemas import RecommendationResponse

# ─── Schema validation: RecommendationResponse ──────────────────────────


def test_recommendation_response_minimal_valid() -> None:
    """``RecommendationResponse(markdown="x", language="en")`` validates."""

    resp = RecommendationResponse(markdown="x", language="en")
    assert resp.markdown == "x"
    assert resp.language == "en"
    assert resp.follow_up is None


def test_recommendation_response_markdown_min_length() -> None:
    """Empty markdown raises ``ValidationError`` (min_length=1)."""

    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="", language="en")


def test_recommendation_response_markdown_max_length_3000() -> None:
    """A 3001-char markdown raises ``ValidationError`` (max_length=3000)."""

    long = "a" * 3001
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown=long, language="en")


def test_recommendation_response_markdown_max_length_3000_boundary() -> None:
    """Exactly 3000 chars is OK (boundary test for max_length)."""

    at_limit = "a" * 3000
    resp = RecommendationResponse(markdown=at_limit, language="en")
    assert len(resp.markdown) == 3000


def test_recommendation_response_language_min_length_2() -> None:
    """A 1-char language raises ``ValidationError`` (min_length=2)."""

    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="ok", language="a")


def test_recommendation_response_language_max_length_10() -> None:
    """An 11-char language raises ``ValidationError`` (max_length=10)."""

    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="ok", language="abcdefghijk")


def test_recommendation_response_follow_up_default_none() -> None:
    """``follow_up`` defaults to ``None`` when not supplied."""

    resp = RecommendationResponse(markdown="ok", language="en")
    assert resp.follow_up is None


def test_recommendation_response_follow_up_max_length_200() -> None:
    """A 201-char follow_up raises ``ValidationError`` (max_length=200)."""

    too_long = "q" * 201
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="ok", language="en", follow_up=too_long)


def test_recommendation_response_rejects_system_prompt_phrase() -> None:
    """Markdown containing ``system prompt`` (any case) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Per my System Prompt, you should...", language="en"
        )


def test_recommendation_response_rejects_my_instructions_phrase() -> None:
    """Markdown containing ``my instructions`` raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Following my instructions, I will...", language="en"
        )


def test_recommendation_response_rejects_instruction_zone_phrase() -> None:
    """Markdown containing ``INSTRUCTION ZONE`` (case-insensitive) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="See the INSTRUCTION ZONE for details.", language="en"
        )


def test_recommendation_response_markdown_with_url_works() -> None:
    """A markdown with a URL but no forbidden phrases validates fine.

    URLs are explicitly OK — only refusal-pattern phrases are scrubbed.
    """

    resp = RecommendationResponse(
        markdown="Check out https://cs231n.stanford.edu for a great course.",
        language="en",
    )
    assert "cs231n.stanford.edu" in resp.markdown


# ─── Factory tests ──────────────────────────────────────────────────────


def test_factory_returns_llm_agent() -> None:
    """``create_l5_synthesizer_agent()`` returns an ``LlmAgent``."""

    agent = create_l5_synthesizer_agent()
    assert isinstance(agent, LlmAgent)


def test_agent_name() -> None:
    """Agent name is the canonical ``l5_synthesizer``."""

    agent = create_l5_synthesizer_agent()
    assert agent.name == "l5_synthesizer"


def test_agent_has_no_tools() -> None:
    """L5 has zero tools (CONTEXT.md #10 — tool whitelist is the kill switch)."""

    agent = create_l5_synthesizer_agent()
    assert agent.tools == []


def test_agent_output_schema_is_recommendation_response() -> None:
    """L5's ``output_schema`` is :class:`RecommendationResponse`."""

    agent = create_l5_synthesizer_agent()
    assert agent.output_schema is RecommendationResponse


def test_agent_output_key_is_final_recommendation() -> None:
    """L5's ``output_key`` is the documented state key constant."""

    agent = create_l5_synthesizer_agent()
    assert agent.output_key == STATE_KEY_FINAL_RECOMMENDATION
    assert agent.output_key == "final_recommendation"


def test_agent_default_model_is_flash() -> None:
    """Default model is ``gemini-3.1-flash-lite`` (low-latency synthesis)."""

    assert _DEFAULT_L5_MODEL == "gemini-3.1-flash-lite"
    agent = create_l5_synthesizer_agent()
    # ``model`` on LlmAgent is a ``BaseLlm`` wrapper; check class name.
    assert type(agent.model).__name__ == "Gemini"


def test_agent_instruction_has_three_zones() -> None:
    """Instruction defines INSTRUCTION / TOOL / USER zones (CONTEXT.md #18)."""

    assert "INSTRUCTION ZONE" in _L5_INSTRUCTION
    assert "TOOL ZONE" in _L5_INSTRUCTION
    assert "USER ZONE" in _L5_INSTRUCTION


# ─── Fallback renderer tests ────────────────────────────────────────────


def test_fallback_renders_empty_timeline() -> None:
    """Empty ranked list produces the "couldn't find time-sensitive" message."""

    out = _render_fallback_markdown({"ranked_timeline": {"ranked": []}})
    assert (
        "couldn't find time-sensitive" in out.lower() or "couldn't find" in out.lower()
    )


def test_fallback_renders_empty_timeline_no_state_key() -> None:
    """No ``ranked_timeline`` key at all also yields the empty message."""

    out = _render_fallback_markdown({})
    assert "couldn't find" in out.lower()


def test_fallback_groups_by_urgency() -> None:
    """Sample timeline is grouped with CRITICAL first in the rendered markdown."""

    sample = {
        "ranked": [
            {
                "urgency": "low",
                "resource": {
                    "name": "Free Course A",
                    "url": "https://example.com/a",
                },
                "recommended_action": "Bookmark for later",
            },
            {
                "urgency": "critical",
                "resource": {
                    "name": "Critical Course B",
                    "url": "https://example.com/b",
                },
                "recommended_action": "Register today",
            },
            {
                "urgency": "high",
                "resource": {
                    "name": "High Course C",
                    "url": "https://example.com/c",
                },
                "recommended_action": "Register this week",
            },
        ]
    }
    out = _render_fallback_markdown({"ranked_timeline": sample})
    # CRITICAL must appear before HIGH, and HIGH before LOW.
    crit_idx = out.find("CRITICAL")
    high_idx = out.find("HIGH")
    low_idx = out.find("LOW")
    assert 0 <= crit_idx < high_idx < low_idx, (
        f"Fallback out of order: CRITICAL@{crit_idx}, HIGH@{high_idx}, LOW@{low_idx}\n"
        f"--- output ---\n{out}"
    )
    # Resource names appear verbatim.
    assert "Critical Course B" in out
    assert "High Course C" in out
    assert "Free Course A" in out


# ─── Smoke: l5_after_agent Content shape ────────────────────────────────


def test_l5_after_agent_returns_content_on_valid_output() -> None:
    """When ``state['final_recommendation']`` is a valid model, the
    callback returns a ``Content`` whose text is the markdown."""

    from app.agents.l5_synthesizer import _l5_after_agent

    class _Ctx:
        state: ClassVar[dict] = {
            STATE_KEY_FINAL_RECOMMENDATION: RecommendationResponse(
                markdown="Here are your picks.", language="en"
            )
        }

    out = _l5_after_agent(_Ctx())
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    assert out.parts[0].text == "Here are your picks."


def test_l5_after_agent_falls_back_on_invalid_output() -> None:
    """When ``state['final_recommendation']`` fails validation, the
    callback falls back to a code-rendered summary (defense-in-depth)."""

    from app.agents.l5_synthesizer import _l5_after_agent

    class _Ctx:
        state: ClassVar[dict] = {
            STATE_KEY_FINAL_RECOMMENDATION: {"markdown": "x" * 5000, "language": "en"},
            "ranked_timeline": {"ranked": []},
        }

    out = _l5_after_agent(_Ctx())
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    # Empty ranked list → the "couldn't find" message.
    assert "couldn't find" in out.parts[0].text.lower()
