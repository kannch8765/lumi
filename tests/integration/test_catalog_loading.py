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


def test_all_resources_load() -> None:
    """Catalog has the expected entry count.

    The catalog started with 50 entries. In June 2026 the
    "absolute-beginner pool" was added — 10 explainer-type
    resources for users who have never coded and may not know
    what Python or a command line is. Total: 60.
    """
    resources = get_all_resources()
    assert len(resources) == 60


def test_no_duplicate_ids() -> None:
    catalog = load_catalog()
    ids = list(catalog.keys())
    assert len(ids) == len(set(ids))


def test_explainer_pool_has_at_least_8_entries() -> None:
    """The absolute-beginner "explainer" pool is non-empty.

    L3's detection rule boosts ``fit_score`` for ``type="explainer"``
    resources when the user is a true beginner. If this count drops
    to 0, the rule has nothing to recommend and the L1→L2→L3→L4→L5
    pipeline silently degrades for the most important user segment.
    """
    explainers = [r for r in get_all_resources() if r.get("type") == "explainer"]
    assert len(explainers) >= 8, (
        f"expected >=8 explainer-type resources, got {len(explainers)}"
    )


def test_all_required_fields() -> None:
    for entry in get_all_resources():
        assert entry.get("id"), f"missing id in {entry}"
        assert entry.get("name"), f"missing name in {entry}"
        assert entry.get("type"), f"missing type in {entry}"
        assert entry.get("url"), f"missing url in {entry}"


def test_schema_validation() -> None:
    for entry in get_all_resources():
        ResourceOutput.model_validate(entry)
