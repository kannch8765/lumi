"""Outcome-based unit tests for the L3 Level Filter Agent.

These tests assert on the factory's return value and on the schemas
that flow out of L3. They do NOT call the LLM (no integration cost) —
they verify the structural contract L3 advertises to the orchestrator
and to L4. Integration tests for the live L3 path belong in
``tests/integration/``.

Lumi test policy (CONTEXT.md #7): no mocks, observe return value
and observable state mutation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.l3_level import create_l3_level_agent
from app.agents.schemas import (
    LevelFilterResult,
    LevelMatch,
    SkillLevel,
)
from app.mcp_servers.resource_catalog.schemas import ResourceOutput


def test_factory_returns_agent() -> None:
    """The factory must return an LlmAgent (the ADK contract)."""

    agent = create_l3_level_agent()
    assert agent is not None


def test_agent_name() -> None:
    """Agent name is the canonical key the orchestrator uses to wire L3."""

    agent = create_l3_level_agent()
    assert agent.name == "l3_level"


def test_agent_has_tools() -> None:
    """L3 must register at least one tool (resource-catalog MCP)."""

    agent = create_l3_level_agent()
    assert agent.tools is not None
    assert len(agent.tools) >= 1


def test_agent_output_schema() -> None:
    """The output_schema is LevelFilterResult — the orchestrator's contract."""

    agent = create_l3_level_agent()
    assert agent.output_schema is LevelFilterResult


def test_agent_output_key() -> None:
    """The output_key is 'level_filter' so L4 can read it from session state."""

    agent = create_l3_level_agent()
    assert agent.output_key == "level_filter"


def test_level_filter_result_validates_empty() -> None:
    """An empty result is valid — L3 may drop everything if nothing fits."""

    result = LevelFilterResult(matches=[], user_level=None, reasoning="")
    assert result.matches == []
    assert result.user_level is None
    assert result.reasoning == ""


def test_level_filter_result_validates_with_matches() -> None:
    """A populated result round-trips through Pydantic with field fidelity."""

    resource = ResourceOutput(
        id="cs231n-stanford",
        name="CS231N",
        type="course",
        url="https://example.com/cs231n",
        level="intermediate",
        description="Stanford deep-learning course.",
    )
    match = LevelMatch(
        resource=resource,
        matched_level=SkillLevel.INTERMEDIATE,
        fit_score=0.9,
    )
    result = LevelFilterResult(
        matches=[match],
        user_level=SkillLevel.INTERMEDIATE,
        reasoning="Undergraduate user; intermediate courses match exactly.",
    )
    assert len(result.matches) == 1
    assert result.matches[0].resource.id == "cs231n-stanford"
    assert result.matches[0].matched_level == SkillLevel.INTERMEDIATE
    assert result.matches[0].fit_score == 0.9
    assert result.user_level == SkillLevel.INTERMEDIATE


def test_skill_level_enum_values() -> None:
    """SkillLevel string values must match the catalog-level vocabulary.

    The enum serializes as ``all_levels`` but the catalog uses ``all``.
    L3's agent instruction documents the mapping; the enum is the
    in-agent canonical form.
    """

    assert SkillLevel.BEGINNER.value == "beginner"
    assert SkillLevel.INTERMEDIATE.value == "intermediate"
    assert SkillLevel.ADVANCED.value == "advanced"
    assert SkillLevel.ALL_LEVELS.value == "all_levels"


def test_level_match_fit_score_bounds() -> None:
    """fit_score must lie in [0.0, 1.0]; Pydantic rejects the rest."""

    resource = ResourceOutput(
        id="x",
        name="X",
        type="course",
        url="https://example.com/x",
        description="",
    )

    # Within bounds — accepted.
    LevelMatch(resource=resource, matched_level=SkillLevel.BEGINNER, fit_score=0.0)
    LevelMatch(resource=resource, matched_level=SkillLevel.BEGINNER, fit_score=1.0)

    # Above the upper bound — rejected.
    with pytest.raises(ValidationError):
        LevelMatch(
            resource=resource,
            matched_level=SkillLevel.BEGINNER,
            fit_score=1.5,
        )

    # Below the lower bound — rejected.
    with pytest.raises(ValidationError):
        LevelMatch(
            resource=resource,
            matched_level=SkillLevel.BEGINNER,
            fit_score=-0.1,
        )


def test_user_level_optional() -> None:
    """user_level can be None — L3 may not always infer a level."""

    result = LevelFilterResult(
        matches=[],
        user_level=None,
        reasoning="Identity profile too sparse to infer a level.",
    )
    assert result.user_level is None
