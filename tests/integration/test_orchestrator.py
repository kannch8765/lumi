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

Refactor 2026-06-24: the pipeline is now 4 layers (L1 → L2 → L3 →
L4) — the former ``timeline_ranker`` (code-only sort) and
``l5_synthesizer`` (markdown emit) layers were absorbed into L4.
"""

from __future__ import annotations

import inspect

import pytest
from google.adk.agents import LlmAgent, SequentialAgent

from app.orchestrator import (
    DEFAULT_PIPELINE_MODEL,
    STATE_KEY_ELIGIBILITY,
    STATE_KEY_IDENTITY,
    STATE_KEY_LEVEL_FILTER,
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


def test_pipeline_has_four_sub_agents() -> None:
    """The pipeline has exactly four sub-agents: L1, L2, L3, L4.

    Refactor 2026-06-24: the former ``timeline_ranker`` (code-only
    sort) and ``l5_synthesizer`` (markdown emit) layers were
    absorbed into L4 Timeline + Finalize. See the
    ``refactor/stop-at-l4`` branch.
    """
    pipeline = create_lumi_pipeline()
    assert len(pipeline.sub_agents) == 4


def test_pipeline_sub_agents_are_in_correct_order() -> None:
    """Sub-agents appear in the canonical order L1 → L2 → L3 → L4.

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

    Refactor 2026-06-24: L4 writes ``"final_recommendation"``
    (RecommendationResponse) instead of the former
    ``"timeline"`` (TimelineResult) — L4 absorbed L5's emit
    responsibility.
    """
    pipeline = create_lumi_pipeline()
    keys = [agent.output_key for agent in pipeline.sub_agents]
    assert keys == [
        STATE_KEY_IDENTITY,
        STATE_KEY_ELIGIBILITY,
        STATE_KEY_LEVEL_FILTER,
        "final_recommendation",
    ]


def test_pipeline_default_model_is_flash() -> None:
    """The default model constant is the Flash-tier Gemini model."""
    assert DEFAULT_PIPELINE_MODEL == "gemini-3.1-flash-lite"


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


def test_l4_sub_agent_has_after_agent_callback() -> None:
    """The L4 sub-agent has an ``after_agent_callback`` wired in by
    default — that callback surfaces the Pydantic ``markdown`` as
    the user-visible turn and falls back to a code-rendered
    summary if validation fails (refactor 2026-06-24: L4 absorbed
    L5's emit responsibility, so this is where the markdown
    finalize lives now).
    """
    pipeline = create_lumi_pipeline()
    l4 = next(a for a in pipeline.sub_agents if a.name == "l4_timeline")
    callback = l4.after_agent_callback
    assert callback is not None
    assert callable(callback)


def test_pipeline_accepts_model_override() -> None:
    """The factory accepts a model name and threads it through.

    We do not assert the inner agents' model strings — that is
    covered by the per-agent test suites — but we verify that a
    non-default model name is accepted without raising.
    """
    pipeline = create_lumi_pipeline(model="gemini-2.5-pro")
    assert pipeline.name == "lumi_pipeline"
    assert len(pipeline.sub_agents) == 4


# ── Public surface ─────────────────────────────────────────────────────


def test_run_lumi_query_is_callable() -> None:
    """``run_lumi_query`` is exposed as a coroutine function so callers
    can ``await`` it directly from FastAPI / scripts."""
    assert callable(run_lumi_query)
    assert inspect.iscoroutinefunction(run_lumi_query)


def test_run_lumi_query_signature_accepts_single_query_string() -> None:
    """``run_lumi_query`` takes a single ``query: str`` argument.

    Returns one of three types, discriminated by content:
    - :class:`TimelineResult` — structured ranked list (fallback path).
    - :class:`RecommendationResponse` — final user-facing
      recommendation (happy path through L5).
    - ``str`` — apology (out_of_scope) or ask_back clarification
      question (insufficient user info).
    """
    sig = inspect.signature(run_lumi_query)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "query"
    # ``str`` annotation is fine — under ``from __future__ import
    # annotations`` we don't need to resolve the string form.
    assert params[0].annotation == "str"
    # The return union is the API contract — callers ``isinstance``-
    # check to decide which path to render.
    assert sig.return_annotation == ("TimelineResult | RecommendationResponse | str")


# ── ValidationError fallback (Bug #7) ──────────────────────────────────


def test_run_lumi_query_handles_layer_validation_error() -> None:
    """``run_lumi_query`` must NOT propagate a Pydantic ValidationError
    raised by an L-layer's structured output. Instead it logs a
    WARNING and returns a structured ``TimelineResult`` so the caller
    always receives a typed payload (never a raw exception).

    L4 (and occasionally L5) are non-deterministic structured-output
    emitters — sometimes the LLM emits a payload that fails schema
    validation. Without this fallback the entire pipeline crashes
    and the caller sees a raw exception. The orchestrator catches
    ``pydantic.ValidationError`` from inside ``runner.run_async``,
    logs it, and falls through to the post-pipeline extraction,
    which returns an empty ``TimelineResult`` if no state survived.
    """
    import asyncio
    from unittest.mock import patch

    from pydantic import ValidationError as PydanticValidationError

    from app.agents.schemas import TimelineResult

    # Build a fake ValidationError — ``model_validate`` on garbage
    # gives us a real one cheaply.
    try:
        TimelineResult.model_validate({"ranked": "not_a_list"})
    except PydanticValidationError as exc:
        validation_error = exc
    else:
        raise AssertionError("expected ValidationError from model_validate")

    # Patch ``Runner.run_async`` to raise the validation error.
    class _FakeRunner:
        def __init__(self, **_kwargs) -> None:
            pass

        def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            async def _gen():
                if False:
                    yield None  # pragma: no cover — make this an async generator
                raise validation_error

            return _gen()

    # Patch the InMemorySessionService too — the runner is constructed
    # inside ``run_lumi_query`` so we patch ``google.adk.runners.Runner``
    # at the import site.
    captured: dict[str, str] = {}

    class _FakeSession:
        id = "sess-test"

    class _FakeSessionService:
        async def create_session(self, **_kwargs):  # type: ignore[no-untyped-def]
            return _FakeSession()

        async def get_session(self, **_kwargs):  # type: ignore[no-untyped-def]
            # No state survived the failed runner — return empty.
            captured["called"] = "yes"
            return type("_S", (), {"state": {}})()

    with (
        patch("google.adk.runners.Runner", _FakeRunner),
        patch("app.orchestrator.InMemorySessionService", _FakeSessionService),
    ):
        result = asyncio.run(run_lumi_query("anything"))

    # Must NOT have re-raised — should return an empty TimelineResult.
    assert isinstance(result, TimelineResult)
    assert result.ranked == []
    # And the fallback path was exercised (the fake session service
    # got called for the post-pipeline extraction).
    assert captured.get("called") == "yes"


def test_run_lumi_query_reraises_non_validation_exceptions() -> None:
    """Non-ValidationError exceptions from ``runner.run_async`` MUST
    still propagate so genuine bugs (network errors, runtime crashes,
    etc.) surface normally to the caller. Only schema-validation
    failures get the graceful fallback.
    """
    import asyncio
    from unittest.mock import patch

    class _FakeRunner:
        def __init__(self, **_kwargs) -> None:
            pass

        def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            async def _gen():
                if False:
                    yield None  # pragma: no cover
                raise RuntimeError("upstream pipeline boom")

            return _gen()

    class _FakeSession:
        id = "sess-test"

    class _FakeSessionService:
        async def create_session(self, **_kwargs):  # type: ignore[no-untyped-def]
            return _FakeSession()

        async def get_session(self, **_kwargs):  # type: ignore[no-untyped-def]
            return type("_S", (), {"state": {}})()

    with (
        patch("google.adk.runners.Runner", _FakeRunner),
        patch("app.orchestrator.InMemorySessionService", _FakeSessionService),
    ):
        with pytest.raises(RuntimeError, match="upstream pipeline boom"):
            asyncio.run(run_lumi_query("anything"))
