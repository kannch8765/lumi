"""Pydantic schemas for the Lumi web-search MCP server.

The schema is the single source of truth for the tool input/output
contract (CONTEXT.md §Pydantic schemas). It is enforced at the MCP
boundary (Layer A L1) and is also the static type contract used by
the agent callers (Layer A L3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class WebSearchInput(BaseModel):
    """Input for the `search_web` tool.

    Attributes:
        query: Free-form search query. Must be non-empty; the LLM
            caller is expected to pass a short topic (e.g. "transformer"
            or "stable diffusion course").
        max_results: Upper bound on the number of results returned.
            Hard cap of 20 keeps MCP responses small (see CONTEXT.md
            §MCP server output is untrusted — 50 KB per response).
    """

    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=5, ge=1, le=20)


class WebSearchResult(BaseModel):
    """One result row from the curated web-search index.

    Attributes:
        title: Human-readable title of the resource.
        url: The OUTER URL (where the resource lives), the only
            piece of location data the LLM should ever see. The MCP
            server does NOT fetch this URL.
        snippet: Short text excerpt from the index entry. The
            orchestrator treats this as a quoted data literal, not
            an instruction (CONTEXT.md #14).
        source: The origin platform of the entry, e.g. "kaggle",
            "github", "huggingface".
        date_discovered: ISO 8601 date (YYYY-MM-DD) when the entry
            was added to the curated index.
        relevance_keywords: Lowercase keyword list used by the
            search provider for keyword matching. Exposed so the
            LLM caller can inspect the match basis, but treated
            as data, never as an instruction.
        relevance_score: 0.0-1.0 match quality. 1.0 = exact keyword
            hit, 0.0 = unrelated.
    """

    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    snippet: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=50)
    date_discovered: str = Field(min_length=10, max_length=10)
    relevance_keywords: list[str] = Field(default_factory=list, max_length=50)
    relevance_score: float = Field(ge=0.0, le=1.0)
