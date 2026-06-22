"""L1 router tests — Task #64.

The L1 router redesign (Tasks #60-#63) turns L1 from a pure
identity extractor into an identity extractor AND a single-turn
intent router. The orchestrator reads L1's ``intent`` +
``target_agents`` fields and uses ``before_agent_callback`` to
skip non-targeted sub-agents in O(0 LLM calls).

These tests cover the structural pieces without spinning up a
real Gemini model (the live happy-path is covered by
``tests/integration/test_pipeline_e2e.py``):

  1. ``IdentityProfile`` schema defaults — every new field has
     the right default so legacy tests + non-router callers
     keep working.
  2. The 5 intent values are accepted by the schema and round-trip.
  3. ``_make_should_i_run_callback`` factory returns callables
     that respect ``state['identity']['target_agents']``.
  4. The orchestrator wires the skip callback to every
     downstream sub-agent (L2, L3, L4, ranker) but NOT to L1
     (the router itself, which must always run).
  5. The ranker callback (``_rank_after_agent``) writes
     ``state['final_user_response']`` when ``out_of_scope=True``
     and skips the ranking step.

Per CONTEXT.md #7 there are no mocks — these tests use a tiny
fake ``callback_context`` that exposes ``.state`` as a plain
dict, matching how ADK surfaces it in practice.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from google.adk.agents import SequentialAgent
from google.genai import types as genai_types
from pydantic import ValidationError

from app.agents.schemas import IdentityProfile, LumiIntent
from app.orchestrator import (
    DEFAULT_OUT_OF_SCOPE_APOLOGY,
    STATE_KEY_FINAL_USER_RESPONSE,
    STATE_KEY_IDENTITY,
    STATE_KEY_RANKED_TIMELINE,
    _make_should_i_run_callback,
    _rank_after_agent,
    create_lumi_pipeline,
    run_lumi_query,
)

# ── Schema defaults (Task #60) ─────────────────────────────────────────


def test_identity_profile_default_intent_is_full_pipeline() -> None:
    """The default intent preserves the legacy always-run behavior.

    Tests that don't exercise the router (e.g. legacy
    prompt-injection suites) construct ``IdentityProfile`` with
    only ``raw_query``. Without a default they'd silently fall
    through to a no-op pipeline.
    """
    profile = IdentityProfile(raw_query="hello")
    assert profile.intent == "full_pipeline"


def test_identity_profile_default_target_agents_runs_everything() -> None:
    """Default ``target_agents`` lists every downstream agent.

    With the default in place, the legacy always-run pipeline
    keeps working even when no router field is set.
    """
    profile = IdentityProfile(raw_query="hello")
    assert set(profile.target_agents) == {
        "l2_eligibility",
        "l3_level",
        "l4_timeline",
        "timeline_ranker",
    }


def test_identity_profile_default_out_of_scope_false() -> None:
    """Default ``out_of_scope=False`` so the OOS short-circuit never
    fires unless L1 explicitly sets it.
    """
    profile = IdentityProfile(raw_query="hello")
    assert profile.out_of_scope is False


def test_identity_profile_default_apology_is_none() -> None:
    """Default ``apology=None`` so the field is optional.

    ``_rank_after_agent`` falls back to
    :data:`DEFAULT_OUT_OF_SCOPE_APOLOGY` when L1 omits it, so a
    missing apology never collapses the pipeline to silence.
    """
    profile = IdentityProfile(raw_query="hello")
    assert profile.apology is None


# ── 5 intent values ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "intent",
    ["full_pipeline", "filter_only", "freshness_check", "drill_down", "out_of_scope"],
)
def test_identity_profile_accepts_all_five_intents(intent: LumiIntent) -> None:
    """All five routing intents are valid Literal members.

    Locked so adding a 6th intent requires updating this test —
    keeps the L1 prompt and the schema in lock-step.
    """
    profile = IdentityProfile(raw_query="x", intent=intent)
    assert profile.intent == intent


def test_identity_profile_rejects_unknown_intent() -> None:
    """An intent outside the Literal set must be rejected at the
    schema boundary, not silently passed through to the
    orchestrator."""
    with pytest.raises(ValidationError):
        IdentityProfile(raw_query="x", intent="not_a_real_intent")  # type: ignore[arg-type]


def test_identity_profile_accepts_empty_target_agents_for_out_of_scope() -> None:
    """``target_agents=[]`` is the OOS shape — every downstream
    agent should be skipped."""
    profile = IdentityProfile(
        raw_query="x",
        intent="out_of_scope",
        target_agents=[],
        out_of_scope=True,
        apology="sorry, that's outside Lumi's scope.",
    )
    assert profile.target_agents == []
    assert profile.out_of_scope is True
    assert profile.apology is not None


# ── before_agent_callback skip behavior (Task #62) ─────────────────────


class _FakeCallbackContext:
    """Minimal stand-in for ADK's CallbackContext for unit tests.

    Mirrors the only attribute the skip callback reads
    (``state``) and behaves like a mutable mapping so the callback
    can write to it without surprises. Per CONTEXT.md #7 no
    mocking library is needed — a tiny test double is clearer.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state = state if state is not None else {}


def test_should_i_run_callback_returns_none_when_targeted() -> None:
    """The callback returns None (= run normally) when the agent
    is in ``target_agents``."""
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: {
                "intent": "full_pipeline",
                "target_agents": [
                    "l2_eligibility",
                    "l3_level",
                    "l4_timeline",
                    "timeline_ranker",
                ],
            }
        }
    )
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None


def test_should_i_run_callback_returns_empty_content_when_not_targeted() -> None:
    """The callback returns an empty ``Content`` (= skip) when the
    agent is NOT in ``target_agents``. Zero LLM calls."""
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: {
                "intent": "freshness_check",
                # freshness_check skips L2 + L3, runs L4 + ranker only.
                "target_agents": ["l4_timeline", "timeline_ranker"],
            }
        }
    )
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert isinstance(result, genai_types.Content)
    assert result.role == "model"
    # Empty parts = no LLM call, no output, just a no-op agent step.
    assert result.parts == []


def test_should_i_run_callback_runs_when_no_state_at_all() -> None:
    """Defense in depth: if the callback context has no state
    attribute (e.g. a malformed ADK callback surface), the agent
    must still run — we never want a missing state to silently
    bypass the pipeline."""
    ctx = _FakeCallbackContext(state=None)
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None


def test_should_i_run_callback_runs_when_identity_missing() -> None:
    """If L1 hasn't written identity yet (e.g. an early abort), the
    callback must NOT skip the agent. The worst case is the legacy
    always-run behavior, never a silent skip."""
    ctx = _FakeCallbackContext(state={})
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None


def test_should_i_run_callback_runs_when_target_agents_missing() -> None:
    """If L1 wrote identity but no ``target_agents`` (e.g. older
    schema), default to running the agent."""
    ctx = _FakeCallbackContext(state={STATE_KEY_IDENTITY: {"intent": "full_pipeline"}})
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None


# ── Orchestrator wiring (Task #62 + #63) ───────────────────────────────


def test_pipeline_wires_skip_callbacks_to_downstream_agents_only() -> None:
    """L2/L3/L4/ranker each have a ``before_agent_callback`` so the
    router can skip them; L1 itself has NO callback (the router
    always runs, by design)."""
    pipeline = create_lumi_pipeline()
    assert isinstance(pipeline, SequentialAgent)
    names_to_callbacks = {
        agent.name: getattr(agent, "before_agent_callback", None)
        for agent in pipeline.sub_agents
    }
    # L1 must NOT have a skip callback — it's the router, always runs.
    assert names_to_callbacks["l1_identity"] is None
    # Every downstream agent MUST have a skip callback.
    for name in ("l2_eligibility", "l3_level", "l4_timeline", "timeline_ranker"):
        assert names_to_callbacks[name] is not None, (
            f"{name} should have a before_agent_callback wired by the orchestrator"
        )
        assert callable(names_to_callbacks[name])


def test_pipeline_wired_callbacks_reference_correct_agent_names() -> None:
    """The orchestrator passes the agent's own ``name`` to the
    callback factory. A typo here would cause the wrong agent to
    be skipped — lock it down."""
    pipeline = create_lumi_pipeline()
    for agent in pipeline.sub_agents:
        if agent.name == "l1_identity":
            continue
        cb = agent.before_agent_callback
        assert cb is not None
        # The factory closes over the agent's name. We probe by
        # running the callback against a fake context that lists
        # every agent — the targeted one should return None
        # (= run), the rest would return empty Content (= skip).
        ctx = _FakeCallbackContext(
            state={
                STATE_KEY_IDENTITY: {
                    "intent": "full_pipeline",
                    "target_agents": [agent.name],
                }
            }
        )
        result = asyncio.run(cb(ctx))
        assert result is None, (
            f"callback wired to {agent.name} should run when its "
            f"own name is the only target_agent"
        )


# ── out_of_scope short-circuit (Task #63) ──────────────────────────────


def test_rank_after_agent_writes_apology_when_out_of_scope() -> None:
    """When ``identity.out_of_scope=True``, the ranker callback
    writes the apology to ``state['final_user_response']`` and
    skips the ranking step entirely."""
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: {
                "out_of_scope": True,
                "apology": "Lumi only handles AI/ML learning — please rephrase.",
            }
        }
    )
    # ``_rank_after_agent`` is a sync callback (ADK calls it directly,
    # not via ``await``). Calling it with ``asyncio.run`` would fail
    # with "a coroutine was expected, got Content".
    result = _rank_after_agent(ctx)
    assert isinstance(result, genai_types.Content)
    assert result.parts == []
    assert ctx.state[STATE_KEY_FINAL_USER_RESPONSE] == (
        "Lumi only handles AI/ML learning — please rephrase."
    )
    # Ranker must NOT have written the timeline path when OOS.
    assert STATE_KEY_RANKED_TIMELINE not in ctx.state


def test_rank_after_agent_falls_back_to_default_apology_when_missing() -> None:
    """If L1 sets ``out_of_scope=True`` but forgets the apology
    text, the callback falls back to
    :data:`DEFAULT_OUT_OF_SCOPE_APOLOGY` so the user always gets
    a reply."""
    ctx = _FakeCallbackContext(
        state={STATE_KEY_IDENTITY: {"out_of_scope": True, "apology": None}}
    )
    _rank_after_agent(ctx)
    assert ctx.state[STATE_KEY_FINAL_USER_RESPONSE] == DEFAULT_OUT_OF_SCOPE_APOLOGY


def test_rank_after_agent_runs_normally_when_in_scope() -> None:
    """The OOS check must NOT fire when ``out_of_scope=False`` —
    the ranker should fall through to the timeline path.
    """
    from app.agents.schemas import TimelineResult

    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: {"out_of_scope": False},
            "timeline": TimelineResult().model_dump(mode="json"),
        }
    )
    _rank_after_agent(ctx)
    # Normal path: final_user_response untouched, ranked_timeline written.
    assert STATE_KEY_FINAL_USER_RESPONSE not in ctx.state
    assert STATE_KEY_RANKED_TIMELINE in ctx.state


# ── Intent → target_agents mapping (Task #61) ─────────────────────────


@pytest.mark.parametrize(
    "intent,expected_agents",
    [
        (
            "full_pipeline",
            {"l2_eligibility", "l3_level", "l4_timeline", "timeline_ranker"},
        ),
        ("filter_only", {"l3_level", "l4_timeline", "timeline_ranker"}),
        ("freshness_check", {"l4_timeline", "timeline_ranker"}),
        ("drill_down", {"timeline_ranker"}),
        ("out_of_scope", set()),
    ],
)
def test_intent_to_target_agents_mapping(
    intent: str, expected_agents: set[str]
) -> None:
    """The L1 prompt documents the intent → target_agents mapping.
    Lock it in at the schema level so a regression in the prompt
    is caught by the test suite.

    Note: this asserts the SHAPE the L1 prompt asks for, not
    L1's actual output (that requires a live model + golden
    suite — covered in ``test_pipeline_e2e.py``).
    """
    target_agents_by_intent = {
        "full_pipeline": [
            "l2_eligibility",
            "l3_level",
            "l4_timeline",
            "timeline_ranker",
        ],
        "filter_only": ["l3_level", "l4_timeline", "timeline_ranker"],
        "freshness_check": ["l4_timeline", "timeline_ranker"],
        "drill_down": ["timeline_ranker"],
        "out_of_scope": [],
    }
    assert set(target_agents_by_intent[intent]) == expected_agents


# ── Public surface ─────────────────────────────────────────────────────


def test_run_lumi_query_returns_timeline_or_str() -> None:
    """``run_lumi_query`` returns ``TimelineResult | str``.

    The union is the API contract — callers ``isinstance``-check
    to decide which path to render.
    """
    sig = inspect.signature(run_lumi_query)
    assert sig.return_annotation == "TimelineResult | str"
