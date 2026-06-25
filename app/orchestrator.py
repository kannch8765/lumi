"""Lumi pipeline orchestrator.

This module wires the four L-layer agents (L1 Identity, L2 Eligibility,
L3 Level Filter, L4 Timeline + Finalize) into an ADK
:class:`SequentialAgent`. The orchestrator itself holds NO tools —
it is pure delegation (CONTEXT.md #10 — the tool whitelist is the
kill switch; the orchestrator cannot do anything its sub-agents
cannot do, and it owns no tool surface that could become a new
attack vector).

Pipeline shape::

    lumi_pipeline (SequentialAgent)
    └── l1_identity        -> state['identity']              :class:`IdentityProfile`
    └── l2_eligibility     -> state['eligibility']           :class:`EligibilityResult`
    └── l3_level           -> state['level_filter']          :class:`LevelFilterResult`
    └── l4_timeline        -> state['final_recommendation']  :class:`RecommendationResponse`

Refactor 2026-06-24: the former ``timeline_ranker`` (code-only sort)
and ``l5_synthesizer`` (markdown emit) layers were dropped. L4 now
absorbs both responsibilities — it annotates resources by timeline
urgency AND emits the user-facing markdown recommendation in a
single LLM call. The orchestrator dropped two layers (ranker + L5)
and one state key (``ranked_timeline``).

Ask-back pattern
================

Each L-layer (L2/L3/L4) can emit an ``ask_back`` field in its
structured output. For L2 and L3 the field lives on the layer's
native schema (``EligibilityResult.ask_back`` /
``LevelFilterResult.ask_back``). For L4 the field was added to
``RecommendationResponse`` (refactor 2026-06-24) so the same
short-circuit mechanism works. When any layer fires ask_back, the
string is lifted into the flat session-state key
``state['ask_back']`` and subsequent ``before_agent_callback``s
skip their agent (zero LLM calls). ``run_lumi_query`` returns the
``ask_back`` string verbatim.

Injecting the user's raw query
==============================

L1's prompt reads the user's message from the conversation, NOT from
a tool parameter — L1 has no tools by design. Callers therefore pass
the query into the pipeline as the user-role message of the first
``Content`` they hand to ``Runner.run_async``. This keeps the
orchestrator agent itself tool-free (no need for a session-state
forwarder tool) and matches the standard ADK conversation pattern.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import ValidationError as PydanticValidationError

from app.agents.l1_identity import create_l1_identity_agent
from app.agents.l2_eligibility import create_l2_eligibility_agent
from app.agents.l3_level import create_l3_level_agent
from app.agents.l4_timeline import (
    STATE_KEY_FINAL_RECOMMENDATION,
    create_l4_timeline_agent,
)
from app.agents.schemas import (
    IdentityProfile,
    RecommendationResponse,
    TimelineResult,
)

logger = logging.getLogger(__name__)

# Default model for all four L-layer agents. Picked for low latency
# and low cost — the pipeline runs structured extraction + bounded
# filtering, so Flash-tier is sufficient everywhere. Overridable per
# call via ``create_lumi_pipeline(model=...)`` so tests can swap in a
# stub model without touching the default.
DEFAULT_PIPELINE_MODEL = "gemini-3.1-flash-lite"

# Session identifiers used by :func:`run_lumi_query`. The values are
# arbitrary stable strings — they only need to be deterministic so
# callers can introspect / reuse the session if they wish.
DEFAULT_APP_NAME = "lumi"
DEFAULT_USER_ID = "lumi_user"

# Output keys written by each L-layer agent. Documented here as
# constants so callers can read them without diving into the agent
# factories. Note: the former ``STATE_KEY_TIMELINE`` and
# ``STATE_KEY_RANKED_TIMELINE`` constants were removed in the
# 2026-06-24 refactor — L4 now writes ``STATE_KEY_FINAL_RECOMMENDATION``
# directly (no intermediate TimelineResult state).
STATE_KEY_IDENTITY = "identity"
STATE_KEY_ELIGIBILITY = "eligibility"
STATE_KEY_LEVEL_FILTER = "level_filter"
# Written by L1's ``after_agent_callback`` when L1 sets
# ``out_of_scope=True``. Holds the user-facing apology string from
# the L1 router. When this key is set, ``run_lumi_query`` returns the
# string verbatim — the pipeline short-circuits to a single LLM call
# (L1 only).
STATE_KEY_FINAL_USER_RESPONSE = "final_user_response"
# Written by an L-layer's ``after_agent_callback`` when that layer's
# structured output contains a non-empty ``ask_back`` field. Holds
# the user-facing clarification question. Subsequent
# ``before_agent_callback``s read this key and skip their agent (zero
# LLM calls), so the pipeline halts cleanly. ``run_lumi_query``
# returns the string verbatim.
STATE_KEY_ASK_BACK = "ask_back"

# Fallback apology used only when L1 marks the query out_of_scope but
# fails to populate the ``apology`` field. Kept here (not in the L1
# prompt) so a malformed L1 output never causes the pipeline to crash
# or return an empty user response.
DEFAULT_OUT_OF_SCOPE_APOLOGY = (
    "I'm Lumi, a guide for free AI/ML learning resources. "
    "Your question looks outside that scope — try asking about AI, "
    "ML, or learning resources and I'll be glad to help."
)

# Fallback used when an L-layer fires ``ask_back`` but the field is
# empty / whitespace-only. Mirrors ``DEFAULT_OUT_OF_SCOPE_APOLOGY`` —
# defensive default so a malformed L-layer output never produces
# silent failures.
DEFAULT_ASK_BACK_FALLBACK = (
    "Could you share a bit more about your background and what you'd "
    "like to learn? I can tailor recommendations better with more "
    "context."
)


def _coerce_identity(value: Any) -> IdentityProfile | None:
    """Coerce a session-state value back to :class:`IdentityProfile`.

    ADK 2.2.0 stores structured ``output_schema`` payloads as plain
    ``dict`` in session state (the ``CallbackContext.state`` view
    shows them as dicts, not typed models). A future ADK version may
    deliver typed Pydantic models instead. This helper handles both
    shapes — same pattern as ``_coerce_recommendation`` in
    :mod:`app.agents.l4_timeline`.

    Accepts:
    - ``IdentityProfile`` instance → returned as-is.
    - ``dict`` matching the schema → validated into IdentityProfile.
    - Anything else → ``None`` (caller falls back to legacy always-run).

    Returns ``None`` on validation failure rather than raising so a
    single bad layer doesn't bring down the whole pipeline.
    """
    if isinstance(value, IdentityProfile):
        return value
    if isinstance(value, dict):
        try:
            return IdentityProfile.model_validate(value)
        except Exception:  # fallback only — see docstring above
            logger.warning(
                "skip callback: failed to coerce dict to IdentityProfile",
                exc_info=True,
            )
            return None
    return None


def _make_should_i_run_callback(agent_name: str):
    """Build a ``before_agent_callback`` that skips ``agent_name`` when
    it is not listed in ``state['identity']['target_agents']`` OR when
    an earlier L-layer has already fired ``ask_back``.

    The skip mechanism is the structural implementation of L1's routing
    decision (see :class:`app.agents.l1_identity._L1_INSTRUCTION` part B
    and ``IdentityProfile.target_agents``). L1's intent + target_agents
    are written to session state after L1 finishes; this callback reads
    that state and, if the agent is not targeted, returns an empty
    :class:`Content` so ADK's runner treats the sub-agent as a no-op
    — zero LLM calls, zero MCP tool calls.

    The ``ask_back`` short-circuit is layered on top: if any earlier
    L-layer's ``after_agent_callback`` wrote
    ``state[STATE_KEY_ASK_BACK]``, all subsequent ``before_agent_callback``s
    skip their agent. This avoids wasting LLM calls on layers that
    would never reach the user (the ask_back string is the final
    reply).

    Args:
        agent_name: The sub-agent's ``name=`` (must match one of the
            values in ``IdentityProfile.target_agents``, e.g.
            ``"l2_eligibility"``, ``"l3_level"``, or
            ``"l4_timeline"``).

    Returns:
        An async-compatible callable suitable for ADK
        ``LlmAgent.before_agent_callback``. Returns ``None`` to let
        the agent run normally, or an empty :class:`Content` to skip.
    """

    async def _before_agent(callback_context: Any) -> genai_types.Content | None:
        state = getattr(callback_context, "state", None)
        if state is None:
            # No state — be conservative and run the agent. We don't
            # want a missing state to silently bypass the pipeline.
            return None

        # Ask-back short-circuit: if any earlier L-layer (L2/L3/L4)
        # fired ask_back, skip this agent entirely. The question is
        # the final reply; no LLM calls downstream are warranted.
        if state.get(STATE_KEY_ASK_BACK):
            logger.debug(
                "skipping %s: ask_back already pending in state",
                agent_name,
            )
            return genai_types.Content(role="model", parts=[])

        identity = _coerce_identity(state.get(STATE_KEY_IDENTITY))
        # L1 may not have written identity yet (e.g. very early abort),
        # or the stored value may not be a valid IdentityProfile. In any
        # such case, let the agent run — the worst case is the old
        # always-run behavior, never a silent skip.
        if identity is None:
            return None
        target_agents = identity.target_agents
        if agent_name in target_agents:
            return None  # run normally
        # Skip: emit an empty Content so ADK treats the agent as done.
        logger.debug(
            "skipping %s: not in target_agents=%s (L1 intent=%s)",
            agent_name,
            target_agents,
            identity.intent,
        )
        return genai_types.Content(role="model", parts=[])

    return _before_agent


def _make_ask_back_after_agent_callback(layer_output_key: str):
    """Build an ``after_agent_callback`` that lifts ``ask_back`` from
    a layer's structured output into the flat ``state['ask_back']`` key.

    Pattern is parallel to :func:`_make_should_i_run_callback`: a
    factory that closes over the per-layer output_key. The callback
    runs after the L-layer's LLM call completes. If the structured
    output (which ADK persists to ``state[layer_output_key]``) has a
    non-empty ``ask_back`` field, the callback:

    1. Writes the string to ``state[STATE_KEY_ASK_BACK]`` so the
       next ``before_agent_callback`` (for the layer below this one)
       skips that layer.
    2. Returns ``Content(role="model", parts=[Part(text=ask_back)])``
       so the CLI prints the question as that layer's user-visible
       turn.

    If ``ask_back`` is None or empty, the callback returns empty
    ``Content`` and the layer's success path emits no user-visible
    text (only its structured JSON dump, which is the current
    behavior).

    Refactor 2026-06-24: this callback is now wired ONLY to L2 and L3.
    L4 absorbed L5's responsibility and handles its own ask_back
    short-circuit inside ``_l4_finalize_after_agent`` (which also
    surfaces the user-visible markdown). L4 does not need an
    additional ask_back callback because its default
    ``after_agent_callback`` already lifts ask_back into
    ``state['ask_back']``.

    Args:
        layer_output_key: The session-state key where the L-layer's
            structured ``output_schema`` payload is written (e.g.
            ``"eligibility"``, ``"level_filter"``).

    Returns:
        An ``after_agent_callback`` suitable for ADK
        ``LlmAgent.after_agent_callback``.
    """

    def _after_agent(callback_context: Any) -> genai_types.Content:
        state = getattr(callback_context, "state", None)
        if state is None:
            return genai_types.Content(role="model", parts=[])

        layer_value = state.get(layer_output_key)
        if layer_value is None:
            return genai_types.Content(role="model", parts=[])

        # Defensive: ADK may deliver a typed Pydantic model or a plain
        # dict depending on version. Try attribute access first (covers
        # typed models), fall back to .get() (covers dicts).
        ask_back: str | None = None
        if hasattr(layer_value, "ask_back"):
            ask_back = getattr(layer_value, "ask_back", None)
        elif isinstance(layer_value, dict):
            ask_back = layer_value.get("ask_back")

        if not isinstance(ask_back, str) or not ask_back.strip():
            return genai_types.Content(role="model", parts=[])

        # Defensive fallback: never let an empty / whitespace-only
        # ask_back collapse the pipeline to silence.
        text = ask_back.strip() or DEFAULT_ASK_BACK_FALLBACK
        state[STATE_KEY_ASK_BACK] = text
        logger.debug(
            "%s callback: ask_back set, short-circuiting pipeline",
            layer_output_key,
        )
        # Surface the question as the layer's user-visible turn.
        return genai_types.Content(
            role="model",
            parts=[genai_types.Part(text=text)],
        )

    return _after_agent


def _make_l1_after_agent_callback():
    """Build L1's ``after_agent_callback`` that surfaces the apology
    on the OOS path BEFORE any downstream skip decision.

    When L1 marks a query as ``out_of_scope``, the
    ``IdentityProfile.target_agents`` list is ``[]`` — so every
    downstream agent's ``before_agent_callback`` skips itself with
    zero LLM calls. Previously the apology lived in the ranker's
    ``after_agent_callback``, but the ranker is itself skipped on the
    OOS path (``timeline_ranker`` is not in ``target_agents``), so the
    final-user-response key was never written. L1's callback fires
    unconditionally (L1 is the router — it always runs), making it
    the right place to write the apology.

    Returns ``None`` so L1's structured ``IdentityProfile`` output
    surfaces as the user-visible turn (the markdown L1 emits is
    the apology — no override).
    """

    def _after_agent(callback_context: Any) -> genai_types.Content | None:
        state = getattr(callback_context, "state", None)
        if state is None:
            return None
        identity = _coerce_identity(state.get(STATE_KEY_IDENTITY))
        if identity is None or not identity.out_of_scope:
            return None  # in-scope — let downstream agents run normally
        apology = identity.apology
        # Defensive fallback: never let a missing apology collapse the
        # pipeline to an empty user reply. The L1 prompt requires the
        # field, but we don't want a schema bug to surface as silence.
        if not isinstance(apology, str) or not apology.strip():
            apology = DEFAULT_OUT_OF_SCOPE_APOLOGY
        state[STATE_KEY_FINAL_USER_RESPONSE] = apology
        logger.debug(
            "L1 after_agent_callback: out_of_scope short-circuit, "
            "wrote %d-char apology to state['%s']",
            len(apology),
            STATE_KEY_FINAL_USER_RESPONSE,
        )
        # Return None so L1's own output is the user-visible turn
        # (don't override with an empty Content).
        return None

    return _after_agent


def create_lumi_pipeline(
    model: str = DEFAULT_PIPELINE_MODEL,
) -> SequentialAgent:
    """Factory for the full Lumi pipeline.

    Returns an ADK :class:`SequentialAgent` (``name='lumi_pipeline'``)
    that runs L1 → L2 → L3 → L4 in order. All four sub-agents are
    the L-layer agents from :mod:`app.agents`. The former
    ``timeline_ranker`` (code-only sort) and ``l5_synthesizer``
    (markdown emit) layers were absorbed into L4 on 2026-06-24 —
    see the refactor plan and the ``refactor/stop-at-l4`` branch.

    The orchestrator itself has NO tools. Per CONTEXT.md #10, the
    tool whitelist is the kill switch — adding a tool here would
    silently expand the attack surface for every L-layer agent in
    the pipeline. Keep this agent tool-free.

    Args:
        model: Gemini model name passed to each L-layer agent.
            Defaults to ``gemini-3.1-flash-lite`` (low-latency, low-cost).
            Override only for testing or for routing specific layers
            to a different model tier via the individual factories.

    Returns:
        A :class:`SequentialAgent` named ``"lumi_pipeline"`` with four
        sub-agents in execution order: L1, L2, L3, L4.
    """
    # L1 always runs — it is the router, never skipped. Its output
    # drives the target_agents list that the callbacks below check.
    # Its ``after_agent_callback`` handles the out-of-scope
    # short-circuit (writes apology to ``state['final_user_response']``
    # BEFORE downstream skip decisions — see
    # :func:`_make_l1_after_agent_callback`). We attach the callback
    # post-construction because ``create_l1_identity_agent`` does not
    # currently expose an ``after_agent_callback`` parameter — keeps
    # the factory backward-compatible with existing callers.
    l1_agent = create_l1_identity_agent(model=model)
    l1_agent.after_agent_callback = _make_l1_after_agent_callback()

    sub_agents: list[LlmAgent] = [
        l1_agent,
        create_l2_eligibility_agent(
            model=model,
            before_agent_callback=_make_should_i_run_callback("l2_eligibility"),
            after_agent_callback=_make_ask_back_after_agent_callback(
                STATE_KEY_ELIGIBILITY
            ),
        ),
        create_l3_level_agent(
            model=model,
            before_agent_callback=_make_should_i_run_callback("l3_level"),
            after_agent_callback=_make_ask_back_after_agent_callback(
                STATE_KEY_LEVEL_FILTER
            ),
        ),
        # L4 Timeline + Finalize — absorbed the former L5 Synthesizer
        # (markdown emit) on 2026-06-24. The factory's default
        # ``after_agent_callback`` (``_l4_finalize_after_agent``)
        # surfaces the markdown as user-visible text, falls back to
        # a code-rendered recommendation if validation fails, AND
        # handles L4's own ask_back short-circuit.
        create_l4_timeline_agent(
            model=model,
            before_agent_callback=_make_should_i_run_callback("l4_timeline"),
        ),
    ]
    return SequentialAgent(
        name="lumi_pipeline",
        sub_agents=sub_agents,
    )


async def run_lumi_query(
    query: str,
) -> TimelineResult | RecommendationResponse | str:
    """Run a single query through the full Lumi pipeline.

    Convenience wrapper for the most common caller pattern: build
    the pipeline, build an in-memory session, hand the user's
    ``query`` to the runner as the user-role message, then read
    the final response out of session state.

    The user's ``query`` is delivered to L1 as the conversation's
    user message — NOT as a tool parameter and NOT via session
    state. L1's prompt reads it from the conversation context, so
    this is the cleanest path that keeps L1 tool-free.

    Short-circuit order (first match wins):

    1. ``state['ask_back']`` — set by L2 / L3 / L4 when that
       layer's structured output contains a non-empty ``ask_back``
       field. Returns the clarification question as a ``str``.
    2. ``state['final_user_response']`` — set by L1's
       ``after_agent_callback`` when L1 marked the query as
       ``out_of_scope``. Returns the apology as a ``str``.
    3. ``state['final_recommendation']`` — set by L4's
       ``output_key`` (was L5's ``output_key`` pre-2026-06-24
       refactor). Returns a :class:`RecommendationResponse`.
    4. Empty :class:`TimelineResult()` — last-resort default so
       callers always receive a structured payload.

    Refactor 2026-06-24: the ``state['ranked_timeline']`` and
    ``state['timeline']`` branches were removed. The ranker is
    gone (L4 emits its own URGENCY-ordered recommendation), and L4
    no longer writes a TimelineResult intermediate (L4 writes
    ``RecommendationResponse`` directly).

    Args:
        query: The user's free-text request (e.g. ``"I'm a CS
            undergrad in Brazil, want to learn LLMs"``).

    Returns:
        One of:
        - A :class:`RecommendationResponse` (markdown + language +
          follow_up) on the happy in-scope path.
        - A ``str`` apology when L1 classified the query as
          ``out_of_scope``, OR a ``str`` clarification question when
          an L-layer fired ``ask_back``.
        - An empty :class:`TimelineResult` as a last-resort
          fallback (defense-in-depth for schema-validation failures
          in :class:`L4 Timeline`).

        The ``str`` variants are discriminated by content (apology
        vs. question) — callers that need to distinguish should
        check ``state`` directly via ``Runner.run_async``.
    """
    pipeline = create_lumi_pipeline()
    session_service = InMemorySessionService()

    session = await session_service.create_session(
        app_name=DEFAULT_APP_NAME,
        user_id=DEFAULT_USER_ID,
        state={},
    )

    # Lazy import — Runner pulls in heavy ADK runtime deps that we
    # want to avoid at module import time so ``create_lumi_pipeline``
    # stays cheap to call from unit tests.
    from google.adk.runners import Runner

    runner = Runner(
        agent=pipeline,
        app_name=DEFAULT_APP_NAME,
        session_service=session_service,
    )

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=query)],
    )

    # Drain the runner's async generator so the post-callbacks (L4's
    # ``_l4_finalize_after_agent``) actually fire. We do not consume
    # individual events here — callers that need per-layer traces
    # should use ``Runner.run_async`` directly.
    #
    # Schema-validation fallback (Bug #7): L4 is a non-deterministic
    # structured-output emitter. When its output fails Pydantic
    # validation, ADK raises a ``ValidationError`` from inside
    # ``run_async``. We catch it here so the caller still gets a
    # structured payload (empty ``TimelineResult`` if state has
    # nothing useful, otherwise whatever survived). Non-validation
    # exceptions are re-raised so genuine bugs surface normally.
    try:
        async for _event in runner.run_async(
            user_id=DEFAULT_USER_ID,
            session_id=session.id,
            new_message=content,
        ):
            pass
    except PydanticValidationError:
        logger.warning(
            "run_lumi_query: layer output schema validation failed, "
            "falling back to TimelineResult",
            exc_info=True,
        )
        # Fall through to the post-pipeline extraction below, which
        # returns whatever ``state['final_recommendation']`` survived
        # (or empty).
    # NOTE: non-ValidationError exceptions intentionally propagate so
    # genuine bugs surface to the caller.

    final_session = await session_service.get_session(
        app_name=DEFAULT_APP_NAME,
        user_id=DEFAULT_USER_ID,
        session_id=session.id,
    )
    state = final_session.state if final_session is not None else {}

    # 1. Ask-back short-circuit: an L-layer (L2/L3/L4) couldn't
    # proceed without more user input. Return the question as a
    # plain ``str`` — same shape as the OOS apology for caller
    # convenience.
    ask_back = state.get(STATE_KEY_ASK_BACK)
    if isinstance(ask_back, str) and ask_back.strip():
        return ask_back

    # 2. Out-of-scope apology short-circuit.
    final_response = state.get(STATE_KEY_FINAL_USER_RESPONSE)
    if isinstance(final_response, str) and final_response.strip():
        return final_response

    # 3. L4 recommendation (preferred on the happy path).
    rec = state.get(STATE_KEY_FINAL_RECOMMENDATION)
    if isinstance(rec, RecommendationResponse):
        return rec
    if isinstance(rec, dict):
        try:
            return RecommendationResponse.model_validate(rec)
        except Exception:
            # Validation failed — fall through to the empty
            # ``TimelineResult`` last-resort below so callers still
            # get a typed payload.
            logger.warning(
                "run_lumi_query: state['final_recommendation'] "
                "failed validation, falling back to empty "
                "TimelineResult",
                exc_info=True,
            )

    # 4. Empty TimelineResult last-resort.
    return TimelineResult()
