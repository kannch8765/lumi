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
     downstream sub-agent (L2, L3, L4) but NOT to L1
     (the router itself, which must always run).
  5. The L1 callback (``_make_l1_after_agent_callback``) writes
     ``state['final_user_response']`` when ``out_of_scope=True``
     so the OOS path short-circuits to a single LLM call.

Refactor 2026-06-24: pipeline is now 4 layers (L1 → L2 → L3 → L4).
The former ``timeline_ranker`` + ``l5_synthesizer`` were absorbed
into L4 Timeline + Finalize. The intent → target_agents mapping
was updated accordingly.

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
    _coerce_identity,
    _make_l1_after_agent_callback,
    _make_should_i_run_callback,
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
    """Default ``target_agents`` for a fresh ``IdentityProfile`` lists
    every L-layer agent (the L1 → L2 → L3 → L4 chain).

    Refactor 2026-06-24: the chain is now 4 layers (ranker + L5
    absorbed into L4).

    Note: ``target_agents`` is derived from ``intent`` by the
    ``_derive_target_agents_from_intent`` validator. The default
    ``intent`` is ``"full_pipeline"`` whose mapping is the 4-agent
    chain (L2 + L3 + L4).
    """
    profile = IdentityProfile(raw_query="hello")
    assert set(profile.target_agents) == {
        "l2_eligibility",
        "l3_level",
        "l4_timeline",
    }


def test_identity_profile_default_out_of_scope_false() -> None:
    """Default ``out_of_scope=False`` so the OOS short-circuit never
    fires unless L1 explicitly sets it.
    """
    profile = IdentityProfile(raw_query="hello")
    assert profile.out_of_scope is False


def test_identity_profile_default_apology_is_none() -> None:
    """Default ``apology=None`` so the field is optional.

    L1's ``after_agent_callback`` falls back to
    :data:`DEFAULT_OUT_OF_SCOPE_APOLOGY` when L1 omits the apology,
    so a missing apology never collapses the pipeline to silence.
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
                ],
            }
        }
    )
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None


def test_should_i_run_callback_returns_empty_content_when_not_targeted() -> None:
    """The callback returns an empty ``Content`` (= skip) when the
    agent is NOT in ``target_agents``. Zero LLM calls.

    Uses a real ``IdentityProfile`` (typed state) since the orchestrator
    now coerces state['identity'] via ``_coerce_identity`` which
    requires a valid IdentityProfile (raw_query etc.). The validator
    derives ``target_agents`` from intent, so we set
    ``intent="freshness_check"`` to test the freshness_check skip path.
    """
    profile = IdentityProfile(
        raw_query="is the Kaggle one still free?",
        intent="freshness_check",  # type: ignore[arg-type]
    )
    # Validator derives target_agents from intent (freshness_check,
    # refactor 2026-06-24: now ["l4_timeline"] only).
    assert profile.target_agents == ["l4_timeline"]

    ctx = _FakeCallbackContext(state={STATE_KEY_IDENTITY: profile})
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
    """L2/L3/L4 each have a ``before_agent_callback`` so the
    router can skip them; L1 itself has NO callback (the router
    always runs, by design).

    Refactor 2026-06-24: the pipeline is now 4 layers (L1 → L2 →
    L3 → L4); the former ``timeline_ranker`` no longer exists.
    """
    pipeline = create_lumi_pipeline()
    assert isinstance(pipeline, SequentialAgent)
    names_to_callbacks = {
        agent.name: getattr(agent, "before_agent_callback", None)
        for agent in pipeline.sub_agents
    }
    # L1 must NOT have a skip callback — it's the router, always runs.
    assert names_to_callbacks["l1_identity"] is None
    # Every downstream agent MUST have a skip callback.
    for name in ("l2_eligibility", "l3_level", "l4_timeline"):
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


def test_l1_after_agent_callback_writes_apology_when_out_of_scope() -> None:
    """When ``identity.out_of_scope=True``, L1's ``after_agent_callback``
    writes the apology to ``state['final_user_response']`` BEFORE any
    downstream skip decision.

    L1's callback runs unconditionally (L1 always runs as the router).
    On the OOS path every downstream agent's ``before_agent_callback``
    skips itself because ``target_agents=[]``, so L4's callback
    (where the OOS logic used to live via the ranker) is never invoked.
    Moving the short-circuit to L1 guarantees
    ``state['final_user_response']`` is set even when all downstream
    agents are skipped.
    """
    callback = _make_l1_after_agent_callback()
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: IdentityProfile(
                raw_query="plan me a Tokyo trip",
                intent="out_of_scope",  # type: ignore[arg-type]
                out_of_scope=True,
                apology="Lumi only handles AI/ML learning — please rephrase.",
            )
        }
    )
    result = callback(ctx)
    # Callback returns None (does not override L1's own output) so the
    # apology surfaces via L1's user-visible turn.
    assert result is None
    assert ctx.state[STATE_KEY_FINAL_USER_RESPONSE] == (
        "Lumi only handles AI/ML learning — please rephrase."
    )


def test_l1_after_agent_callback_falls_back_to_default_apology_when_missing() -> None:
    """If L1 sets ``out_of_scope=True`` but forgets the apology
    text, L1's callback falls back to
    :data:`DEFAULT_OUT_OF_SCOPE_APOLOGY` so the user always gets
    a reply.
    """
    callback = _make_l1_after_agent_callback()
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: IdentityProfile(
                raw_query="plan me a Tokyo trip",
                intent="out_of_scope",  # type: ignore[arg-type]
                out_of_scope=True,
                apology=None,
            )
        }
    )
    callback(ctx)
    assert ctx.state[STATE_KEY_FINAL_USER_RESPONSE] == DEFAULT_OUT_OF_SCOPE_APOLOGY


def test_l1_after_agent_callback_noop_when_in_scope() -> None:
    """The OOS check must NOT fire when ``out_of_scope=False`` —
    L1's callback returns None and does not write
    ``state['final_user_response']``, so the downstream timeline path
    runs normally.
    """
    callback = _make_l1_after_agent_callback()
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: IdentityProfile(
                raw_query="I am a CS undergrad",
                intent="full_pipeline",  # type: ignore[arg-type]
                out_of_scope=False,
            )
        }
    )
    result = callback(ctx)
    assert result is None
    assert STATE_KEY_FINAL_USER_RESPONSE not in ctx.state


def test_l1_after_agent_callback_does_not_affect_when_in_scope() -> None:
    """Refactor 2026-06-24: the former ``test_rank_after_agent_runs_normally_when_in_scope``
    is replaced by this — the ranker no longer exists, so there's no
    ranker callback to test. L1's callback still doesn't touch
    ``state['final_user_response']`` on the in-scope path."""
    callback = _make_l1_after_agent_callback()
    ctx = _FakeCallbackContext(
        state={
            STATE_KEY_IDENTITY: IdentityProfile(
                raw_query="I am a CS undergrad",
                intent="full_pipeline",
                out_of_scope=False,
            )
        }
    )
    result = callback(ctx)
    assert result is None
    # No final_user_response written on the in-scope path.
    assert STATE_KEY_FINAL_USER_RESPONSE not in ctx.state


# ── Intent → target_agents mapping (Task #61) ─────────────────────────


@pytest.mark.parametrize(
    "intent,expected_agents",
    [
        (
            "full_pipeline",
            {"l2_eligibility", "l3_level", "l4_timeline"},
        ),
        (
            "filter_only",
            {"l3_level", "l4_timeline"},
        ),
        (
            "freshness_check",
            {"l4_timeline"},
        ),
        ("drill_down", {"l4_timeline"}),
        ("out_of_scope", set()),
    ],
)
def test_intent_to_target_agents_mapping(
    intent: str, expected_agents: set[str]
) -> None:
    """The L1 prompt documents the intent → target_agents mapping.

    Since the IdentityProfile.model_validator recomputes target_agents
    from intent (single source of truth — see Task #9 plan), this test
    now asserts the validator's output for each intent rather than the
    static mapping literal. A regression in the validator or the
    routing constants is caught here.

    Refactor 2026-06-24: the mapping was simplified — the former
    ``timeline_ranker`` + ``l5_synthesizer`` are gone, so each intent
    now targets fewer agents.
    """
    profile = IdentityProfile(raw_query="hello", intent=intent)  # type: ignore[arg-type]
    assert set(profile.target_agents) == expected_agents


# ── Public surface ─────────────────────────────────────────────────────


def test_run_lumi_query_returns_timeline_or_str() -> None:
    """``run_lumi_query`` returns ``TimelineResult | RecommendationResponse | str``.

    The union is the API contract — callers ``isinstance``-check
    to decide which path to render. ``RecommendationResponse`` is
    emitted by L4 Timeline + Finalize (refactor 2026-06-24 absorbed
    L5 into L4); ``str`` covers both the out-of-scope apology and
    the ask-back clarification path.
    """
    sig = inspect.signature(run_lumi_query)
    assert sig.return_annotation == ("TimelineResult | RecommendationResponse | str")


# ── Validator behavior (Task #9 — intent routing fix) ──────────────────


@pytest.mark.parametrize(
    "intent",
    ["full_pipeline", "filter_only", "freshness_check", "drill_down", "out_of_scope"],
)
def test_validator_derives_target_agents_for_all_five_intents(intent: str) -> None:
    """For each intent, the IdentityProfile validator produces the
    canonical target_agents list — regardless of what L1 emits.

    The validator (``IdentityProfile._derive_target_agents_from_intent``)
    is the single source of truth for the intent → target_agents
    mapping. This test pins down the contract for all 5 intents.
    """
    from app.routing import INTENT_TO_TARGET_AGENTS, LUMI_AGENT_NAMES

    profile = IdentityProfile(raw_query="hello", intent=intent)  # type: ignore[arg-type]
    expected = INTENT_TO_TARGET_AGENTS.get(intent, list(LUMI_AGENT_NAMES))
    assert profile.target_agents == expected


def test_validator_overrides_incorrect_target_agents() -> None:
    """Even if L1 emits target_agents=all_3 with intent='drill_down',
    the validator narrows it to ['l4_timeline'].

    This is the bug class: L1 prompt tells the model to set
    target_agents per intent, but Gemini 3.1 Flash Lite is
    inconsistent for non-OOS intents. The validator makes that
    inconsistency irrelevant.

    Refactor 2026-06-24: drill_down now narrows to ``['l4_timeline']``
    (the chain is 4 layers, no separate ranker / L5).
    """
    from app.routing import LUMI_AGENT_NAMES

    profile = IdentityProfile(
        raw_query="tell me more about fast.ai",
        intent="drill_down",  # type: ignore[arg-type]
        target_agents=list(LUMI_AGENT_NAMES),  # WRONG input — validator must override
    )
    assert profile.target_agents == ["l4_timeline"]


# ── _coerce_identity helper ─────────────────────────────────────────────


def test_coerce_identity_accepts_typed_identityprofile() -> None:
    """_coerce_identity(IdentityProfile_instance) returns the same instance."""
    profile = IdentityProfile(raw_query="hi", intent="full_pipeline")
    result = _coerce_identity(profile)
    assert result is profile  # exact identity, no copy


def test_coerce_identity_accepts_valid_dict() -> None:
    """_coerce_identity({valid dict}) returns a validated IdentityProfile."""
    payload = {
        "raw_query": "I am a CS undergrad in Brazil, want to learn LLMs",
        "intent": "full_pipeline",
        "target_agents": [
            "l2_eligibility",
            "l3_level",
            "l4_timeline",
        ],
    }
    result = _coerce_identity(payload)
    assert isinstance(result, IdentityProfile)
    assert result.intent == "full_pipeline"
    assert result.raw_query == payload["raw_query"]


def test_coerce_identity_returns_none_for_invalid_dict() -> None:
    """_coerce_identity({garbage}) returns None and logs a warning.

    The helper must NOT raise — a single bad layer must not bring
    down the whole pipeline. (Same contract as _coerce_timeline.)
    """
    result = _coerce_identity({"not_a_real_field": "wat", "intent": 99999})
    assert result is None


def test_coerce_identity_returns_none_for_wrong_type() -> None:
    """_coerce_identity(non-dict, non-IdentityProfile) returns None.

    Defensive: protects against an unexpected state value (e.g. a
    string or int accidentally written to state['identity']).
    """
    assert _coerce_identity(42) is None
    assert _coerce_identity("not a profile") is None
    assert _coerce_identity(None) is None


# ── Skip callback with typed state (the bug-class test) ────────────────


def test_should_i_run_callback_skips_with_typed_identity_state() -> None:
    """A typed IdentityProfile in state drives the skip decision
    correctly — this is the test that proves the Pydantic-model
    delivery path works (previously the failing path).

    Refactor 2026-06-24: ``freshness_check`` now skips L2 + L3 and
    runs L4 only (no separate ranker).
    """
    # freshness_check: skip L2 + L3, run L4
    profile = IdentityProfile(
        raw_query="is kaggle still free?", intent="freshness_check"
    )
    ctx = _FakeCallbackContext(state={STATE_KEY_IDENTITY: profile})

    # L2 should be SKIPPED
    l2_cb = _make_should_i_run_callback("l2_eligibility")
    l2_result = asyncio.run(l2_cb(ctx))
    assert isinstance(l2_result, genai_types.Content)
    assert l2_result.parts == []  # empty = skip

    # L4 should RUN
    l4_cb = _make_should_i_run_callback("l4_timeline")
    l4_result = asyncio.run(l4_cb(ctx))
    assert l4_result is None  # None = run


def test_should_i_run_callback_falls_back_to_run_when_coercion_fails() -> None:
    """When state['identity'] is unparseable, the callback returns
    None (run normally) — preserves the legacy always-run contract
    so a transient bad state never silently skips an agent.
    """
    ctx = _FakeCallbackContext(state={STATE_KEY_IDENTITY: {"garbage": True}})
    callback = _make_should_i_run_callback("l2_eligibility")
    result = asyncio.run(callback(ctx))
    assert result is None  # run normally, never a silent skip
