"""Outcome-based unit tests for the L4 Timeline Agent (Task 32).

These tests assert on the factory output (LlmAgent attributes) and
on the TimelineResult schema. No mocks, no monkey-patching of the
production code per CONTEXT.md rule #7 — a test that passes with
the factory replaced by `return None` would not be a real test.

The McpToolset attribute is asserted to be a non-empty list (both
the resource-catalog and the web-search MCP servers are exposed).
We do not invoke the tool subprocesses — that requires a live ADK
runtime and is covered by the integration tests in
`tests/integration/test_pipeline_e2e.py` (Task 26).
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.agents.l4_timeline import create_l4_timeline_agent
from app.agents.schemas import (
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
    agent = create_l4_timeline_agent()
    assert agent.output_schema is TimelineResult


def test_agent_default_model() -> None:
    agent = create_l4_timeline_agent()
    # Default model is the spec'd Gemini flash variant.
    assert agent.model is not None


def test_agent_custom_model() -> None:
    agent = create_l4_timeline_agent(model="gemini-2.0-flash")
    assert agent.model is not None


def test_agent_output_key() -> None:
    agent = create_l4_timeline_agent()
    assert agent.output_key == "timeline"


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
