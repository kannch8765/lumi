"""Outcome-based unit tests for :mod:`app.ranking`.

These tests exercise the pure ranking logic without an LLM. They
verify the canonical sort order (urgency → deadline → name), the
no-deadline tiebreak, and the human-readable summary format. All
assertions are on return values, not on internal calls — per
CONTEXT.md #7, no mocks, no ``monkeypatch``.
"""

from __future__ import annotations

from app.agents.schemas import (
    ResourceOutput,
    TimelineEntry,
    TimelineResult,
    Urgency,
)
from app.ranking import explain_ranking, rank_timeline_entries


def _resource(name: str, resource_id: str | None = None) -> ResourceOutput:
    """Build a minimal :class:`ResourceOutput` for test fixtures.

    Only ``id``, ``name``, ``type``, ``url``, and ``description`` are
    required by the schema; everything else defaults. Tests that need
    richer data should construct :class:`ResourceOutput` directly.
    """
    return ResourceOutput(
        id=resource_id or name.lower().replace(" ", "_"),
        name=name,
        type="course",
        url=f"https://example.com/{name.lower().replace(' ', '-')}",
        description="test resource",
    )


def _entry(
    name: str,
    urgency: Urgency,
    days_until_deadline: int | None = None,
    action: str = "Register soon",
) -> TimelineEntry:
    """Build a :class:`TimelineEntry` with sensible defaults."""
    return TimelineEntry(
        resource=_resource(name),
        urgency=urgency,
        days_until_deadline=days_until_deadline,
        freshness_signal="fresh",
        recommended_action=action,
    )


# ── Empty / single-entry edge cases ────────────────────────────────────


def test_empty_timeline_returns_empty_result() -> None:
    """An empty timeline stays empty after ranking."""
    result = TimelineResult(ranked=[], reasoning="nothing matched")
    ranked = rank_timeline_entries(result)
    assert ranked.ranked == []
    assert ranked.reasoning == "nothing matched"


def test_single_entry_timeline_returns_same_entry() -> None:
    """A one-entry timeline is returned unchanged (sorted trivially)."""
    entry = _entry("CS231n", Urgency.HIGH, days_until_deadline=20)
    result = TimelineResult(ranked=[entry])
    ranked = rank_timeline_entries(result)
    assert ranked.ranked == [entry]


# ── Primary sort: urgency ──────────────────────────────────────────────


def test_primary_sort_by_urgency_ascending() -> None:
    """Entries are ordered CRITICAL → HIGH → MEDIUM → LOW → STALE."""
    entries = [
        _entry("Stale Resource", Urgency.STALE),
        _entry("Low Resource", Urgency.LOW),
        _entry("High Resource", Urgency.HIGH),
        _entry("Critical Resource", Urgency.CRITICAL),
        _entry("Medium Resource", Urgency.MEDIUM),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    urgencies = [e.urgency for e in ranked.ranked]
    assert urgencies == [
        Urgency.CRITICAL,
        Urgency.HIGH,
        Urgency.MEDIUM,
        Urgency.LOW,
        Urgency.STALE,
    ]


def test_primary_sort_all_buckets_present() -> None:
    """Each urgency bucket, when present, appears in the canonical order.

    All five entries share the same deadline (None) and so fall
    through to the tertiary name-sort within their urgency bucket —
    but each bucket appears in the canonical CRITICAL → STALE order.
    """
    entries = [
        _entry("a_low", Urgency.LOW),
        _entry("b_critical", Urgency.CRITICAL),
        _entry("c_stale", Urgency.STALE),
        _entry("d_medium", Urgency.MEDIUM),
        _entry("e_high", Urgency.HIGH),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    urgencies = [e.urgency for e in ranked.ranked]
    # The urgency order is canonical and invariant — that is the
    # primary sort we are asserting here.
    assert urgencies == [
        Urgency.CRITICAL,
        Urgency.HIGH,
        Urgency.MEDIUM,
        Urgency.LOW,
        Urgency.STALE,
    ]
    # And the within-bucket name order is alphabetical.
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["b_critical", "e_high", "d_medium", "a_low", "c_stale"]


def test_primary_sort_uses_canonical_urgency_enum_order() -> None:
    """The urgency ranking order matches the canonical enum declaration
    order in :class:`Urgency` (``CRITICAL → HIGH → MEDIUM → LOW → STALE``).

    The orchestrator relies on this invariant — if the enum is ever
    reordered, the primary sort must follow it. We assert this
    independently of any fixture so the test stays useful as the
    enum grows.
    """
    expected = [
        Urgency.CRITICAL,
        Urgency.HIGH,
        Urgency.MEDIUM,
        Urgency.LOW,
        Urgency.STALE,
    ]
    assert list(Urgency) == expected


# ── Secondary sort: deadline ascending ─────────────────────────────────


def test_secondary_sort_by_deadline_ascending() -> None:
    """Within one urgency bucket, the earliest deadline comes first."""
    entries = [
        _entry("FarFuture", Urgency.HIGH, days_until_deadline=28),
        _entry("Soon", Urgency.HIGH, days_until_deadline=15),
        _entry("Midway", Urgency.HIGH, days_until_deadline=22),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["Soon", "Midway", "FarFuture"]


def test_secondary_sort_preserves_urgency_priority() -> None:
    """A HIGH entry with a tiny deadline still beats a CRITICAL entry
    with no deadline — urgency beats deadline proximity."""
    entries = [
        _entry("HighSoon", Urgency.HIGH, days_until_deadline=15),
        _entry("CriticalNoDeadline", Urgency.CRITICAL, days_until_deadline=None),
        _entry("CriticalFar", Urgency.CRITICAL, days_until_deadline=12),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    urgencies = [e.urgency for e in ranked.ranked]
    # CRITICAL bucket first, then HIGH. CRITICAL entries within bucket
    # sorted by deadline (None goes last).
    assert urgencies == [Urgency.CRITICAL, Urgency.CRITICAL, Urgency.HIGH]


# ── None-deadline handling ─────────────────────────────────────────────


def test_none_deadline_sorts_last_in_bucket() -> None:
    """Within one urgency bucket, an entry with days_until_deadline=None
    sorts AFTER every entry that has a finite deadline."""
    entries = [
        _entry("NoDeadline", Urgency.MEDIUM, days_until_deadline=None),
        _entry("Early", Urgency.MEDIUM, days_until_deadline=10),
        _entry("Late", Urgency.MEDIUM, days_until_deadline=80),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["Early", "Late", "NoDeadline"]


def test_multiple_none_deadlines_tertiary_break() -> None:
    """Two ``None``-deadline entries in the same urgency bucket fall
    through to the tertiary (alphabetical) sort."""
    entries = [
        _entry("Zeta", Urgency.LOW, days_until_deadline=None),
        _entry("Alpha", Urgency.LOW, days_until_deadline=None),
        _entry("Mu", Urgency.LOW, days_until_deadline=None),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["Alpha", "Mu", "Zeta"]


# ── Tertiary sort: alphabetical name ───────────────────────────────────


def test_tertiary_sort_by_name_when_urgency_and_deadline_tie() -> None:
    """Same urgency + same deadline → alphabetical by resource name."""
    entries = [
        _entry("Charlie", Urgency.HIGH, days_until_deadline=10),
        _entry("Alpha", Urgency.HIGH, days_until_deadline=10),
        _entry("Bravo", Urgency.HIGH, days_until_deadline=10),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["Alpha", "Bravo", "Charlie"]


def test_tertiary_sort_is_case_insensitive() -> None:
    """Name comparison is case-insensitive (``casefold``)."""
    entries = [
        _entry("beta", Urgency.HIGH, days_until_deadline=10),
        _entry("ALPHA", Urgency.HIGH, days_until_deadline=10),
        _entry("Gamma", Urgency.HIGH, days_until_deadline=10),
    ]
    result = TimelineResult(ranked=entries)
    ranked = rank_timeline_entries(result)
    names = [e.resource.name for e in ranked.ranked]
    assert names == ["ALPHA", "beta", "Gamma"]


# ── Mutation safety ────────────────────────────────────────────────────


def test_ranking_does_not_mutate_input() -> None:
    """The original TimelineResult is returned untouched; ranking
    returns a NEW object with the sorted list."""
    entries = [
        _entry("Z", Urgency.STALE),
        _entry("A", Urgency.CRITICAL),
    ]
    result = TimelineResult(ranked=list(entries))
    original_order = [e.resource.name for e in result.ranked]
    assert original_order == ["Z", "A"]  # pre-condition

    ranked = rank_timeline_entries(result)

    # Input list and identity preserved.
    assert [e.resource.name for e in result.ranked] == ["Z", "A"]
    assert ranked is not result
    assert ranked.ranked is not result.ranked
    # Output is the sorted version.
    assert [e.resource.name for e in ranked.ranked] == ["A", "Z"]


def test_ranking_preserves_metadata() -> None:
    """``today`` and ``reasoning`` survive into the ranked output."""
    from datetime import date

    today = date(2026, 6, 21)
    result = TimelineResult(
        ranked=[_entry("A", Urgency.CRITICAL)],
        today=today,
        reasoning="kept for audit",
    )
    ranked = rank_timeline_entries(result)
    assert ranked.today == today
    assert ranked.reasoning == "kept for audit"


# ── explain_ranking ────────────────────────────────────────────────────


def test_explain_ranking_one_line_per_entry_with_index() -> None:
    """Each line starts with a 1-based index, then name, urgency,
    deadline, and recommended_action."""
    entries = [
        _entry(
            "CS231n",
            Urgency.CRITICAL,
            days_until_deadline=12,
            action="Register this week",
        ),
        _entry(
            "fast.ai",
            Urgency.HIGH,
            days_until_deadline=25,
            action="Enroll soon",
        ),
    ]
    result = TimelineResult(ranked=entries)
    explanation = explain_ranking(result)
    lines = explanation.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("1. ")
    assert lines[1].startswith("2. ")
    assert "CS231n" in lines[0]
    assert "urgency=critical" in lines[0]
    assert "deadline=12d" in lines[0]
    assert "Register this week" in lines[0]
    assert "fast.ai" in lines[1]
    assert "urgency=high" in lines[1]
    assert "deadline=25d" in lines[1]
    assert "Enroll soon" in lines[1]


def test_explain_ranking_empty_timeline_returns_empty_string() -> None:
    """An empty timeline yields an empty string (no spurious blank
    line that would force callers to ``.rstrip()``)."""
    result = TimelineResult(ranked=[])
    assert explain_ranking(result) == ""


def test_explain_ranking_renders_none_deadline_as_na() -> None:
    """``None`` deadlines appear as ``deadline=n/a`` in the summary."""
    entries = [_entry("Ongoing", Urgency.LOW, days_until_deadline=None)]
    result = TimelineResult(ranked=entries)
    explanation = explain_ranking(result)
    assert "deadline=n/a" in explanation
    assert "urgency=low" in explanation
