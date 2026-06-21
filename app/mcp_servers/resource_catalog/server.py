"""Resource-catalog MCP server.

Exposes three read-only tools over the curated 50-resource catalog.
This is the first MCP server for Lumi; it is the literal "tool whitelist
is the kill switch" boundary from ARCHITECTURE.md §Two-Layer model.

Tools:
    - search_catalog: keyword search across name, description, tags.
    - get_resource_by_id: O(1) lookup by canonical id.
    - list_by_type: filter by resource type (course, credit, ...).

The catalog is loaded once at import time (see catalog_loader). The
Pydantic schemas in schemas.py validate every tool input and shape
every tool output.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp_servers.resource_catalog.catalog_loader import (
    get_all_resources,
    load_catalog,
)
from app.mcp_servers.resource_catalog.schemas import (
    GetByIdInput,
    ListByTypeInput,
    ResourceOutput,
    SearchInput,
)

mcp = FastMCP("resource-catalog")


def _to_resource_output(entry: dict) -> ResourceOutput:
    """Coerce a raw catalog dict into a ResourceOutput, defaulting fields."""

    return ResourceOutput(
        id=entry.get("id", ""),
        name=entry.get("name", ""),
        type=entry.get("type", ""),
        url=entry.get("url", ""),
        level=entry.get("level"),
        language=entry.get("language"),
        prerequisites=list(entry.get("prerequisites") or []),
        geo_restrictions=list(entry.get("geo_restrictions") or []),
        age_requirement=(
            int(entry["age_requirement"])
            if entry.get("age_requirement") is not None
            else None
        ),
        institution_requirement=entry.get("institution_requirement"),
        last_verified_free=entry.get("last_verified_free"),
        tags=list(entry.get("tags") or []),
        description=entry.get("description", ""),
    )


def _matches(entry: dict, query_lower: str) -> bool:
    """Return True if the query substring appears in the searchable fields."""

    name = (entry.get("name") or "").lower()
    description = (entry.get("description") or "").lower()
    tags = " ".join(entry.get("tags") or []).lower()
    return query_lower in name or query_lower in description or query_lower in tags


@mcp.tool()
def search_catalog(query: SearchInput) -> list[ResourceOutput]:
    """Search the curated resource catalog. Read-only.

    Performs case-insensitive substring matching on name, description,
    and tags. Optionally filters by type list and language code.
    """

    query_lower = query.query.lower()
    type_filter = {t.lower() for t in query.types} if query.types else None
    language_filter = query.language.lower() if query.language else None

    results: list[ResourceOutput] = []
    for entry in get_all_resources():
        if not _matches(entry, query_lower):
            continue
        if (
            type_filter is not None
            and (entry.get("type") or "").lower() not in type_filter
        ):
            continue
        if (
            language_filter is not None
            and (entry.get("language") or "").lower() != language_filter
        ):
            continue
        results.append(_to_resource_output(entry))
        if len(results) >= query.max_results:
            break
    return results


@mcp.tool()
def get_resource_by_id(resource_id: GetByIdInput) -> ResourceOutput | None:
    """Fetch one resource by its canonical ID.

    Returns None if the id is not present in the catalog.
    """

    catalog = load_catalog()
    entry = catalog.get(resource_id.resource_id)
    if entry is None:
        return None
    return _to_resource_output(entry)


@mcp.tool()
def list_by_type(resource_type: ListByTypeInput) -> list[ResourceOutput]:
    """List resources of a given type (course, credit, competition, ...)."""

    target = resource_type.resource_type.lower()
    results: list[ResourceOutput] = []
    for entry in get_all_resources():
        if (entry.get("type") or "").lower() != target:
            continue
        results.append(_to_resource_output(entry))
        if len(results) >= resource_type.max_results:
            break
    return results
