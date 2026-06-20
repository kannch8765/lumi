"""FastAPI wrapper for Lumi's ADK app.

Created in Task 27 (Cloud Run deploy). For now this is a placeholder so
the Dockerfile CMD has a valid import target. The actual `app: FastAPI`
construction will use `google.adk.cli.fast_api.get_fast_api_app` once
the L1 Identity Agent (Task 22) is in place.
"""

from __future__ import annotations

# The real FastAPI app is constructed in a later task. This stub exists
# so that `uv run uvicorn app.fast_api_app:app` imports cleanly during
# infrastructure setup (Task 27). Until then, import this module only
# for syntax validation; do not run it as a server.
