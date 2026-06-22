"""FastAPI wrapper for Lumi's ADK app.

Exposes the Lumi pipeline (L1 -> L2 -> L3 -> L4 -> ranker) as a
FastAPI app with the ADK Web UI, ready for Cloud Run.

Used by:
- Local dev:  uv run uvicorn app.fast_api_app:app --reload
- Cloud Run:  CMD ["uv", "run", "uvicorn", "app.fast_api_app:app", ...]
              (see Dockerfile)

The ``agents_dir`` points at the package containing the ``root_agent``
entry point (see ``app/agents/agent.py`` — Task 56). ADK's
``AgentLoader`` discovers it via the standard ``agent.py + root_agent``
convention, the same shape that ``adk run`` and ``adk web`` use.
"""

from __future__ import annotations

import os

from google.adk.cli.fast_api import get_fast_api_app

# ``agents_dir`` is the package that holds the root_agent entry point
# (app/agents/agent.py — see Task 56). Using ``__file__`` keeps this
# path correct both locally (where __file__ resolves to
# /home/sou/git/lumi/app/fast_api_app.py) and inside the Cloud Run
# container (where __file__ resolves to /code/app/fast_api_app.py).
AGENTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "agents",
)

# web=True enables the ADK browser chat UI at /dev-ui. Required for
# the Kaggle brief's "interactive demo" deliverable (Task 27).
app = get_fast_api_app(agents_dir=AGENTS_DIR, web=True)
