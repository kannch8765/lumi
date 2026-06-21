"""Integration tests for the resource catalog loader.

Asserts the catalog.json file has the expected shape and that every
entry validates against the ResourceOutput Pydantic schema.
"""

from __future__ import annotations

from app.mcp_servers.resource_catalog.catalog_loader import (
    get_all_resources,
    load_catalog,
)
from app.mcp_servers.resource_catalog.schemas import ResourceOutput


def test_all_50_resources_load() -> None:
    resources = get_all_resources()
    assert len(resources) == 50


def test_no_duplicate_ids() -> None:
    catalog = load_catalog()
    ids = list(catalog.keys())
    assert len(ids) == len(set(ids))


def test_all_required_fields() -> None:
    for entry in get_all_resources():
        assert entry.get("id"), f"missing id in {entry}"
        assert entry.get("name"), f"missing name in {entry}"
        assert entry.get("type"), f"missing type in {entry}"
        assert entry.get("url"), f"missing url in {entry}"


def test_schema_validation() -> None:
    for entry in get_all_resources():
        ResourceOutput.model_validate(entry)
