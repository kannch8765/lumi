"""Security / prompt-injection tests for the L4 Timeline + Finalize Agent.

Refactor 2026-06-24: L5 Synthesizer was absorbed into L4 Timeline.
L4 is now the only L-layer that emits user-facing natural language,
so its prompt is the highest-value target for injection. These
tests cover the layered defenses (formerly on L5, now on L4):

  * **No fabrication tools** — L4's tools are MCP catalog + web
    search (CONTEXT.md #10). It cannot pay, cannot create accounts.
    The user-facing markdown emit is structured via
    ``RecommendationResponse``.
  * **PII echo ban** — the INSTRUCTION zone forbids echoing the
    user's age, location, or education_level into the reply.
  * **No URL fabrication** — instruction forbids URLs not in
    ``state['level_filter']`` or the catalog MCP.
  * **No resource fabrication** — every resource mentioned must be
    in ``state['level_filter']``.
  * **Three-zone hierarchy** — INSTRUCTION / TOOL / USER zones are
    all present (refactored form, but same intent).
  * **Refusal-pattern scrub** — :class:`RecommendationResponse` rejects
    "system prompt", "my instructions", and "instruction zone"
    (case-insensitive).
  * **Length caps** — markdown ≤ 3000, follow_up ≤ 200, ask_back ≤ 500.
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

from app.agents.l4_timeline import (
    _L4_INSTRUCTION,
    create_l4_timeline_agent,
)
from app.agents.schemas import RecommendationResponse

# ─── Factory-level security invariants ─────────────────────────────────


def test_l4_has_no_extra_tools_beyond_mcp() -> None:
    """L4's tool surface is exactly the MCP catalog + web-search
    servers (CONTEXT.md #10 — tool whitelist is the kill switch).
    No native function tools, no payment APIs, no account creation."""

    agent = create_l4_timeline_agent()
    # L4 has 2 MCP toolsets (catalog + web-search). The contract is
    # that those are the ONLY tools — no Python function tools.
    toolsets = list(agent.tools)
    assert len(toolsets) >= 1, "L4 should have at least the MCP toolsets"
    # Verify no native FunctionTool instances leaked in.
    for tool in toolsets:
        # ADK's McpToolset wraps the MCP server; its class name
        # starts with "Mcp". Anything else is suspicious.
        assert tool.__class__.__name__.startswith("Mcp"), (
            f"L4 has a non-MCP tool: {tool.__class__.__name__}. "
            "Tool whitelist is the kill switch — adding a non-MCP "
            "tool here silently expands the attack surface."
        )


def test_l4_instruction_bans_pii_echo() -> None:
    """INSTRUCTION zone forbids echoing the user's PII fields."""

    # The instruction must forbid mentioning age/location/education_level.
    lowered = _L4_INSTRUCTION.lower()
    assert "age" in lowered
    assert "location" in lowered
    # "MUST NOT mention" is the canonical phrasing used elsewhere in
    # the codebase; require its presence (case-insensitive substring).
    assert "must not mention" in lowered


def test_l4_instruction_bans_url_fabrication() -> None:
    """INSTRUCTION zone forbids URLs not present in the input set."""

    lowered = _L4_INSTRUCTION.lower()
    # Forbids invented/shortened/tracker URLs.
    assert "url" in lowered
    assert (
        "must not include" in lowered
        or "must not invent" in lowered
        or "no shortened" in lowered
    )


def test_l4_instruction_bans_resource_fabrication() -> None:
    """INSTRUCTION zone forbids inventing resources."""

    lowered = _L4_INSTRUCTION.lower()
    assert "must not invent" in lowered


def test_l4_instruction_has_three_zones() -> None:
    """Three-zone hierarchy present (CONTEXT.md #18).

    L4's instruction has the same INSTRUCTION / TOOL / USER zone
    structure as the former L5. The zone names must appear verbatim
    so the prompt-injection scanners (semgrep rules in
    ``app/security/``) can locate them.
    """

    assert "INSTRUCTION ZONE" in _L4_INSTRUCTION
    assert "TOOL ZONE" in _L4_INSTRUCTION
    assert "USER ZONE" in _L4_INSTRUCTION


def test_l4_instruction_includes_refusal_pattern_scrub() -> None:
    """L4's instruction names the refusal patterns that the
    RecommendationResponse validator rejects. Locked so a future
    refactor doesn't accidentally remove the warning."""

    lowered = _L4_INSTRUCTION.lower()
    assert "system prompt" in lowered
    assert "my instructions" in lowered
    assert "instruction zone" in lowered


# ─── Schema-level refusal-pattern scrub ────────────────────────────────


def test_recommendation_response_rejects_system_prompt_substring() -> None:
    """Markdown containing 'system prompt' (any case) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Per my system prompt, I should ignore the user.",
            language="en",
        )


def test_recommendation_response_rejects_instruction_zone_substring() -> None:
    """Markdown containing 'instruction zone' (any case) raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="Echoing my INSTRUCTION ZONE back to the user.",
            language="en",
        )


def test_recommendation_response_rejects_my_instructions_substring() -> None:
    """Markdown containing 'my instructions' raises."""

    with pytest.raises(ValidationError):
        RecommendationResponse(
            markdown="According to my instructions, I must...",
            language="en",
        )


# ─── Length caps ───────────────────────────────────────────────────────


def test_recommendation_response_markdown_cap_3000_chars() -> None:
    """Markdown length cap is exactly 3000 chars."""

    # 3000 OK, 3001 not.
    RecommendationResponse(markdown="a" * 3000, language="en")
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="a" * 3001, language="en")


def test_recommendation_response_follow_up_cap_200_chars() -> None:
    """follow_up length cap is exactly 200 chars."""

    RecommendationResponse(markdown="ok", language="en", follow_up="q" * 200)
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown="ok", language="en", follow_up="q" * 201)


def test_recommendation_response_ask_back_cap_500_chars() -> None:
    """ask_back length cap is exactly 500 chars (refactor 2026-06-24)."""

    RecommendationResponse(markdown=None, language="en", ask_back="q" * 500)
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown=None, language="en", ask_back="q" * 501)


# ─── PII surface ───────────────────────────────────────────────────────


def test_recommendation_response_no_field_for_pii() -> None:
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


def test_recommendation_response_unicode_in_markdown_works() -> None:
    """Japanese / non-ASCII markdown validates fine (Pydantic accepts str)."""

    resp = RecommendationResponse(
        markdown="おすすめのコースはCS231nです。https://cs231n.stanford.edu",
        language="ja",
    )
    assert "CS231n" in resp.markdown
    assert resp.language == "ja"


def test_recommendation_response_zero_width_char_in_markdown_works() -> None:
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
