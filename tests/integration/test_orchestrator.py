"""Construction-only tests for :mod:`app.orchestrator`.

The full live pipeline (with the real Gemini model, MCP servers, and
session plumbing) is covered by the golden-scenario suite planned
for Task 26. These tests verify the factory returns the right
``SequentialAgent`` shape — the right name, the right number of
sub-agents in the right order, and the right callables in the
public surface — without spinning up any LLM or MCP subprocess.

Per CONTEXT.md #7 there are no mocks. We assert only on ADK object
shape (type, name, ``output_key``, presence of the callback) so the
tests stay useful even when the agent factories evolve their
internal model wiring.
"""

from __future__ import annotations

import inspect

from google.adk.agents import LlmAgent, SequentialAgent

from app.orchestrator import (
    DEFAULT_PIPELINE_MODEL,
    STATE_KEY_ELIGIBILITY,
    STATE_KEY_IDENTITY,
    STATE_KEY_LEVEL_FILTER,
    STATE_KEY_RANKED_TIMELINE,
    STATE_KEY_TIMELINE,
    create_lumi_pipeline,
    run_lumi_query,
)

# ── Pipeline construction ──────────────────────────────────────────────


def test_create_lumi_pipeline_returns_sequential_agent() -> None:
    """``create_lumi_pipeline`` returns an ADK ``SequentialAgent``."""
    pipeline = create_lumi_pipeline()
    assert isinstance(pipeline, SequentialAgent)


def test_pipeline_name_is_lumi_pipeline() -> None:
    """The pipeline name is the documented identifier ``lumi_pipeline``.

    Locked so the FastAPI app (Task 27) and any logging / tracing
    surface can rely on the name being stable.
    """
    pipeline = create_lumi_pipeline()
    assert pipeline.name == "lumi_pipeline"


def test_pipeline_has_five_sub_agents() -> None:
    """The pipeline has exactly five sub-agents: L1, L2, L3, L4, ranker."""
    pipeline = create_lumi_pipeline()
    assert len(pipeline.sub_agents) == 5


def test_pipeline_sub_agents_are_in_correct_order() -> None:
    """Sub-agents appear in the canonical order L1 → L2 → L3 → L4 → ranker.

    ARCHITECTURE.md §Agent Pipeline mandates the order; if this test
    ever fails, the security model has been silently broken (a
    later agent now runs before an earlier one).
    """
    pipeline = create_lumi_pipeline()
    names = [agent.name for agent in pipeline.sub_agents]
    assert names == [
        "l1_identity",
        "l2_eligibility",
        "l3_level",
        "l4_timeline",
        "timeline_ranker",
    ]


def test_pipeline_sub_agents_are_llm_agents() -> None:
    """Every sub-agent is an ``LlmAgent`` (the supported ADK shape)."""
    pipeline = create_lumi_pipeline()
    for agent in pipeline.sub_agents:
        assert isinstance(agent, LlmAgent)


def test_pipeline_sub_agents_use_documented_output_keys() -> None:
    """Each L-layer agent writes to its documented session-state key.

    Downstream layers (and the orchestrator) read from these keys,
    so they must be stable and explicit.
    """
    pipeline = create_lumi_pipeline()
    keys = [agent.output_key for agent in pipeline.sub_agents]
    assert keys == [
        STATE_KEY_IDENTITY,
        STATE_KEY_ELIGIBILITY,
        STATE_KEY_LEVEL_FILTER,
        STATE_KEY_TIMELINE,
        STATE_KEY_RANKED_TIMELINE,
    ]


def test_pipeline_default_model_is_flash() -> None:
    """The default model constant is the Flash-tier Gemini model."""
    assert DEFAULT_PIPELINE_MODEL == "gemini-2.5-flash"


def test_pipeline_orchestrator_has_no_tools() -> None:
    """The SequentialAgent itself has no tools (pure delegation).

    CONTEXT.md #10 — the tool whitelist is the kill switch. Adding a
    tool to the orchestrator would silently expose it to every
    L-layer sub-agent at runtime. The orchestrator's job is
    ordering + delegation, nothing else.
    """
    pipeline = create_lumi_pipeline()
    # ``SequentialAgent`` exposes ``tools`` via ``BaseAgent`` only when
    # explicitly set; the default is the empty tuple. Either way it
    # must not contain any tool.
    assert not getattr(pipeline, "tools", [])


def test_ranker_sub_agent_has_after_agent_callback() -> None:
    """The ranker sub-agent is wired to a non-trivial
    ``after_agent_callback`` — that callback is what does the real
    ranking work (ARCHITECTURE.md §Parallel Output Stage)."""
    pipeline = create_lumi_pipeline()
    ranker = pipeline.sub_agents[-1]
    assert ranker.name == "timeline_ranker"
    callback = ranker.after_agent_callback
    assert callback is not None
    # The callback must be callable (ADK invokes it on agent completion).
    assert callable(callback)


def test_pipeline_accepts_model_override() -> None:
    """The factory accepts a model name and threads it through.

    We do not assert the inner agents' model strings — that is
    covered by the per-agent test suites — but we verify that a
    non-default model name is accepted without raising.
    """
    pipeline = create_lumi_pipeline(model="gemini-2.5-pro")
    assert pipeline.name == "lumi_pipeline"
    assert len(pipeline.sub_agents) == 5


# ── Public surface ─────────────────────────────────────────────────────


def test_run_lumi_query_is_callable() -> None:
    """``run_lumi_query`` is exposed as a coroutine function so callers
    can ``await`` it directly from FastAPI / scripts."""
    assert callable(run_lumi_query)
    assert inspect.iscoroutinefunction(run_lumi_query)


def test_run_lumi_query_signature_accepts_single_query_string() -> None:
    """``run_lumi_query`` takes a single ``query: str`` argument and
    returns a :class:`TimelineResult`."""
    sig = inspect.signature(run_lumi_query)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "query"
    # ``str`` annotation is fine — under ``from __future__ import
    # annotations`` we don't need to resolve the string form.
    assert params[0].annotation == "str"
    assert sig.return_annotation == "TimelineResult"
