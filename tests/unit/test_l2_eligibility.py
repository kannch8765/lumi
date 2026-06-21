"""Outcome-based unit tests for the L2 Eligibility Agent.

Tests cover two layers (per CONTEXT.md #21):

  1. Agent construction — the factory returns a valid ``LlmAgent``
     with the correct name, tools, and output schema. These tests
     assert on the constructed agent's observable attributes, no
     mocks.

  2. Schema validation — ``EligibilityResult`` and ``EligibleResource``
     accept the shapes L2 produces. These guard against accidental
     schema drift between L2 and L3 (the next pipeline layer).

LLM behavior tests (filter correctness on real catalog entries) live
in Task 26 (``tests/unit/test_l2_eligibility_injection.py`` and the
``tests/integration/test_pipeline_e2e.py`` happy path). Per CONTEXT.md
#7 — no mocks, observe return value and observable state.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset

from app.agents.l2_eligibility import create_l2_eligibility_agent
from app.agents.schemas import (
    EligibilityResult,
    EligibleResource,
    IdentityProfile,
)
from app.mcp_servers.resource_catalog.schemas import ResourceOutput

# ─── Agent construction ─────────────────────────────────────────────────


def test_factory_returns_agent() -> None:
    """``create_l2_eligibility_agent()`` returns an LlmAgent instance."""

    agent = create_l2_eligibility_agent()
    assert isinstance(agent, LlmAgent)


def test_agent_name() -> None:
    """The agent's name is exactly ``l2_eligibility`` (pipeline contract)."""

    agent = create_l2_eligibility_agent()
    assert agent.name == "l2_eligibility"


def test_agent_has_tools() -> None:
    """The agent has at least one tool configured (the catalog MCP toolset)."""

    agent = create_l2_eligibility_agent()
    assert len(agent.tools) >= 1
    # Tool whitelist invariant — every tool bound to L2 must be an
    # McpToolset (we have no FunctionTool / no inline def). This is
    # the in-code check for CONTEXT.md #10 — tool whitelist is the
    # kill switch.
    assert all(isinstance(t, McpToolset) for t in agent.tools)


def test_agent_output_schema() -> None:
    """The agent's ``output_schema`` is ``EligibilityResult``."""

    agent = create_l2_eligibility_agent()
    assert agent.output_schema is EligibilityResult


def test_agent_output_key() -> None:
    """The agent stores its result under ``eligibility`` for L3 to consume."""

    agent = create_l2_eligibility_agent()
    assert agent.output_key == "eligibility"


def test_agent_default_model() -> None:
    """Default model is the Flash-tier Gemini (cost / latency rationale)."""

    agent = create_l2_eligibility_agent()
    # ``model`` on LlmAgent is a ``BaseLlm`` instance; check its class name
    # rather than its ``__repr__`` (which embeds the model id).
    assert type(agent.model).__name__ == "Gemini"


# ─── Schema validation ─────────────────────────────────────────────────


def _sample_resource() -> ResourceOutput:
    """Build a minimal ResourceOutput for schema tests."""

    return ResourceOutput(
        id="cs231n-stanford",
        name="CS231n",
        type="course",
        url="https://cs231n.stanford.edu",
        description="Convolutional Neural Networks for Visual Recognition",
        language="en",
    )


def test_eligibility_result_validates_empty() -> None:
    """An empty EligibilityResult with a short reasoning is valid."""

    result = EligibilityResult(eligible=[], reasoning="no matches")
    assert result.eligible == []
    assert result.insufficient_data is False
    assert result.reasoning == "no matches"


def test_eligibility_result_validates_with_matches() -> None:
    """An EligibilityResult with one EligibleResource round-trips."""

    resource = _sample_resource()
    match = EligibleResource(resource=resource, matched_constraints=["age", "language"])
    result = EligibilityResult(eligible=[match], reasoning="kept one")
    assert len(result.eligible) == 1
    assert result.eligible[0].resource.id == "cs231n-stanford"
    assert result.reasoning == "kept one"


def test_eligibility_result_insufficient_data_flag() -> None:
    """``insufficient_data=True`` is accepted and stored verbatim."""

    result = EligibilityResult(
        eligible=[], insufficient_data=True, reasoning="profile too thin"
    )
    assert result.insufficient_data is True
    assert result.reasoning == "profile too thin"


def test_eligible_resource_matched_constraints() -> None:
    """Matched constraints list-of-strings round-trips."""

    resource = _sample_resource()
    match = EligibleResource(
        resource=resource,
        matched_constraints=["age", "location", "language"],
    )
    assert match.matched_constraints == ["age", "location", "language"]
    assert match.rejected_constraints == []  # default factory


def test_eligible_resource_rejected_constraints() -> None:
    """Rejected constraints list-of-strings round-trips."""

    resource = _sample_resource()
    match = EligibleResource(
        resource=resource,
        matched_constraints=["age"],
        rejected_constraints=["institution_requirement"],
    )
    assert match.matched_constraints == ["age"]
    assert match.rejected_constraints == ["institution_requirement"]


def test_eligibility_result_serializes_via_resource_output() -> None:
    """L2's output embeds a ResourceOutput — verify the nested shape."""

    resource = _sample_resource()
    match = EligibleResource(resource=resource, matched_constraints=["age"])
    result = EligibilityResult(eligible=[match], reasoning="ok")

    dumped = result.model_dump()
    assert dumped["eligible"][0]["resource"]["id"] == "cs231n-stanford"
    assert dumped["eligible"][0]["matched_constraints"] == ["age"]
    assert dumped["insufficient_data"] is False
    assert dumped["reasoning"] == "ok"


# ─── Cross-layer contract ──────────────────────────────────────────────


def test_identity_profile_does_not_pollute_l2_schema() -> None:
    """L2's output schema is independent of L1's IdentityProfile shape.

    Sanity check that adding ``EligibilityResult`` did not accidentally
    mutate ``IdentityProfile`` (L1's contract is preserved by L2's
    factory reading ``session.state['identity']``).
    """

    profile = IdentityProfile(raw_query="hello")
    assert profile.age is None
    assert profile.education_level is None
    assert profile.languages == []
    assert profile.interests == []
    assert profile.confidence == 0.0

    # And L2's output is its own type, not a subclass of IdentityProfile.
    result = EligibilityResult(eligible=[], reasoning="")
    assert not isinstance(result, IdentityProfile)
