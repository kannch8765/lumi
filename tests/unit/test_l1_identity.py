"""Outcome-based unit tests for the L1 Identity Agent.

These tests cover agent construction and the :class:`IdentityProfile`
Pydantic schema. They do NOT exercise the live Gemini model — that
requires an API key and a golden-scenario suite, which is planned
for Task 26 (see ``PLAN.md`` Phase 4). All assertions are on
return values and observable state, per CONTEXT.md #7 (no mocks,
no ``monkeypatch`` of business logic).
"""

from __future__ import annotations

import os

import pytest
from google.adk.agents import LlmAgent
from pydantic import ValidationError

from app.agents.l1_identity import DEFAULT_L1_MODEL, create_l1_identity_agent
from app.agents.schemas import EducationLevel, IdentityProfile

# ── Agent construction ─────────────────────────────────────────────────


def test_factory_returns_agent() -> None:
    """The factory must return an ADK ``LlmAgent`` instance."""
    agent = create_l1_identity_agent()
    assert isinstance(agent, LlmAgent)


def test_agent_name() -> None:
    """The agent name is the pipeline identifier ``l1_identity``."""
    agent = create_l1_identity_agent()
    assert agent.name == "l1_identity"


def test_agent_output_schema() -> None:
    """The agent's output schema is :class:`IdentityProfile`."""
    agent = create_l1_identity_agent()
    # ``output_schema`` is stored as a Pydantic ``type[BaseModel]``;
    # identity comparison is the simplest correct check.
    assert agent.output_schema is IdentityProfile


def test_agent_output_key() -> None:
    """The agent writes its output to session state key ``identity``.

    The orchestrator (Task 25) reads downstream agents' outputs from
    the session state, so the key must be stable and documented.
    """
    agent = create_l1_identity_agent()
    assert agent.output_key == "identity"


def test_agent_has_no_tools() -> None:
    """L1 has zero tools — it only collects identity.

    ARCHITECTURE.md §L1: "CANNOT do" includes "Store profile beyond
    session" and L1 has no search responsibility. Per CONTEXT.md
    #10, the tool whitelist is the kill switch, and L1's portion
    of that whitelist is empty.
    """
    agent = create_l1_identity_agent()
    assert agent.tools == []


def test_agent_default_model_is_flash() -> None:
    """The default model is the Flash-tier Gemini model.

    Locked in so the orchestrator can rely on the default latency
    profile and so accidental model upgrades are intentional.
    """
    assert DEFAULT_L1_MODEL == "gemini-3.1-flash-lite"
    agent = create_l1_identity_agent()
    # ``model`` is wrapped in a ``Gemini`` instance. Read the
    # underlying string back from the Pydantic field.
    model_obj = agent.model
    assert model_obj.model == DEFAULT_L1_MODEL  # type: ignore[attr-defined]


def test_agent_uses_custom_model() -> None:
    """The factory accepts an override for the model name."""
    agent = create_l1_identity_agent(model="gemini-2.5-pro")
    model_obj = agent.model
    assert model_obj.model == "gemini-2.5-pro"  # type: ignore[attr-defined]


def test_agent_instruction_is_non_empty_string() -> None:
    """The system prompt must be a non-empty string.

    The instruction encodes the three-zone prompt-injection defense
    (CONTEXT.md #18). A blank instruction would silently disable it.
    """
    agent = create_l1_identity_agent()
    assert isinstance(agent.instruction, str)
    assert len(agent.instruction) > 0
    # Spot-check the three zones are present so the defense is real.
    instruction = agent.instruction
    assert "INSTRUCTION ZONE" in instruction
    assert "USER ZONE" in instruction
    assert "TOOL ZONE" in instruction


# ── IdentityProfile schema ─────────────────────────────────────────────


def test_identity_profile_validates_minimal() -> None:
    """A profile with only ``raw_query`` is valid; everything else defaults."""
    profile = IdentityProfile(raw_query="hi")
    assert profile.raw_query == "hi"
    assert profile.age is None
    assert profile.location is None
    assert profile.education_level is None
    assert profile.languages == []
    assert profile.interests == []
    assert profile.goals is None
    assert profile.confidence == 0.0


def test_identity_profile_validates_full() -> None:
    """All fields populated, age in range, valid confidence."""
    profile = IdentityProfile(
        age=25,
        location="BR",
        education_level=EducationLevel.UNDERGRADUATE,
        languages=["pt", "en"],
        interests=["nlp", "llm"],
        goals="learn transformers",
        raw_query="I am 25, undergrad in Brazil, want to learn transformers",
        confidence=0.9,
    )
    assert profile.age == 25
    assert profile.location == "BR"
    assert profile.education_level is EducationLevel.UNDERGRADUATE
    assert profile.languages == ["pt", "en"]
    assert profile.interests == ["nlp", "llm"]
    assert profile.goals == "learn transformers"
    assert profile.raw_query.startswith("I am 25")
    assert profile.confidence == 0.9


def test_identity_profile_rejects_invalid_age() -> None:
    """Age out of bounds [5, 120] raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", age=200)
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", age=2)
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", age=-1)


def test_identity_profile_confidence_bounds() -> None:
    """Confidence outside [0.0, 1.0] raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", confidence=1.5)
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", confidence=-0.1)


def test_identity_profile_education_level_enum() -> None:
    """Enum members serialize to their stable string values."""
    assert EducationLevel.HIGH_SCHOOL.value == "high_school"
    assert EducationLevel.UNDERGRADUATE.value == "undergraduate"
    assert EducationLevel.GRADUATE.value == "graduate"
    assert EducationLevel.SELF_TAUGHT.value == "self_taught"
    assert EducationLevel.PROFESSIONAL.value == "professional"

    # Round-trip via the schema: the LLM outputs the string, the
    # schema accepts it and resolves to the enum member.
    profile = IdentityProfile(
        raw_query="x",
        education_level=EducationLevel.HIGH_SCHOOL,
    )
    assert profile.education_level is EducationLevel.HIGH_SCHOOL


def test_identity_profile_languages_default_empty() -> None:
    """``languages`` defaults to an empty list, not ``None``."""
    profile = IdentityProfile(raw_query="x")
    assert profile.languages == []
    assert isinstance(profile.languages, list)


def test_identity_profile_rejects_missing_raw_query() -> None:
    """``raw_query`` is the only required field — omitting it must fail."""
    with pytest.raises(ValidationError):
        IdentityProfile()  # type: ignore[call-arg]


# ── Live smoke test (skipped without API key) ─────────────────────────
# This test exercises the real Gemini model and is gated on
# GEMINI_API_KEY being present in the environment. Per Task 26's
# plan, the full golden-scenario suite for L1 will live alongside
# this file; for now we just check that one representative input
# round-trips through the agent.


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="requires GEMINI_API_KEY in environment",
)
def test_agent_smoke_test_live_model() -> None:
    """Smoke test the real Gemini model with a representative query.

    Asserts that age and location are extracted for a query that
    explicitly states them. This is intentionally a single,
    obvious case — the broader golden-scenario suite is Task 26.
    """
    import asyncio

    from app.agents.l1_identity import create_l1_identity_agent

    agent = create_l1_identity_agent()
    assert agent.output_schema is IdentityProfile

    # Construct a minimal Content with the user's text. We avoid
    # the full ADK Runner here so the test stays a pure unit test
    # that doesn't depend on session plumbing. The real integration
    # test lives in tests/integration/test_pipeline_e2e.py (Task 25+).
    from google.genai import types as genai_types

    content = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(text="I'm 17 years old in Tokyo and want to learn LLMs")
        ],
    )

    async def _run() -> IdentityProfile:
        # Use the LLM directly via the Gemini wrapper to avoid
        # requiring a full ADK Runner / session for this smoke test.
        model_obj = agent.model
        from google.adk.models.llm_request import LlmRequest

        request = LlmRequest(
            model=DEFAULT_L1_MODEL,
            contents=[content],
            config=genai_types.GenerateContentConfig(
                response_schema=IdentityProfile.model_json_schema(),
                response_mime_type="application/json",
            ),
        )
        response_text = ""
        async for resp in model_obj.generate_content_async(  # type: ignore[attr-defined]
            request, stream=False
        ):
            if resp.content and resp.content.parts:
                for part in resp.content.parts:
                    if part.text:
                        response_text += part.text
        return IdentityProfile.model_validate_json(response_text)

    profile = asyncio.run(_run())
    assert profile.age == 17
    assert profile.location is not None
    assert "tokyo" in profile.location.lower()
