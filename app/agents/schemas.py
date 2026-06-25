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

from pydantic import BaseModel, Field, field_validator, model_validator

from app.mcp_servers.resource_catalog.schemas import ResourceOutput
from app.routing import LUMI_AGENT_NAMES

# ─── L1 router intent types ────────────────────────────────────────────

# Names of the L-layer agents in the pipeline. Used as values for
# IdentityProfile.target_agents. Re-exported from app.routing for
# back-compat with callers that import the underscore-prefixed name.
_LUMI_AGENT_NAMES = LUMI_AGENT_NAMES

# The 5 routing intents L1 can emit. Each intent maps to a specific
# target_agents list (see IdentityProfile.target_agents default_factory).
# See app/agents/l1_identity.py:_L1_INSTRUCTION for the full classification
# rules + examples for each intent.
LumiIntent = Literal[
    "full_pipeline",  # Initial query: L1 → L2 → L3 → L4
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
            not present. Default = all 3 downstream agents.
            L1 always runs (it is the router, never skipped).
        out_of_scope: True when the query is NOT about AI/ML
            learning. L1's `after_agent_callback` reads this
            and writes `final_user_response` = `apology`,
            short-circuiting the entire pipeline to 1 LLM call
            (L1 only).
        apology: User-facing reply when `out_of_scope=True`.
            Should be 1-2 sentences, in the user's language,
            explaining Lumi's scope. L1's callback copies this
            verbatim into `state['final_user_response']`.
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
    # Recomputed by ``_derive_target_agents_from_intent`` validator below;
    # the default is the full agent list (full_pipeline behavior) but any
    # non-full_pipeline intent overrides it. Never trust the L1-emitted
    # value directly — always read after validation.
    target_agents: list[str] = Field(default_factory=lambda: list(LUMI_AGENT_NAMES))
    out_of_scope: bool = False
    apology: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _derive_target_agents_from_intent(self) -> IdentityProfile:
        """Always recompute target_agents from intent (single source of truth).

        L1's prompt instructs it to populate target_agents per intent, but
        Gemini 3.1 Flash Lite is inconsistent for non-OOS intents — it
        sometimes leaves target_agents at the default (all 5 agents),
        which defeats the orchestrator's skip mechanism. This validator
        treats intent as the single source of truth and overrides any
        target_agents the LLM wrote.

        Falls back to DEFAULT_TARGET_AGENTS for unknown intents (shouldn't
        happen — the LumiIntent Literal blocks it at parse time, but
        defense in depth).
        """
        # Local import to avoid circular-import risk if app.routing ever
        # needs to import from app.agents.schemas.
        from app.routing import DEFAULT_TARGET_AGENTS, INTENT_TO_TARGET_AGENTS

        self.target_agents = INTENT_TO_TARGET_AGENTS.get(
            self.intent,
            DEFAULT_TARGET_AGENTS,
        )
        return self


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
    # ``ask_back`` is a user-facing clarification question. When the
    # L2 layer detects that ``identity`` is too sparse to filter
    # meaningfully (no age, no location, no education_level, no
    # language), it sets this field instead of producing speculative
    # matches. The orchestrator's ``after_agent_callback`` lifts the
    # string into ``state['ask_back']`` so downstream layers (L3/L4/L5)
    # skip themselves and ``run_lumi_query`` returns the question to
    # the caller verbatim. Capped at 500 chars (CONTEXT.md #22) —
    # same budget as ``IdentityProfile.apology``.
    ask_back: str | None = Field(default=None, max_length=500)


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
    # ``ask_back``: L3's user-facing clarification question. When L3
    # cannot infer the user's skill level (no education_level, no
    # goal hint), it sets this field. The orchestrator lifts it into
    # ``state['ask_back']`` and skips downstream layers.
    ask_back: str | None = Field(default=None, max_length=500)


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
    # ``ask_back``: L4's user-facing clarification question. When L4
    # finds no time-sensitive free resources (or the catalog returned
    # zero candidates), it asks the user to broaden the search. Lifted
    # into ``state['ask_back']`` by the orchestrator.
    ask_back: str | None = Field(default=None, max_length=500)


# ─── L4 Final Recommendation output (was: L5 Synthesizer output) ─────
#
# Refactor 2026-06-24: the L5 Synthesizer layer was absorbed into L4
# Timeline. The "final user-facing markdown recommendation" is now L4's
# direct output, written to state['final_recommendation'] instead of
# being emitted by a separate L5 agent. The schema is unchanged
# structurally — L4 still emits markdown + language + follow_up — but
# an additional ``ask_back`` field supports the ask_back short-circuit
# flow that previously fired from L4's TimelineResult.


# Refusal-pattern strings that must never appear in user-facing agent
# output (CONTEXT.md #19 — "no echo of system prompts"). The validator
# on ``RecommendationResponse.markdown`` rejects any string containing
# any of these substrings (case-insensitive).
_REFUSAL_PATTERNS = (
    "system prompt",
    "my instructions",
    "instruction zone",
)


class RecommendationResponse(BaseModel):
    """L4's structured output — the final user-facing recommendation.

    Refactor 2026-06-24: L5 Synthesizer was absorbed into L4. L4 now
    reads the level-filtered resources (``state['level_filter']``)
    plus the user's identity profile (``state['identity']``) and
    emits a natural-language markdown reply grouped by urgency, with
    one line per resource. This schema is the L4 / ADK boundary
    contract — the CLI and FastAPI surfaces render the ``markdown``
    field directly.

    Security guards (CONTEXT.md #18-22, threat_model.md):

    * ``markdown`` is bounded to 3000 chars (DoS via context overflow).
      Nullable so ``ask_back`` can carry a clarification question
      without a placeholder markdown.
    * A refusal-pattern scrub (see ``_REFUSAL_PATTERNS``) rejects any
      string containing "system prompt", "my instructions", or
      "instruction zone" — case-insensitive. Defense against the L4
      LLM echoing its own INSTRUCTION zone into the user reply.
    * ``follow_up`` is optional (a single suggested next question) and
      capped at 200 chars.
    * ``language`` is an ISO 639-1 code, capped at 10 chars (allows
      BCP-47 subtags like ``pt-BR``).
    * ``ask_back`` is a user-facing clarification question. Set when
      L4 needs more info to proceed (e.g., the L3 result is empty).
      Mutually exclusive with ``markdown`` in spirit but the model
      allows either — at least one of ``markdown`` / ``ask_back``
      must be non-empty (enforced by ``_validate_either_field``).

    Attributes:
        markdown: Natural-language user-facing recommendation. Plain
            text / markdown only — no HTML, no JS, no executable
            content. ``None`` is allowed when ``ask_back`` is set.
        language: ISO 639-1 (or BCP-47) language code for the reply.
            Drives client-side rendering (e.g., selecting a voice for
            TTS). Defaults to ``"en"``.
        follow_up: Optional single-sentence follow-up question to
            prompt the user into a follow-up turn (e.g., "Want me to
            filter by deadline?"). ``None`` means L4 has no natural
            follow-up.
        ask_back: Optional clarification question L4 surfaces when it
            cannot produce a useful recommendation. The orchestrator's
            ``_make_ask_back_after_agent_callback`` lifts this into
            ``state['ask_back']`` so downstream layers skip themselves
            and ``run_lumi_query`` returns the string verbatim.
    """

    markdown: str | None = Field(default=None, max_length=3000)
    language: str = Field(default="en", min_length=2, max_length=10)
    follow_up: str | None = Field(default=None, max_length=200)
    ask_back: str | None = Field(default=None, max_length=500)

    @field_validator("markdown")
    @classmethod
    def _scrub_refusal_patterns(cls, v: str | None) -> str | None:
        """Reject strings that echo INSTRUCTION-zone content (CONTEXT.md #19).

        Case-insensitive substring match against ``_REFUSAL_PATTERNS``.
        Raises ``ValueError`` so Pydantic surfaces the violation as a
        schema validation failure — the L4 ``after_agent_callback``
        catches the failure and falls back to a code-rendered
        recommendation built directly from ``state['level_filter']``.
        ``None`` is allowed (the ``ask_back`` path doesn't need
        markdown).
        """
        if v is None:
            return v
        lowered = v.lower()
        for needle in _REFUSAL_PATTERNS:
            if needle in lowered:
                raise ValueError(
                    f"markdown contains forbidden phrase '{needle}' "
                    "(CONTEXT.md #19: do not echo instruction zone)"
                )
        return v

    @model_validator(mode="after")
    def _validate_either_field(self) -> RecommendationResponse:
        """At least one of ``markdown`` or ``ask_back`` must be set.

        The LLM might forget to populate either field; this validator
        surfaces that as a schema failure so the
        ``after_agent_callback`` can fall back to a code-rendered
        response instead of returning empty markdown.
        """
        has_md = bool(self.markdown and self.markdown.strip())
        has_ab = bool(self.ask_back and self.ask_back.strip())
        if not has_md and not has_ab:
            raise ValueError(
                "RecommendationResponse: either `markdown` or `ask_back` "
                "must be non-empty"
            )
        return self


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
