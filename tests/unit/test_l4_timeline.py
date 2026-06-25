"""Outcome-based unit tests for the L4 Timeline + Finalize Agent.

These tests assert on the factory output (LlmAgent attributes) and
on the ``RecommendationResponse`` / ``TimelineResult`` schemas. No
mocks, no monkey-patching of the production code per CONTEXT.md
rule #7 — a test that passes with the factory replaced by
``return None`` would not be a real test.

The McpToolset attribute is asserted to be a non-empty list (both
the resource-catalog and the web-search MCP servers are exposed).
We do not invoke the tool subprocesses — that requires a live ADK
runtime and is covered by the integration tests in
``tests/integration/test_pipeline_e2e.py`` (Task 26).

Refactor 2026-06-24: L4 now emits ``RecommendationResponse``
(markdown + language + follow_up + ask_back) instead of
``TimelineResult`` — L5 Synthesizer was absorbed into L4. The
``TimelineResult`` schema is still tested because the fallback
renderer reads ``state['level_filter']`` and we want to verify
the data contract is intact.
"""

from __future__ import annotations

from datetime import date

import pytest
from google.genai import types as genai_types
from pydantic import ValidationError

from app.agents.l4_timeline import (
    _L4_INSTRUCTION,
    STATE_KEY_FINAL_RECOMMENDATION,
    _coerce_recommendation,
    _l4_finalize_after_agent,
    _render_fallback_markdown,
    create_l4_timeline_agent,
)
from app.agents.schemas import (
    LevelFilterResult,
    LevelMatch,
    RecommendationResponse,
    SkillLevel,
    TimelineEntry,
    TimelineResult,
    Urgency,
    classify_days_until_deadline,
)
from app.mcp_servers.resource_catalog.schemas import ResourceOutput

# ─── Helper ────────────────────────────────────────────────────────────


def _sample_resource(
    resource_id: str = "cs231n-stanford",
    name: str = "CS231n",
    type: str = "course",
) -> ResourceOutput:
    """A minimal ResourceOutput for TimelineEntry construction."""

    return ResourceOutput(
        id=resource_id,
        name=name,
        type=type,
        url="https://example.com/" + resource_id,
        description="sample",
    )


# ─── Agent factory ─────────────────────────────────────────────────────


def test_factory_returns_agent() -> None:
    agent = create_l4_timeline_agent()
    assert agent is not None
    assert agent.name == "l4_timeline"


def test_agent_name() -> None:
    agent = create_l4_timeline_agent()
    assert agent.name == "l4_timeline"


def test_agent_has_tools() -> None:
    agent = create_l4_timeline_agent()
    # Two MCP servers (resource-catalog + web-search) — at least two
    # toolset entries. ADK resolves the concrete tool list lazily at
    # runtime, so we assert the toolset list is non-empty here.
    assert agent.tools
    assert len(list(agent.tools)) >= 2


def test_agent_output_schema() -> None:
    """L4's ``output_schema`` is ``RecommendationResponse`` (refactor
    2026-06-24: L4 absorbed L5's emit responsibility)."""
    agent = create_l4_timeline_agent()
    assert agent.output_schema is RecommendationResponse


def test_agent_default_model() -> None:
    agent = create_l4_timeline_agent()
    # Default model is the spec'd Gemini flash variant.
    assert agent.model is not None


def test_agent_custom_model() -> None:
    agent = create_l4_timeline_agent(model="gemini-2.0-flash")
    assert agent.model is not None


def test_agent_output_key() -> None:
    """L4's ``output_key`` is ``STATE_KEY_FINAL_RECOMMENDATION``
    (formerly ``"timeline"`` pre-refactor)."""
    agent = create_l4_timeline_agent()
    assert agent.output_key == STATE_KEY_FINAL_RECOMMENDATION
    assert agent.output_key == "final_recommendation"


def test_agent_has_after_agent_callback_by_default() -> None:
    """L4 has a non-None ``after_agent_callback`` by default — that's
    ``_l4_finalize_after_agent``, which surfaces the Pydantic
    markdown as user-visible text and falls back to a
    code-rendered summary if validation fails.
    """
    agent = create_l4_timeline_agent()
    assert agent.after_agent_callback is not None
    assert agent.after_agent_callback is _l4_finalize_after_agent


# ─── Absorbed L5 behavior — instruction content (refactor 2026-06-24) ──


def test_l4_instruction_includes_explainer_first_rule() -> None:
    """L4's instruction mentions the pre-coding explainer-first rule
    (absorbed from the former L5 Synthesizer on 2026-06-24)."""
    assert "Pre-coding explainer" in _L4_INSTRUCTION
    assert "explainer" in _L4_INSTRUCTION
    # The detection rule: pre-coding user + explainer resources =>
    # explainers first.
    assert "Start here" in _L4_INSTRUCTION


def test_l4_instruction_includes_urgency_grouping() -> None:
    """L4's instruction mentions URGENCY grouping (absorbed from L5)."""
    assert "URGENCY" in _L4_INSTRUCTION
    # The canonical urgency order CRITICAL -> HIGH -> MEDIUM -> LOW -> STALE
    # is preserved.
    assert "CRITICAL" in _L4_INSTRUCTION
    assert "STALE" in _L4_INSTRUCTION


def test_l4_instruction_includes_refusal_pattern_scrub() -> None:
    """L4's instruction mentions the refusal-pattern scrub (L5's
    defense against instruction-zone echo)."""
    assert "Refusal-pattern" in _L4_INSTRUCTION
    assert "system prompt" in _L4_INSTRUCTION.lower()


def test_l4_instruction_includes_language_selection() -> None:
    """L4's instruction mentions language selection rules (L5's
    user-language awareness)."""
    assert (
        "Language selection" in _L4_INSTRUCTION or "language" in _L4_INSTRUCTION.lower()
    )
    assert "identity" in _L4_INSTRUCTION


# ─── RecommendationResponse schema (absorbed L5 contract) ───────────────


def test_recommendation_response_markdown_required_by_default() -> None:
    """``RecommendationResponse(markdown="x", language="en")`` validates
    when at least one of markdown / ask_back is non-empty."""

    resp = RecommendationResponse(markdown="x", language="en")
    assert resp.markdown == "x"
    assert resp.language == "en"
    assert resp.follow_up is None
    assert resp.ask_back is None


def test_recommendation_response_accepts_ask_back_only() -> None:
    """A RecommendationResponse with only ask_back (markdown=None)
    validates. This is the L4 ask_back short-circuit path
    (refactor 2026-06-24)."""
    resp = RecommendationResponse(
        markdown=None,
        language="en",
        ask_back="could you tell me more?",
    )
    assert resp.ask_back == "could you tell me more?"
    assert resp.markdown is None


def test_recommendation_response_rejects_empty_both() -> None:
    """A RecommendationResponse with markdown=None AND ask_back=None
    fails the ``_validate_either_field`` model validator."""
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown=None, language="en")


def test_recommendation_response_markdown_max_length_3000() -> None:
    """A 3001-char markdown raises ``ValidationError`` (max_length=3000)."""

    long = "a" * 3001
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown=long, language="en")


def test_recommendation_response_ask_back_max_length_500() -> None:
    """A 501-char ask_back raises ``ValidationError`` (max_length=500)."""

    too_long = "q" * 501
    with pytest.raises(ValidationError):
        RecommendationResponse(markdown=None, language="en", ask_back=too_long)


# ─── _coerce_recommendation helper (absorbed from L5) ───────────────────


def test_coerce_recommendation_passes_through_instance() -> None:
    """A RecommendationResponse instance passes through unchanged."""
    rec = RecommendationResponse(markdown="hello", language="en")
    assert _coerce_recommendation(rec) is rec


def test_coerce_recommendation_validates_dict() -> None:
    """A dict matching the schema is validated into a typed model."""
    rec = _coerce_recommendation({"markdown": "hi", "language": "en"})
    assert isinstance(rec, RecommendationResponse)
    assert rec.markdown == "hi"


def test_coerce_recommendation_returns_none_on_invalid() -> None:
    """An invalid dict returns None (no exception)."""
    assert _coerce_recommendation({"markdown": "", "language": "en"}) is None
    assert _coerce_recommendation({"markdown": None, "language": "en"}) is None


def test_coerce_recommendation_returns_none_on_garbage() -> None:
    """A non-dict, non-RecommendationResponse value returns None."""
    assert _coerce_recommendation(42) is None
    assert _coerce_recommendation("string") is None
    assert _coerce_recommendation(None) is None


# ─── _render_fallback_markdown helper (absorbed from L5) ────────────────


def test_fallback_renders_empty_level_filter() -> None:
    """Empty ``level_filter`` produces the "couldn't find" message."""

    out = _render_fallback_markdown({})
    assert "couldn't find" in out.lower()


def test_fallback_renders_level_filter_with_matches() -> None:
    """A level_filter with matches produces a markdown list with
    resource names + URLs."""
    state = {
        "level_filter": LevelFilterResult(
            matches=[
                LevelMatch(
                    resource=ResourceOutput(
                        id="cs231n",
                        name="CS231n",
                        type="course",
                        url="https://cs231n.stanford.edu",
                        description="CNN course",
                    ),
                    matched_level=SkillLevel.ADVANCED,
                    fit_score=0.9,
                ),
                LevelMatch(
                    resource=ResourceOutput(
                        id="kaggle-python",
                        name="Kaggle Learn - Python",
                        type="course",
                        url="https://kaggle.com/learn/python",
                        description="Intro to Python",
                    ),
                    matched_level=SkillLevel.BEGINNER,
                    fit_score=1.0,
                ),
            ]
        )
    }
    out = _render_fallback_markdown(state)
    assert "CS231n" in out
    assert "Kaggle Learn - Python" in out
    assert "https://cs231n.stanford.edu" in out


def test_fallback_renders_dict_form_level_filter() -> None:
    """A dict-form ``level_filter`` (after ADK JSON round-trip) also
    renders."""
    state = {
        "level_filter": {
            "matches": [
                {
                    "resource": {
                        "id": "kaggle-python",
                        "name": "Kaggle Learn",
                        "type": "course",
                        "url": "https://kaggle.com/learn/python",
                        "description": "Intro to Python",
                    },
                    "matched_level": "beginner",
                    "fit_score": 1.0,
                }
            ]
        }
    }
    out = _render_fallback_markdown(state)
    assert "Kaggle Learn" in out


# ─── _l4_finalize_after_agent callback (absorbed from L5) ──────────────


def test_l4_finalize_returns_pydantic_markdown_on_valid_output() -> None:
    """When ``state['final_recommendation']`` is a valid
    ``RecommendationResponse`` with markdown, the callback returns
    a ``Content`` whose text is the markdown field (overrides the
    LLM's raw JSON natural text)."""

    class _Ctx:
        def __init__(self) -> None:
            self.state = {
                STATE_KEY_FINAL_RECOMMENDATION: RecommendationResponse(
                    markdown="Here are your picks.", language="en"
                )
            }

    out = _l4_finalize_after_agent(_Ctx())
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    assert out.parts[0].text == "Here are your picks."


def test_l4_finalize_writes_ask_back_to_state() -> None:
    """When ``state['final_recommendation']`` has a non-empty
    ``ask_back``, the callback writes it to ``state['ask_back']``
    (for ``run_lumi_query`` to detect) AND returns a Content with
    the ask_back text."""

    class _Ctx:
        def __init__(self) -> None:
            self.state = {
                STATE_KEY_FINAL_RECOMMENDATION: RecommendationResponse(
                    markdown=None,
                    language="en",
                    ask_back="could you broaden the topic?",
                )
            }

    ctx = _Ctx()
    out = _l4_finalize_after_agent(ctx)
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    assert out.parts[0].text == "could you broaden the topic?"
    # state['ask_back'] should now be set for run_lumi_query.
    assert ctx.state.get("ask_back") == "could you broaden the topic?"


def test_l4_finalize_falls_back_on_invalid_output() -> None:
    """When ``state['final_recommendation']`` fails validation, the
    callback falls back to a code-rendered summary."""

    class _Ctx:
        def __init__(self) -> None:
            self.state = {
                STATE_KEY_FINAL_RECOMMENDATION: {
                    "markdown": "x" * 5000,
                    "language": "en",
                },
            }

    out = _l4_finalize_after_agent(_Ctx())
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    # 5000-char markdown fails max_length; empty level_filter => "couldn't find"
    assert "couldn't find" in out.parts[0].text.lower()


def test_l4_finalize_returns_empty_content_on_no_state() -> None:
    """If the callback context has no ``state``, return empty Content."""

    class _NoStateCtx:
        state = None

    out = _l4_finalize_after_agent(_NoStateCtx())
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


# ─── TimelineResult schema ─────────────────────────────────────────────


def test_timeline_result_validates_empty() -> None:
    result = TimelineResult()
    assert result.ranked == []
    assert result.reasoning == ""
    # `today` defaults to today() as an ISO 8601 string (see schema note
    # about why we store it as str rather than date).
    assert isinstance(result.today, str)
    assert result.today == date.today().isoformat()


def test_timeline_result_validates_with_entries() -> None:
    entry = TimelineEntry(
        resource=_sample_resource(),
        urgency=Urgency.HIGH,
        days_until_deadline=21,
        freshness_signal="recent",
        recommended_action="Register this week",
    )
    result = TimelineResult(
        ranked=[entry],
        today="2026-06-21",
        reasoning="one high-urgency resource",
    )
    assert len(result.ranked) == 1
    assert result.ranked[0].urgency == Urgency.HIGH
    assert result.today == "2026-06-21"


def test_timeline_entry_urgency_enum() -> None:
    assert Urgency.CRITICAL == "critical"
    assert Urgency.HIGH == "high"
    assert Urgency.MEDIUM == "medium"
    assert Urgency.LOW == "low"
    assert Urgency.STALE == "stale"


def test_timeline_entry_days_until_deadline_optional() -> None:
    entry = TimelineEntry(
        resource=_sample_resource(),
        urgency=Urgency.LOW,
        freshness_signal="unverified",
        recommended_action="Bookmark for later",
    )
    assert entry.days_until_deadline is None


def test_timeline_entry_freshness_signal() -> None:
    # The schema allows any non-empty string for `freshness_signal`;
    # verify a few common values construct cleanly.
    for signal in ("fresh", "recent", "stale", "unverified"):
        entry = TimelineEntry(
            resource=_sample_resource(),
            urgency=Urgency.MEDIUM,
            freshness_signal=signal,
            recommended_action="act",
        )
        assert entry.freshness_signal == signal


def test_urgency_enum_values() -> None:
    # All five urgency levels must exist and have stable string values.
    values = {u.value for u in Urgency}
    assert values == {"critical", "high", "medium", "low", "stale"}


def test_timeline_result_rejects_bad_urgency() -> None:
    with pytest.raises(ValidationError):
        TimelineEntry(
            resource=_sample_resource(),
            urgency="not-a-real-urgency",  # type: ignore[arg-type]
            freshness_signal="fresh",
            recommended_action="act",
        )


# ─── Heuristic (code-side urgency classification) ───────────────────────


def test_classify_none_is_low() -> None:
    assert classify_days_until_deadline(None) is Urgency.LOW


def test_classify_past_deadline_is_critical() -> None:
    assert classify_days_until_deadline(-1) is Urgency.CRITICAL


def test_classify_within_14_days_is_critical() -> None:
    assert classify_days_until_deadline(0) is Urgency.CRITICAL
    assert classify_days_until_deadline(14) is Urgency.CRITICAL


def test_classify_within_30_days_is_high() -> None:
    assert classify_days_until_deadline(15) is Urgency.HIGH
    assert classify_days_until_deadline(30) is Urgency.HIGH


def test_classify_within_90_days_is_medium() -> None:
    assert classify_days_until_deadline(31) is Urgency.MEDIUM
    assert classify_days_until_deadline(90) is Urgency.MEDIUM


def test_classify_beyond_90_days_is_low() -> None:
    assert classify_days_until_deadline(91) is Urgency.LOW


# ─── ask_back field (CONTEXT.md #22) ────────────────────────────────────


def test_timeline_result_accepts_ask_back() -> None:
    """``TimelineResult`` accepts a string ``ask_back`` field."""

    result = TimelineResult(
        ranked=[],
        today="2026-06-21",
        reasoning="no time-sensitive matches",
        ask_back="could you broaden the topic?",
    )
    assert result.ask_back == "could you broaden the topic?"


def test_timeline_result_ask_back_max_length_500() -> None:
    """A 501-char ``ask_back`` raises ``ValidationError`` (CONTEXT.md #22)."""

    too_long = "q" * 501
    with pytest.raises(ValidationError):
        TimelineResult(
            ranked=[],
            today="2026-06-21",
            reasoning="empty",
            ask_back=too_long,
        )


def test_timeline_result_ask_back_defaults_to_none() -> None:
    """``ask_back`` defaults to ``None`` when not supplied."""

    result = TimelineResult()
    assert result.ask_back is None
    assert classify_days_until_deadline(365) is Urgency.LOW
