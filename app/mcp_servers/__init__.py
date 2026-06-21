"""Lumi MCP server subpackage.

Houses the FastMCP tool servers that act as the only data boundary
between Lumi's agents and the outside world. The tool whitelist IS the
kill switch (see ARCHITECTURE.md §Two-Layer Control Model).

Subpackages:
    web_search  — curated search index exposing `search_web` (Task 21).
    resource_catalog — curated catalog (Task 20, sibling).
"""
