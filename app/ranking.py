"""Parallel output ranking for the Lumi pipeline.

After L4 (Timeline Agent) produces a :class:`TimelineResult`, the
pipeline orchestrator applies this pure ranking logic to sort the
timeline entries by urgency, deadline proximity, and resource name.
The function is pure — no LLM, no I/O, no side effects — so it can
be tested in isolation and reused for the multiple ranking strategies
ARCHITECTURE.md §Parallel Output Stage envisions (by urgency, by
topic, by value, by sequence). Task 25 implements the "by urgency"
strategy; future tasks can add the other three on top of this
foundation.

The sort order is the canonical ordering defined by :class:`Urgency`
(``CRITICAL → HIGH → MEDIUM → LOW → STALE``) plus two tiebreakers:
deadline ascending (None = +Infinity, sorts last within a bucket),
then alphabetical by ``resource.name`` for a stable, deterministic
order across runs.
"""

from __future__ import annotations

from app.agents.schemas import TimelineEntry, TimelineResult, Urgency

# The canonical urgency rank: lower index = higher priority. This must
# match the declaration order in ``app.agents/schemas.py`` so that any
# future enum appendage does not silently reorder the sort.
_URGENCY_RANK: dict[Urgency, int] = {
    Urgency.CRITICAL: 0,
    Urgency.HIGH: 1,
    Urgency.MEDIUM: 2,
    Urgency.LOW: 3,
    Urgency.STALE: 4,
}

# Sentinel for the "no deadline" case — used to push None entries to
# the end of their urgency bucket.
_NO_DEADLINE = float("inf")


def _sort_key(entry: TimelineEntry) -> tuple[int, float, str]:
    """Build the composite sort key for one :class:`TimelineEntry`.

    Returns:
        A 3-tuple ``(urgency_rank, deadline, name)`` suitable for
        ``sorted(..., key=_sort_key)``. ``urgency_rank`` follows
        :data:`_URGENCY_RANK` (CRITICAL first). ``deadline`` is the
        ``days_until_deadline`` value, or ``+Infinity`` when the
        resource has no deadline on record. ``name`` is
        ``resource.name`` lowercased for case-insensitive, stable,
        alphabetical ordering.
    """
    urgency_rank = _URGENCY_RANK[entry.urgency]
    deadline = (
        _NO_DEADLINE
        if entry.days_until_deadline is None
        else float(entry.days_until_deadline)
    )
    name = entry.resource.name.casefold()
    return (urgency_rank, deadline, name)


def rank_timeline_entries(result: TimelineResult) -> TimelineResult:
    """Return a NEW :class:`TimelineResult` with ``ranked`` sorted.

    Sort order (ARCHITECTURE.md §Parallel Output Stage — "by urgency"
    strategy):

      1. Primary — ``urgency`` ascending by :data:`_URGENCY_RANK`
         (CRITICAL first, STALE last).
      2. Secondary — ``days_until_deadline`` ascending. ``None`` is
         treated as ``+Infinity`` so resources with no deadline on
         record sort to the end of their urgency bucket.
      3. Tertiary — ``resource.name`` alphabetical (case-insensitive)
         for deterministic order across runs.

    The original :class:`TimelineResult` is not mutated. A new
    instance is returned so callers can keep the unsorted input for
    audit / debugging.

    Args:
        result: The L4 :class:`TimelineResult` from the pipeline.

    Returns:
        A new :class:`TimelineResult` with the same ``today`` and
        ``reasoning`` fields, and a freshly sorted ``ranked`` list.
    """
    sorted_entries = sorted(result.ranked, key=_sort_key)
    return TimelineResult(
        ranked=sorted_entries,
        today=result.today,
        reasoning=result.reasoning,
    )


def explain_ranking(result: TimelineResult) -> str:
    """Return a one-line-per-entry human-readable ranking summary.

    Each line is ``"{index}. {name} (urgency={urgency}, deadline={N}d,
    action={action})"``. The 1-based ``index`` reflects the sort order
    of ``result.ranked`` — i.e. callers should pass a result that has
    already been run through :func:`rank_timeline_entries` if they
    want the canonical order.

    Args:
        result: The ranked :class:`TimelineResult` (typically the
            output of :func:`rank_timeline_entries`).

    Returns:
        A newline-joined string. Returns an empty string when the
        timeline has no entries (so the caller does not have to
        special-case an empty result).
    """
    lines: list[str] = []
    for index, entry in enumerate(result.ranked, start=1):
        days = entry.days_until_deadline
        deadline_part = f"{days}d" if days is not None else "n/a"
        lines.append(
            f"{index}. {entry.resource.name} "
            f"(urgency={entry.urgency.value}, deadline={deadline_part}, "
            f"action={entry.recommended_action})"
        )
    return "\n".join(lines)
