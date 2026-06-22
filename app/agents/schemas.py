"""Pydantic schemas for the Lumi agent layer.

The schemas are the single source of truth for the structured data that
flows between Lumi's 4-layer agent pipeline (L1 Identity -> L2 Eligibility
-> L3 Level Filter -> L4 Timeline). They are enforced at the agent
boundary (Layer A L1 + L4) and are also the static type contract used
by the orchestrator (Layer A L3).

See:
- ARCHITECTURE.md section "L1: Identity Agent" — input/output contract
- CONTEXT.md #1 — "Pydantic schemas for all tool inputs"
- CONTEXT.md #12 — "Cross-layer re-validation"
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.mcp_servers.resource_catalog.schemas import ResourceOutput

# ─── L1 router intent types ────────────────────────────────────────────

# Names of the L-layer agents in the pipeline. Used as values for
# IdentityProfile.target_agents. Keep in sync with app/orchestrator.py.
_LUMI_AGENT_NAMES = ("l2_eligibility", "l3_level", "l4_timeline", "timeline_ranker")

# The 5 routing intents L1 can emit. Each intent maps to a specific
# target_agents list (see IdentityProfile.target_agents default_factory).
# See app/agents/l1_identity.py:_L1_INSTRUCTION for the full classification
# rules + examples for each intent.
LumiIntent = Literal[
    "full_pipeline",  # Initial query: L1 → L2 → L3 → L4 → ranker
    "filter_only",  # Follow-up: re-filter existing eligibility results
    "freshness_check",  # Follow-up: re-check last_verified_free on existing picks
    "drill_down",  # Follow-up: details on one specific resource
    "out_of_scope",  # Not about AI/ML learning → apology + 0 sub-agents
]


class EducationLevel(StrEnum):
    """Highest formal education stage of the user.

    Values are stable string identifiers suitable for serialization to
    JSON and for round-tripping through the LLM's structured output.
    """

    HIGH_SCHOOL = "high_school"
    UNDERGRADUATE = "undergraduate"
    GRADUATE = "graduate"
    SELF_TAUGHT = "self_taught"
    PROFESSIONAL = "professional"


class IdentityProfile(BaseModel):
    """Structured user identity extracted from a free-text query.

    Produced by the L1 Identity Agent from the user's raw message. The
    profile is the input to L2 (Eligibility Search) and is never
    persisted to disk (CONTEXT.md #8 — no PII persistence).

    Attributes:
        age: Age in whole years, bounded 5..120 to reject obvious
            prompt-injection payloads (e.g. "age: 99999").
        location: ISO 3166-1 alpha-2 country code, an ISO 3166-2
            subdivision, or a city name. Free-form when the user
            provides a city but not a country. Capped at 100 chars
            (city/country names are short).
        education_level: Coarse-grained education stage. The LLM
            must choose the closest enum value or leave it None.
        languages: ISO 639-1 language codes (e.g. "en", "zh",
            "ja"). Empty list when no language is mentioned.
            Capped at 20 entries (defense against DoS via
            context overflow).
        interests: Lowercased topic tags (e.g. ["nlp",
            "computer_vision", "rl", "agents"]). No PII.
            Capped at 20 entries (same DoS rationale).
        goals: Free-text goal statement — what the user wants to
            learn or build. Preserved verbatim from the model.
            Capped at 500 chars.
        raw_query: The original user message, preserved so later
            layers can re-validate against the source of truth
            (CONTEXT.md #12). Required, 1..2000 chars (CONTEXT.md
            #11 input-length cap, enforced at the schema layer).
        confidence: Extraction confidence in [0.0, 1.0]. The LLM
            is instructed to set this based on how many fields
            were extracted with high confidence.
        intent: Routing decision made by L1. One of the five
            :data:`LumiIntent` values. Drives which downstream
            sub-agents run (full_pipeline / filter_only /
            freshness_check / drill_down / out_of_scope).
            Default "full_pipeline" preserves the original
            behavior (L2 → L3 → L4 → ranker all run) when the
            router fields are not explicitly set, e.g. in tests
            that don't exercise routing.
        target_agents: Names of sub-agents that should actually
            run, derived from `intent`. Each sub-agent's
            `before_agent_callback` checks this list and skips
            itself (returns an empty Content, 0 LLM call) if
            not present. Default = all 4 downstream agents.
            L1 always runs (it is the router, never skipped).
        out_of_scope: True when the query is NOT about AI/ML
            learning. The orchestrator's ranker callback reads
            this and writes `final_user_response` = `apology`
            instead of running the rank, short-circuiting the
            entire pipeline to 1 LLM call (L1 only).
        apology: User-facing reply when `out_of_scope=True`.
            Should be 1-2 sentences, in the user's language,
            explaining Lumi's scope. The ranker callback copies
            this verbatim into `state['final_user_response']`.
    """

    age: int | None = Field(default=None, ge=5, le=120)
    location: str | None = Field(default=None, max_length=100)
    education_level: EducationLevel | None = None
    languages: list[str] = Field(default_factory=list, max_length=20)
    interests: list[str] = Field(default_factory=list, max_length=20)
    goals: str | None = Field(default=None, max_length=500)
    raw_query: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intent: LumiIntent = "full_pipeline"
    target_agents: list[str] = Field(default_factory=lambda: list(_LUMI_AGENT_NAMES))
    out_of_scope: bool = False
    apology: str | None = Field(default=None, max_length=500)


# ─── L2 Eligibility output ─────────────────────────────────────────────


class EligibleResource(BaseModel):
    """A resource that passed L2's eligibility filter.

    ``matched_constraints`` records which identity fields were satisfied
    (e.g. ``["age", "language"]``) so L3 (Level Filter) and the parallel
    output stage can explain *why* this resource survived L2.

    ``rejected_constraints`` records any partial mismatches that did not
    fully exclude the resource (kept for transparency / future audit).
    """

    resource: ResourceOutput
    matched_constraints: list[str] = Field(default_factory=list, max_length=20)
    rejected_constraints: list[str] = Field(default_factory=list, max_length=20)


class EligibilityResult(BaseModel):
    """L2's structured output — resources that match the user's eligibility.

    Returned into session state under ``output_key='eligibility'`` for L3
    (Level Filter) to consume. ``insufficient_data=True`` signals that
    the identity profile was too sparse to filter meaningfully;
    downstream layers should treat that flag as a hint to relax their
    own thresholds. ``reasoning`` is a short, human-readable summary of
    which filters were applied and why.
    """

    eligible: list[EligibleResource] = Field(default_factory=list, max_length=50)
    insufficient_data: bool = False
    reasoning: str = Field(max_length=1000)


# ─── L3 Level Filter output ────────────────────────────────────────────


class SkillLevel(StrEnum):
    """Difficulty level of an AI learning resource.

    The catalog stores ``level`` as a free-form string (``beginner``,
    ``intermediate``, ``advanced``, ``all``). ``ALL_LEVELS`` is the
    agent-side enum value for the catalog's ``"all"`` literal — a
    resource that fits any user regardless of stage.
    """

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    ALL_LEVELS = "all_levels"


class LevelMatch(BaseModel):
    """A single resource after L3's level filter, with its fit score.

    Attributes:
        resource: The catalog entry that survived the filter.
        matched_level: The SkillLevel of the resource as classified
            from the catalog ``level`` field.
        fit_score: How well this resource matches the user's level.
            1.0 for an exact match, 0.7 for an adjacent match,
            0.4 for a stretch match. Bounded to [0.0, 1.0].
    """

    resource: ResourceOutput
    matched_level: SkillLevel
    fit_score: float = Field(ge=0.0, le=1.0)


class LevelFilterResult(BaseModel):
    """L3's structured output — resources matching the user's skill level.

    Drops resources that are too easy (boring) or too hard
    (frustrating) for the user's current level. L4 consumes this as
    its sole input.

    Attributes:
        matches: Surviving resources, each tagged with its
            SkillLevel and a fit_score in [0.0, 1.0].
        user_level: The SkillLevel L3 assigned to the user from
            identity.education_level + interests. ``None`` only when
            L3 could not determine a level — a rare case that L4
            re-validates on every request.
        reasoning: Short justification L4 / the orchestrator can
            surface to the user when the match set is empty.
    """

    matches: list[LevelMatch] = Field(default_factory=list, max_length=50)
    user_level: SkillLevel | None = None
    reasoning: str = Field(default="", max_length=1000)


# ─── L4 Timeline output ────────────────────────────────────────────────


class Urgency(StrEnum):
    """Timeline urgency classification for a single resource.

    Five buckets, ordered from most-to-least time-sensitive. The
    orchestrator (Task 25) sorts the TimelineResult by enum order,
    so do not reorder these values — append-only is the rule.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    STALE = "stale"


class TimelineEntry(BaseModel):
    """A resource after L4's timeline ranking.

    Combines the original catalog record with L4's annotations:
    deadline proximity, freshness signal, and a recommended action
    for the user.

    Field bounds close DoS surfaces flagged by the prompt-injection
    test suite (Task 41-44): ``days_until_deadline`` is bounded to
    +/- 10 years, ``freshness_signal`` and ``recommended_action`` are
    short single-line strings, and ``resource`` is the catalog entry
    (bounded upstream by its own schema).
    """

    resource: ResourceOutput
    urgency: Urgency
    days_until_deadline: int | None = Field(default=None, ge=-3650, le=3650)
    freshness_signal: str = Field(min_length=1, max_length=50)
    recommended_action: str = Field(min_length=1, max_length=200)


class TimelineResult(BaseModel):
    """L4's structured output — resources ranked by timeline urgency.

    The orchestrator (Task 25) reads this as the final pipeline
    payload and feeds it into the parallel output-ranking stage.
    ``ranked`` is capped at 50 entries to bound the parallel output
    stage's memory and latency.
    """

    ranked: list[TimelineEntry] = Field(default_factory=list, max_length=50)
    # ISO 8601 date string (e.g. "2026-06-21"). Stored as ``str`` rather
    # than ``date`` so that ADK's session-state JSON serialization can
    # round-trip the field without needing a custom encoder. The L4
    # agent is allowed to override this (it sometimes uses "today" as
    # a freshness anchor); we accept whatever the LLM sets, but only
    # up to a length cap.
    today: str = Field(default_factory=lambda: date.today().isoformat(), max_length=10)
    reasoning: str = Field(default="", max_length=1000)


# ─── Heuristics for code-side urgency classification ────────────────────

# These thresholds are referenced by both the L4 agent's instructions
# and by any code-side pre-classification (test fixtures, future
# orchestrator pre-sort). Centralized here so L4 stays consistent with
# whatever the orchestrator eventually does.

CRITICAL_THRESHOLD = timedelta(days=14)
HIGH_THRESHOLD = timedelta(days=30)
MEDIUM_THRESHOLD = timedelta(days=90)
STALE_THRESHOLD = timedelta(days=180)


def classify_days_until_deadline(days: int | None) -> Urgency:
    """Map a deadline-proximity integer to an Urgency bucket.

    Args:
        days: Days until deadline. Negative means the deadline is in
            the past. None means no deadline on record.

    Returns:
        Urgency enum value. CRITICAL for <=14 days, HIGH for <=30,
        MEDIUM for <=90, LOW for anything further out (or no deadline),
        and CRITICAL if the deadline has already passed (the user
        missed it — surface this clearly).
    """
    if days is None:
        return Urgency.LOW
    if days < 0:
        return Urgency.CRITICAL
    if days <= CRITICAL_THRESHOLD.days:
        return Urgency.CRITICAL
    if days <= HIGH_THRESHOLD.days:
        return Urgency.HIGH
    if days <= MEDIUM_THRESHOLD.days:
        return Urgency.MEDIUM
    return Urgency.LOW
