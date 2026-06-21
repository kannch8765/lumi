"""Entrypoint for the resource-catalog MCP server.

Run with: `uv run python -m app.mcp_servers.resource_catalog`
"""

from __future__ import annotations

from app.mcp_servers.resource_catalog.server import mcp

if __name__ == "__main__":
    mcp.run()
