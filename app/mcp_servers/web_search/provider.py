"""Curated search index provider for the Lumi web-search MCP server.

The index is a static JSON file committed to the repo. Each entry
represents a "fresh" free AI learning resource that is NOT yet in
`resources/catalog.json`. The file is regenerated offline by the
catalog-refresh background job (Task 33) and committed via the normal
review process.

SECURITY NOTE
=============
This is a CURATED INDEX, not a real-time web search. It is
deterministic and reviewable, which makes it safe to ship inside the
MCP trust boundary (no indirect-prompt-injection via untrusted
remote content; see threat_model.md §MC2.T.1, §PI.8).

The matching logic is pure-Python keyword scoring (case-insensitive,
word-boundary aware). It does NOT do LLM embedding calls, so the
provider is reproducible and testable without external services.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

# ─── Constants ──────────────────────────────────────────────────────────

# Path to the curated index file, relative to the repo root. The MCP
# server resolves it at import time.
DEFAULT_INDEX_PATH = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "mcp_servers"
    / "web_search"
    / "curated_index.json"
)

# Suspicious-instruction patterns. Any index entry whose `snippet` or
# `title` contains one of these is dropped on load. This is the
# defense-in-depth pass recommended by CONTEXT.md §MCP server output
# is untrusted (rule #11) — even though the index is curated, we
# re-validate on every read.
_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(ignore|disregard|forget)\s+(all|previous|above)", re.IGNORECASE),
    re.compile(r"you are (now )?an? (admin|unrestricted|jailbroken)", re.IGNORECASE),
    re.compile(r"reveal (your|the) (system|hidden) prompt", re.IGNORECASE),
)

# Only https:// URLs are allowed (CONTEXT.md §No arbitrary URL
# browsing). The strictness of the check matches the test_web_search
# boundary case.
_URL_SCHEME = re.compile(r"^https://", re.IGNORECASE)


# ─── Exceptions ─────────────────────────────────────────────────────────


class CuratedIndexError(RuntimeError):
    """Raised when the curated index cannot be loaded or is malformed."""


# ─── Loaders ────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_index(path: Path | None = None) -> list[dict[str, Any]]:
    """Load and validate the curated search index.

    Returns a list of raw dict entries. Each entry is sanitized:
        - Non-https URLs are dropped.
        - Snippets/titles matching instruction patterns are dropped.
        - Entries missing required keys are dropped.

    The result is cached for the process lifetime. The MCP server is
    a long-running subprocess, so the file is loaded once at startup.
    """
    index_path = path or DEFAULT_INDEX_PATH
    if not index_path.is_file():
        raise CuratedIndexError(
            f"Curated search index not found at {index_path}. "
            "Run the catalog-refresh job (Task 33) to regenerate it."
        )

    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CuratedIndexError(
            f"Curated search index at {index_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, list):
        raise CuratedIndexError(
            f"Curated search index must be a JSON array, got {type(raw).__name__}"
        )

    sanitized: list[dict[str, Any]] = []
    required_keys = {"title", "url", "snippet", "source", "date_discovered"}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if not required_keys.issubset(entry):
            continue
        if not _URL_SCHEME.match(str(entry.get("url", ""))):
            continue
        title = str(entry.get("title", ""))
        snippet = str(entry.get("snippet", ""))
        if any(p.search(title) or p.search(snippet) for p in _INSTRUCTION_PATTERNS):
            continue
        sanitized.append(entry)
    return sanitized


def clear_cache() -> None:
    """Reset the module-level cache. Test-only helper."""
    load_index.cache_clear()


# ─── Scoring ────────────────────────────────────────────────────────────

# Match-weights: how strongly a hit in a particular field contributes
# to the relevance score. Title hits are weighted highest because the
# title is the most-curated, most-human-readable signal in the index.
_TITLE_WEIGHT = 1.0
_KEYWORD_WEIGHT = 0.8
_SNIPPET_WEIGHT = 0.5


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokenizer. Splits on non-alphanumerics."""
    return {m.group(0).lower() for m in re.finditer(r"[a-z0-9]+", text)}


def _contains_phrase(haystack_lower: str, query_lower: str) -> bool:
    """True if the query appears as a substring in the haystack."""
    return query_lower in haystack_lower


def score_entry(
    entry: dict[str, Any], query_tokens: set[str], query_raw_lower: str
) -> float:
    """Score one index entry against the query.

    Returns a 0.0-1.0 relevance score. The score is the weighted
    fraction of query tokens that hit each field, normalised against
    the maximum possible score (1.0 = every field has every token).
    """
    if not query_tokens:
        return 0.0

    title_lower = str(entry.get("title", "")).lower()
    snippet_lower = str(entry.get("snippet", "")).lower()
    keywords = {
        str(k).lower()
        for k in entry.get("relevance_keywords", [])
        if isinstance(k, str)
    }
    keyword_set = keywords

    title_tokens = _tokenize(title_lower)
    snippet_tokens = _tokenize(snippet_lower)

    title_hits = sum(1 for tok in query_tokens if tok in title_tokens)
    snippet_hits = sum(1 for tok in query_tokens if tok in snippet_tokens)
    keyword_hits = sum(1 for tok in query_tokens if tok in keyword_set)

    # Phrase match (whole query in field) is a strong boost.
    phrase_boost = 0.0
    if _contains_phrase(title_lower, query_raw_lower):
        phrase_boost += 0.5
    if _contains_phrase(snippet_lower, query_raw_lower):
        phrase_boost += 0.25

    raw_score = (
        title_hits * _TITLE_WEIGHT
        + keyword_hits * _KEYWORD_WEIGHT
        + snippet_hits * _SNIPPET_WEIGHT
        + phrase_boost
    )
    # Max raw score for a query of N tokens: N * (1.0 + 0.8 + 0.5) + 0.5
    max_score = (
        len(query_tokens) * (_TITLE_WEIGHT + _KEYWORD_WEIGHT + _SNIPPET_WEIGHT) + 0.5
    )
    if max_score <= 0:
        return 0.0
    return min(1.0, raw_score / max_score)


# ─── Public API ─────────────────────────────────────────────────────────


def search(
    query: str, max_results: int, *, index_path: Path | None = None
) -> list[dict[str, Any]]:
    """Run the curated-index search and return scored entries.

    Args:
        query: Free-form search query. Must be non-empty.
        max_results: Upper bound on returned results. Caller is
            responsible for clamping to 1..20.
        index_path: Optional override for the index location. Used
            by tests to point at a fixture.

    Returns:
        A list of raw index entries, sorted by relevance descending,
        each augmented with a `relevance_score` float. Empty list on
        no match.
    """
    entries = load_index(index_path)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    query_raw_lower = query.lower()

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        s = score_entry(entry, query_tokens, query_raw_lower)
        if s > 0.0:
            scored.append((s, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    out: list[dict[str, Any]] = []
    for score, entry in scored[:max_results]:
        # Copy so we don't mutate the cached entries.
        item = dict(entry)
        item["relevance_score"] = score
        out.append(item)
    return out
