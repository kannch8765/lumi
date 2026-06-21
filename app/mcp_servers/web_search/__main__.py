"""Entrypoint for the Lumi web-search MCP server (Task 21).

CURATED INDEX — not a real-time web search. Updated offline by the
catalog-refresh background job (Task 33). The freshest possible
results are bounded by when the index was last regenerated.

Run this module directly to launch the server as a stdio MCP
subprocess (the standard pattern for ADK integration):

    uv run python -m app.mcp_servers.web_search

It is also importable via the FastMCP ASGI app:

    from app.mcp_servers.web_search.server import mcp
    mcp.run(transport="streamable-http")
"""

from __future__ import annotations

from app.mcp_servers.web_search.server import mcp


def main() -> None:
    """Run the MCP server in stdio mode (default for ADK integration)."""
    mcp.run()


if __name__ == "__main__":
    main()
