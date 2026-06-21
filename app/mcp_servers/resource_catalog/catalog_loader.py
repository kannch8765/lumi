"""Catalog loader for the resource-catalog MCP server.

Loads resources/catalog.json exactly once at module import time. The
catalog is then served from an in-memory dict for O(1) lookups by id
and an in-memory list for full enumeration.

The catalog file is resolved relative to this module's location, with
a fallback for running tests from the tests/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

_CATALOG_FILENAME = "catalog.json"

_cached_catalog: dict[str, dict] | None = None


def _catalog_path() -> Path:
    """Locate resources/catalog.json relative to the project root.

    Tries the standard layout (app/mcp_servers/resource_catalog/...
    lives four levels under the project root, so the project root is
    three parents up). Falls back to scanning a few candidate parents
    if the file is not at the first guess.
    """

    candidates: list[Path] = []
    here = Path(__file__).resolve().parent
    for ancestors in range(2, 6):
        candidate = here.parents[ancestors - 1] / "resources" / _CATALOG_FILENAME
        candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    msg = (
        f"Could not locate resources/{_CATALOG_FILENAME}. "
        f"Tried: {[str(c) for c in candidates]}"
    )
    raise FileNotFoundError(msg)


def _load_from_disk() -> dict[str, dict]:
    """Read catalog.json from disk and index by id."""

    path = _catalog_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"Expected catalog.json to contain a list, got {type(raw).__name__}"
        raise TypeError(msg)
    indexed: dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            indexed[entry_id] = entry
    return indexed


def _get_catalog() -> dict[str, dict]:
    """Return the cached catalog, loading it on first access."""

    global _cached_catalog
    if _cached_catalog is None:
        _cached_catalog = _load_from_disk()
    return _cached_catalog


def load_catalog() -> dict[str, dict]:
    """Return the full catalog indexed by resource id.

    Returns a reference to the cached dict so callers must not mutate it.
    """

    return _get_catalog()


def get_all_resources() -> list[dict]:
    """Return every catalog resource as a list of dicts.

    Order matches the catalog.json file order so deterministic for tests.
    """

    return list(_get_catalog().values())
