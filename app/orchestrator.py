"""Lumi pipeline orchestrator.

This module wires the four L-layer agents (L1 Identity, L2 Eligibility,
L3 Level Filter, L4 Timeline) into an ADK :class:`SequentialAgent` and
adds a final parallel-output ranking step. The orchestrator itself
holds NO tools — it is pure delegation (CONTEXT.md #10 — the tool
whitelist is the kill switch; the orchestrator cannot do anything its
sub-agents cannot do, and it owns no tool surface that could become a
new attack vector).

Pipeline shape::

    lumi_pipeline (SequentialAgent)
    └── l1_identity        -> state['identity']      :class:`IdentityProfile`
    └── l2_eligibility     -> state['eligibility']   :class:`EligibilityResult`
    └── l3_level           -> state['level_filter']  :class:`LevelFilterResult`
    └── l4_timeline        -> state['timeline']      :class:`TimelineResult`
    └── timeline_ranker    -> state['ranked_timeline'] (TimelineResult, sorted)

The first four sub-agents are the 4-layer pipeline (ARCHITECTURE.md
§Agent Pipeline). The fifth is a non-LLM code step — a thin ADK
agent whose ``instruction`` is a no-op and whose ``output_key`` is
written by an ``after_agent_callback`` that runs
:func:`app.ranking.rank_timeline_entries` against ``state['timeline']``.
This keeps the parallel-ranking stage inside the SequentialAgent
boundary so the pipeline remains a single ADK ``agent`` object that
callers can hand to a :class:`~google.adk.runners.Runner`.

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

from app.agents.l1_identity import create_l1_identity_agent
from app.agents.l2_eligibility import create_l2_eligibility_agent
from app.agents.l3_level import create_l3_level_agent
from app.agents.l4_timeline import create_l4_timeline_agent
from app.agents.schemas import TimelineResult
from app.ranking import rank_timeline_entries

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

# Output keys written by each L-layer agent, plus the ranking step.
# Documented here as constants so callers can read them without
# diving into the agent factories.
STATE_KEY_IDENTITY = "identity"
STATE_KEY_ELIGIBILITY = "eligibility"
STATE_KEY_LEVEL_FILTER = "level_filter"
STATE_KEY_TIMELINE = "timeline"
STATE_KEY_RANKED_TIMELINE = "ranked_timeline"


def _coerce_timeline(value: Any) -> TimelineResult | None:
    """Coerce a session-state value back to :class:`TimelineResult`.

    ADK 2.2.0 stores structured ``output_schema`` payloads as plain
    ``dict`` in session state (the ``CallbackContext.state`` view
    shows them as dicts, not typed models). When the ranker callback
    reads ``state['timeline']`` and the orchestrator reads
    ``state['ranked_timeline']``, we need to coerce the dict back
    to the typed model so downstream callers always see the
    contract type.

    Accepts:
    - ``TimelineResult`` instance → returned as-is.
    - ``dict`` matching the schema → validated into ``TimelineResult``.
    - Anything else → ``None`` (caller should fall back to empty).

    Returns ``None`` on validation failure rather than raising so a
    single bad layer doesn't bring down the whole pipeline.
    """
    if isinstance(value, TimelineResult):
        return value
    if isinstance(value, dict):
        try:
            return TimelineResult.model_validate(value)
        except Exception:  # fallback only — see docstring above
            logger.warning(
                "ranker callback: failed to coerce dict to TimelineResult",
                exc_info=True,
            )
            return None
    return None


def _build_ranker_agent() -> LlmAgent:
    """Build the final code-only ranking sub-agent.

    The ranker has no LLM call to make — its job is purely to run
    :func:`app.ranking.rank_timeline_entries` against the L4 output.
    We still wrap it as an :class:`LlmAgent` (with a tiny model and
    a no-op instruction) because ADK ``SequentialAgent`` requires
    every sub-agent to be a ``BaseAgent`` instance, and
    ``LlmAgent`` is the simplest supported shape. The real work is
    done in :func:`_rank_after_agent` via the ``after_agent_callback``
    hook, which writes ``state['ranked_timeline']`` and returns a
    minimal :class:`Content` so the agent surface stays compatible
    with the ADK runner.
    """
    return LlmAgent(
        name="timeline_ranker",
        model="gemini-3.1-flash-lite",  # never invoked — see after_agent_callback
        instruction=(
            "No-op. The real ranking work is performed in code by the "
            "after_agent_callback. Do not emit any text."
        ),
        output_key=STATE_KEY_RANKED_TIMELINE,
        after_agent_callback=_rank_after_agent,
    )


def _rank_after_agent(
    callback_context: Any,
) -> genai_types.Content:
    """Sort ``state['timeline']`` and write ``state['ranked_timeline']``.

    Wired into the ranker sub-agent as its ``after_agent_callback``,
    so ADK invokes this synchronously after the ranker's (no-op)
    LLM call completes. We read ``state['timeline']`` — a
    :class:`TimelineResult` produced by L4 — run
    :func:`app.ranking.rank_timeline_entries`, and write the sorted
    result back to ``state['ranked_timeline']``.

    Args:
        callback_context: ADK-provided callback context. We use it to
            access the live session state. The exact type is opaque
            across ADK versions, so we type it as ``Any`` and access
            ``callback_context.state`` defensively.

    Returns:
        An empty :class:`Content` so the runner can move on to the
        next (or final) sub-agent without parsing any LLM output.
    """
    state = getattr(callback_context, "state", None)
    if state is None:
        logger.warning("ranker callback: no state on callback_context")
        return genai_types.Content(role="model", parts=[])

    raw_timeline = _coerce_timeline(state.get(STATE_KEY_TIMELINE))
    if raw_timeline is None:
        logger.warning(
            "ranker callback: state['%s'] is missing or wrong type",
            STATE_KEY_TIMELINE,
        )
        return genai_types.Content(role="model", parts=[])

    ranked = rank_timeline_entries(raw_timeline)
    state[STATE_KEY_RANKED_TIMELINE] = ranked
    logger.debug("ranker callback: sorted %d timeline entries", len(ranked.ranked))
    return genai_types.Content(role="model", parts=[])


def create_lumi_pipeline(
    model: str = DEFAULT_PIPELINE_MODEL,
) -> SequentialAgent:
    """Factory for the full Lumi pipeline.

    Returns an ADK :class:`SequentialAgent` (``name='lumi_pipeline'``)
    that runs L1 → L2 → L3 → L4 → ranker in order. The first four
    sub-agents are the L-layer agents from :mod:`app.agents`; the
    fifth is the code-only ranker from
    :func:`_build_ranker_agent`.

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
        A :class:`SequentialAgent` named ``"lumi_pipeline"`` with five
        sub-agents in execution order: L1, L2, L3, L4, ranker.
    """
    sub_agents: list[LlmAgent] = [
        create_l1_identity_agent(model=model),
        create_l2_eligibility_agent(model=model),
        create_l3_level_agent(model=model),
        create_l4_timeline_agent(model=model),
        _build_ranker_agent(),
    ]
    return SequentialAgent(
        name="lumi_pipeline",
        sub_agents=sub_agents,
    )


async def run_lumi_query(query: str) -> TimelineResult:
    """Run a single query through the full Lumi pipeline.

    Convenience wrapper for the most common caller pattern: build
    the pipeline, build an in-memory session, hand the user's
    ``query`` to the runner as the user-role message, then read the
    final ranked :class:`TimelineResult` out of session state.

    The user's ``query`` is delivered to L1 as the conversation's
    user message — NOT as a tool parameter and NOT via session
    state. L1's prompt reads it from the conversation context, so
    this is the cleanest path that keeps L1 tool-free.

    Args:
        query: The user's free-text request (e.g. ``"I'm a CS
            undergrad in Brazil, want to learn LLMs"``).

    Returns:
        The final ranked :class:`TimelineResult`. If any layer
        errored or the pipeline never wrote ``state['timeline']``,
        an empty :class:`TimelineResult` is returned so callers
        always receive a structured payload.
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

    # Drain the runner's async generator so the post-callback (ranker)
    # actually fires. We do not consume individual events here —
    # callers that need per-layer traces should use ``Runner.run_async``
    # directly.
    async for _event in runner.run_async(
        user_id=DEFAULT_USER_ID,
        session_id=session.id,
        new_message=content,
    ):
        pass

    final_session = await session_service.get_session(
        app_name=DEFAULT_APP_NAME,
        user_id=DEFAULT_USER_ID,
        session_id=session.id,
    )
    state = final_session.state if final_session is not None else {}

    # Prefer the post-ranker output if the callback fired, otherwise
    # fall back to the L4 output so callers still get a structured
    # payload if ranking was skipped (e.g. L4 returned an empty
    # timeline and the ranker was a no-op).
    #
    # ADK 2.2.0 serializes structured ``output_schema`` payloads to
    # plain ``dict`` before writing them to session state (the
    # ``CallbackContext.state`` view shows them as dicts). We coerce
    # back to the typed model so downstream code (``rank_timeline_entries``,
    # tests, the FastAPI handler) always sees the contract type.
    ranked = state.get(STATE_KEY_RANKED_TIMELINE)
    ranked = _coerce_timeline(ranked)
    if ranked is not None:
        return ranked
    raw = state.get(STATE_KEY_TIMELINE)
    raw = _coerce_timeline(raw)
    if raw is not None:
        return rank_timeline_entries(raw)
    return TimelineResult()
