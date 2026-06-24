"""Integration tests for the orchestrator's ask-back callbacks.

Covers two callback factories from :mod:`app.orchestrator`:

  1. :func:`_make_ask_back_after_agent_callback` — lifts ``ask_back``
     from an L-layer's structured output into the flat session-state
     key ``state['ask_back']`` and surfaces it as user-visible text.

  2. :func:`_make_should_i_run_callback` — ``before_agent_callback``
     that skips an L-layer when ``state['ask_back']`` is set (and also
     when the layer is not in L1's ``target_agents``).

These tests use fake callback contexts with a ``.state`` dict. ADK's
real ``CallbackContext`` is opaque across versions, and the
orchestrator code accesses ``state`` defensively via ``getattr``, so
a duck-typed object is sufficient.

Per CONTEXT.md #7 — no mocks of the production code; we exercise the
real factory functions with synthetic state.
"""

from __future__ import annotations

import asyncio

from google.genai import types as genai_types

from app.orchestrator import (
    STATE_KEY_ASK_BACK,
    STATE_KEY_ELIGIBILITY,
    STATE_KEY_IDENTITY,
    _make_ask_back_after_agent_callback,
    _make_should_i_run_callback,
)

# ─── Helpers ────────────────────────────────────────────────────────────


class _FakeCtx:
    """Minimal duck-typed CallbackContext with a mutable state dict."""

    def __init__(self, state: dict | None = None) -> None:
        self.state = state if state is not None else {}


def _run(coro):  # pragma: no cover - thin wrapper
    """Run a coroutine to completion from sync test functions."""

    return asyncio.run(coro)


# ─── _make_ask_back_after_agent_callback ────────────────────────────────


def test_ask_back_callback_writes_state_when_layer_output_has_ask_back() -> None:
    """When ``state['eligibility']['ask_back']`` is set, the callback
    lifts it to ``state['ask_back']`` and returns the question as text."""

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)
    ctx = _FakeCtx({"eligibility": {"ask_back": "share your age"}})

    out = cb(ctx)

    assert ctx.state[STATE_KEY_ASK_BACK] == "share your age"
    assert isinstance(out, genai_types.Content)
    assert len(out.parts) == 1
    assert out.parts[0].text == "share your age"


def test_ask_back_callback_no_write_when_layer_ask_back_is_none() -> None:
    """When the layer's ``ask_back`` is None, no state key is written
    and the returned Content is empty."""

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)
    ctx = _FakeCtx({"eligibility": {}})

    out = cb(ctx)

    assert ctx.state.get(STATE_KEY_ASK_BACK) is None
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_ask_back_callback_no_write_when_ask_back_empty_string() -> None:
    """Empty-string ``ask_back`` is treated as None (no write)."""

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)
    ctx = _FakeCtx({"eligibility": {"ask_back": ""}})

    out = cb(ctx)

    assert ctx.state.get(STATE_KEY_ASK_BACK) is None
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_ask_back_callback_falls_back_when_layer_missing() -> None:
    """No eligibility key in state at all → no write, no Content."""

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)
    ctx = _FakeCtx({})  # no 'eligibility'

    out = cb(ctx)

    assert ctx.state.get(STATE_KEY_ASK_BACK) is None
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_ask_back_callback_uses_default_when_text_empty() -> None:
    """Whitespace-only ``ask_back`` is treated as None (no write).

    The production guard ``not ask_back.strip()`` collapses
    whitespace-only strings to the same path as None, so the
    callback never writes ``state['ask_back']`` in that case. This is
    the defensive behavior — an empty / whitespace ask_back collapses
    to silence rather than writing a meaningless state key.
    """

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)
    ctx = _FakeCtx({"eligibility": {"ask_back": "   "}})

    out = cb(ctx)

    assert ctx.state.get(STATE_KEY_ASK_BACK) is None
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_ask_back_callback_no_state_attribute() -> None:
    """If the callback context has no ``state``, returns empty Content
    without crashing (defensive path)."""

    cb = _make_ask_back_after_agent_callback(STATE_KEY_ELIGIBILITY)

    class _NoStateCtx:
        state = None

    out = cb(_NoStateCtx())
    assert isinstance(out, genai_types.Content)
    assert out.parts == []


# ─── _make_should_i_run_callback ────────────────────────────────────────


def test_should_i_run_callback_skips_when_ask_back_pending() -> None:
    """When ``state['ask_back']`` is set, the callback returns empty
    ``Content`` to skip the agent (zero LLM calls)."""

    cb = _make_should_i_run_callback("l5_synthesizer")
    ctx = _FakeCtx({STATE_KEY_ASK_BACK: "share your age"})

    out = _run(cb(ctx))

    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_should_i_run_callback_runs_normally_when_ask_back_absent() -> None:
    """No ask_back + agent is in target_agents → returns ``None``
    (let the agent run normally)."""

    cb = _make_should_i_run_callback("l5_synthesizer")
    ctx = _FakeCtx(
        {
            STATE_KEY_IDENTITY: {
                "target_agents": [
                    "l2_eligibility",
                    "l3_level",
                    "l4_timeline",
                    "timeline_ranker",
                    "l5_synthesizer",
                ]
            }
        }
    )

    out = _run(cb(ctx))

    # ``None`` means "let the agent run" — ADK's contract.
    assert out is None


def test_should_i_run_callback_skips_when_agent_not_targeted() -> None:
    """If identity lists a different target set, the agent is skipped.

    Uses a typed IdentityProfile with intent="freshness_check" so the
    validator derives ``target_agents=["l4_timeline", "timeline_ranker",
    "l5_synthesizer"]`` (which excludes l2_eligibility + l3_level).
    This mirrors the path live probes A2/A3/A4 took and proves the
    skip fires on typed state.
    """
    from app.agents.schemas import IdentityProfile

    profile = IdentityProfile(
        raw_query="is kaggle still free?",
        intent="freshness_check",
    )
    assert profile.target_agents == [
        "l4_timeline",
        "timeline_ranker",
        "l5_synthesizer",
    ]

    cb = _make_should_i_run_callback("l2_eligibility")
    ctx = _FakeCtx({STATE_KEY_IDENTITY: profile})

    out = _run(cb(ctx))

    assert isinstance(out, genai_types.Content)
    assert out.parts == []


def test_should_i_run_callback_runs_when_no_identity_in_state() -> None:
    """Without identity in state, be conservative and let the agent run
    (worst case = old always-run behavior, never a silent skip)."""

    cb = _make_should_i_run_callback("l5_synthesizer")
    ctx = _FakeCtx({})

    out = _run(cb(ctx))

    assert out is None


def test_should_i_run_callback_runs_when_no_state_attribute() -> None:
    """If the callback context has no ``state``, let the agent run."""

    cb = _make_should_i_run_callback("l5_synthesizer")

    class _NoStateCtx:
        state = None

    out = _run(cb(_NoStateCtx()))
    assert out is None


# ─── Task #9 — typed-state parity tests ────────────────────────────────


def test_should_i_run_callback_skips_with_typed_identity_state() -> None:
    """A typed IdentityProfile in state drives the skip decision
    correctly. Mirrors ``test_should_i_run_callback_skips_when_agent_not_targeted``
    but with a real Pydantic model instance instead of a dict — proves
    the Pydantic-model delivery path works (was previously the
    failing path that probes A2/A3/A4 exposed).
    """
    from app.agents.schemas import IdentityProfile

    profile = IdentityProfile(
        raw_query="is kaggle still free today?",
        intent="freshness_check",
    )
    # Validator (IdentityProfile.model_validator) ensures target_agents
    # is ["l4_timeline", "timeline_ranker", "l5_synthesizer"] for
    # freshness_check (l5 added so L5 actually runs for in-scope queries).
    assert profile.target_agents == [
        "l4_timeline",
        "timeline_ranker",
        "l5_synthesizer",
    ]

    ctx = _FakeCtx({STATE_KEY_IDENTITY: profile})
    cb = _make_should_i_run_callback(
        "l2_eligibility"
    )  # l2 NOT in freshness_check target

    out = _run(cb(ctx))
    assert isinstance(out, genai_types.Content)
    assert out.parts == []  # empty = skip
