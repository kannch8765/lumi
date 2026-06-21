"""Outcome-based unit tests for the resource-catalog MCP server.

These tests call the underlying tool functions directly (no MCP
protocol, no mocks). They assert on return values only, per the
Lumi test policy (CONTEXT.md #7 — no mocks, observe return value
and observable state mutation).
"""

from __future__ import annotations

from app.mcp_servers.resource_catalog import server
from app.mcp_servers.resource_catalog.schemas import (
    GetByIdInput,
    ListByTypeInput,
    SearchInput,
)


def test_search_by_keyword() -> None:
    results = server.search_catalog(SearchInput(query="transformer"))
    assert len(results) >= 1
    assert all(
        "transformer" in r.description.lower()
        or "transformer" in r.name.lower()
        or any("transformer" in t.lower() for t in r.tags)
        for r in results
    )


def test_search_by_type_filter() -> None:
    results = server.search_catalog(SearchInput(query="a", types=["course"]))
    assert len(results) >= 1
    assert all(r.type == "course" for r in results)


def test_get_by_id_known() -> None:
    result = server.get_resource_by_id(GetByIdInput(resource_id="cs231n-stanford"))
    assert result is not None
    assert result.id == "cs231n-stanford"


def test_get_by_id_unknown() -> None:
    result = server.get_resource_by_id(GetByIdInput(resource_id="does-not-exist"))
    assert result is None


def test_list_by_type_credit() -> None:
    results = server.list_by_type(ListByTypeInput(resource_type="credit"))
    assert len(results) == 8
    assert all(r.type == "credit" for r in results)


def test_search_respects_max_results() -> None:
    results = server.search_catalog(SearchInput(query="a", max_results=3))
    assert len(results) == 3


def test_search_no_match() -> None:
    results = server.search_catalog(SearchInput(query="xyz123nonexistent"))
    assert results == []


def test_search_case_insensitive() -> None:
    upper = server.search_catalog(SearchInput(query="TRANSFORMER"))
    lower = server.search_catalog(SearchInput(query="transformer"))
    assert len(upper) == len(lower) >= 1
