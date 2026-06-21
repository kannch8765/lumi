"""Lumi's agent layer (L1-L4).

Each submodule is a factory that builds a single LlmAgent per the
4-layer pipeline defined in ARCHITECTURE.md §Agent Pipeline. The
orchestrator (Task 25) composes them into a sequential pipeline.

Note: For ADK CLI discovery (``adk run app/agents`` / ``adk web`` /
``adk eval``), the ``root_agent`` entry point lives in
``app/agents/agent.py``, NOT here. This package is for the
individual L-layer factories only — keep its import lightweight
(no orchestrator imports at module level).
"""

from __future__ import annotations
