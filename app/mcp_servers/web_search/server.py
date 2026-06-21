"""FastMCP server for Lumi's web-search tool (Task 21).

This server exposes a single `search_web` tool. It is one half of the
L2 MCP boundary in ARCHITECTURE.md §Two-Layer Control Model — the
resource-catalog server (Task 20) is the other half.

SECURITY MODEL
==============
The L4 Timeline agent and the catalog-refresh background job (Task 33)
call this tool to find NEW free AI learning resources beyond the
curated catalog. The tool returns deterministic results from a
committed JSON file (curated_index.json), NOT a live web search.

Why a curated index instead of a real search API?

* **Prompt injection (threat_model.md §PI.8, §MC2.T.1)** — live web
  search is the highest-likelihood indirect-prompt-injection vector
  in Lumi's design. A real search response is untrusted content by
  definition.
* **Determinism / reproducibility** — the demo and tests need
  reproducible results. A live API would make the demo flaky.
* **Free-tier constraints** — Kaggle's free tier and the capstone
  deadline don't permit a paid search API.

The catalog-refresh background job (Task 33) is responsible for
regenerating curated_index.json from real web sources. The job runs
in a sandboxed pipeline, sanitizes the results, and commits a new
version of the file. Until then, this file is reviewed by humans at
ingest time.

TOOL SURFACE
============
The only exposed tool is `search_web`. Per CONTEXT.md §Tool whitelist
is the kill switch, this is intentional: adding a `fetch_url` or
`browse` tool would re-introduce the indirect-prompt-injection
surface that the curated index deliberately avoids.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp_servers.web_search import provider
from app.mcp_servers.web_search.schemas import WebSearchInput, WebSearchResult

# Single FastMCP instance for the server. The `mcp` name is what
# callers see in their tool list — keep it descriptive and stable.
mcp = FastMCP("lumi-web-search")


@mcp.tool()
def search_web(query: WebSearchInput) -> list[WebSearchResult]:
    """Search the curated web-search index for fresh free AI learning resources.

    CURATED INDEX — not a real-time web search. Updated offline by the
    catalog-refresh background job (Task 33). The freshest possible
    results are bounded by when the index was last regenerated.

    Args:
        query: WebSearchInput with `query` (1-200 chars) and
            `max_results` (1-20, default 5).

    Returns:
        A list of WebSearchResult rows sorted by relevance descending.
        Empty list when the index has no matches for the query.

    Security:
        - Results are Pydantic-validated before return (CONTEXT.md
          §MCP server output is untrusted, rule #11).
        - URLs are required to be https:// by the schema.
        - Snippets that match common prompt-injection patterns are
          stripped during index load.
        - This tool never fetches the OUTER URL; the LLM caller is
          expected to render it as a link for the user to visit.
    """
    raw_results = provider.search(query=query.query, max_results=query.max_results)
    # Pydantic-validate every row before it leaves the MCP boundary.
    # This is the runtime enforcement of CONTEXT.md #11.
    return [WebSearchResult.model_validate(row) for row in raw_results]


if __name__ == "__main__":
    # The MCP server is launched as a stdio subprocess by the ADK
    # orchestrator. Running this module directly is only useful for
    # local debugging: it will block waiting on stdio.
    mcp.run()
