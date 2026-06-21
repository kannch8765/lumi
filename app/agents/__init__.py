"""Lumi's agent layer (L1-L4).

Each submodule is a factory that builds a single LlmAgent per the
4-layer pipeline defined in ARCHITECTURE.md §Agent Pipeline. The
orchestrator (Task 25) composes them into a sequential pipeline.
"""

from __future__ import annotations
