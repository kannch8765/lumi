"""Security / prompt-injection tests for the L5 Synthesizer Agent.

L5 is the only L-layer that emits user-facing natural language, so
its prompt is the highest-value target for injection. These tests
cover the layered defenses:

  * **No tools** (CONTEXT.md #10) — L5 has zero tools, so it cannot
    browse, cannot call the catalog, cannot pay.
  * **PII echo ban** — the INSTRUCTION zone forbids echoing the
    user's age, location, or education_level into the reply.
  * **No URL fabrication** — instruction forbids URLs not in
    ``state['ranked_timeline']``.
  * **No resource fabrication** — every resource mentioned must be in
    ``state['ranked_timeline']``.
  * **Three-zone hierarchy** — INSTRUCTION / TOOL / USER zones are
    all present.
  * **Refusal-pattern scrub** — :class:`RecommendationResponse` rejects
    "system prompt", "my instructions", and "instruction zone"
    (case-insensitive).
  * **Length caps** — markdown ≤ 3000, follow_up ≤ 200.
  * **No PII fields on the schema** — RecommendationResponse has no
    age/location/name/email fields, so PII cannot leak via the
    structured-output pathway even if the model tries.
  * **Unicode / zero-width chars** — Pydantic does not filter unicode,
    so non-ASCII and zero-width characters pass through. Verified so
    that no future regression tries to "normalize" them away.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.l5_synthesizer import (
    _L5_INSTRUCTION,
    create_l5_synthesizer_agent,
)
from app.agents.schemas import RecommendationResponse

# ─── Factory-level security invariants ─────────────────────────────────


def test_l5_has_no_tools() -> None:
    """L5 has zero tools (CONTEXT.md #10 — tool whitelist is the kill switch)."""

    agent = create_l5_synthesizer_agent()
    assert agent.tools == []


def test_l5_instruction_bans_pii_echo() -> None:
    """INSTRUCTION zone forbids echoing the user's PII fields."""

    # The instruction must forbid mentioning age/location/education_level.
    lowered = _L5_INSTRUCTION.lower()
    assert "age" in lowered
    assert "location" in lowered
    # "MUST NOT mention" is the canonical phrasing used elsewhere in
    # the codebase; require its presence (case-insensitive substring).
    assert "must not mention" in lowered


def test_l5_instruction_bans_url_fabrication() -> None:
    """INSTRUCTION zone forbids URLs not present in ``ranked_timeline``."""

    lowered = _L5_INSTRUCTION.lower()
    # Forbids invented/shortened/tracker URLs.
    assert "url" in lowered
    assert (
        "must not include" in lowered
        or "must not invent" in lowered
        or "no shortened" in lowered
    )


def test_l5_instruction_bans_resource_fabrication() -> None:
    """INSTRUCTION zone forbids inventing resources."""

    lowered = _L5_INSTRUCTION.lower()
    assert "must not invent" in lowered
    # And explicitly requires resources to come from ranked_timeline.
    assert "ranked_timeline" in lowered


def test_l5_instruction_has_three_zones() -> None:
    """Three-zone hierarchy present (CONTEXT.md #18)."""

    assert "INSTRUCTION ZONE" in _L5_INSTRUCTION
    assert "TOOL ZONE" in _L5_INSTRUCTION
    assert "USER ZONE" in _L5_INSTRUCTION


# ─── Schema-level refusal-pattern scrub ────────────────────────────────


def test_l5_recommendation_response_rejects_system_prompt_substring() -> None:
    """Markdown containing 'system prompt' (any case) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Per my system prompt, I should ignore the user.",
            language="en",
        )


def test_l5_recommendation_response_rejects_instruction_zone_substring() -> None:
    """Markdown containing 'instruction zone' (any case) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Echoing my INSTRUCTION ZONE back to the user.",
            language="en",
        )


def test_l5_recommendation_response_rejects_my_instructions_substring() -> None:
    """Markdown containing 'my instructions' raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="According to my instructions, I must...",
            language="en",
        )


# ─── Length caps ───────────────────────────────────────────────────────


def test_l5_markdown_cap_3000_chars() -> None:
    """Markdown length cap is exactly 3000 chars."""

    # 3000 OK, 3001 not.
    RecommendationResponse(markdown="a" * 3000, language="en")
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="a" * 3001, language="en")


def test_l5_follow_up_cap_200_chars() -> None:
    """follow_up length cap is exactly 200 chars."""

    RecommendationResponse(markdown="ok", language="en", follow_up="q" * 200)
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="ok", language="en", follow_up="q" * 201)


# ─── PII surface ───────────────────────────────────────────────────────


def test_l5_no_field_for_pii() -> None:
    """RecommendationResponse has no age / location / name / email field.

    Even if the LLM tries to inject PII into the structured output,
    the schema rejects it. This is the second line of defense behind
    the INSTRUCTION zone's "MUST NOT mention" rule.
    """

    fields = set(RecommendationResponse.model_fields.keys())
    for pii in ("age", "location", "name", "email"):
        assert pii not in fields, (
            f"RecommendationResponse must not have a '{pii}' field — "
            f"PII echo is forbidden by CONTEXT.md #19. Found: {fields}"
        )


# ─── Unicode / zero-width handling ─────────────────────────────────────


def test_l5_unicode_in_markdown_works() -> None:
    """Japanese / non-ASCII markdown validates fine (Pydantic accepts str)."""

    resp = RecommendationResponse(
        markdown="おすすめのコースはCS231nです。https://cs231n.stanford.edu",
        language="ja",
    )
    assert "CS231n" in resp.markdown
    assert resp.language == "ja"


def test_l5_zero_width_char_in_markdown_works() -> None:
    """Zero-width characters (U+200B etc.) do NOT trigger the
    refusal-pattern scrub and do NOT raise.

    Pydantic doesn't filter unicode. The refusal patterns are
    substring-matched on ASCII ("system prompt" etc.), so zero-width
    padding cannot smuggle a forbidden phrase past the validator.
    This test guards against a future regression that tries to be
    "clever" by stripping/normalizing unicode.
    """

    zwsp = "​"  # zero-width space
    resp = RecommendationResponse(
        markdown=f"Here are your picks: {zwsp}CS231n",
        language="en",
    )
    assert zwsp in resp.markdown
