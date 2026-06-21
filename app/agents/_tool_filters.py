"""Shared tool-whitelist constants for Lumi's LlmAgent factories.

Per CONTEXT.md #10, the tool whitelist is the kill switch. Every
McpToolset wired to an L2/L3/L4 agent MUST pass ``tool_filter=`` with
the explicit allow-list from this module — never rely on the MCP
server alone to enforce visibility.

Why a shared module: duplicating the tuple across L2/L3/L4 invites
drift (one tuple gets updated, the others don't). A single source of
truth means ``grep`` for any tool name finds one match, and adding a
new tool is a one-line edit.
"""

from __future__ import annotations

# Resource-catalog MCP server (Task 20) exposes exactly three tools.
RESOURCE_CATALOG_TOOL_NAMES: tuple[str, ...] = (
    "search_catalog",
    "get_resource_by_id",
    "list_by_type",
)

# Web-search MCP server (Task 21) exposes exactly one tool.
WEB_SEARCH_TOOL_NAMES: tuple[str, ...] = ("search_web",)
