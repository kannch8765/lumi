"""Lumi pipeline routing constants.

Single source of truth for sub-agent names and the canonical mapping
from L1's routing intents to the downstream sub-agents each intent
targets. Imported by both the L1 prompt (l1_identity.py) and the
orchestrator (orchestrator.py) so they cannot drift.

Why a separate module?
----------------------
``app/agents/schemas.py`` and ``app/orchestrator.py`` form a logical
loop: schemas describes what L1 produces (IdentityProfile.intent +
IdentityProfile.target_agents); orchestrator consumes those fields.
Putting the canonical intent->target_agents mapping in ``schemas.py``
forces ``orchestrator.py`` to import schema internals (the literal
mapping is logically a property of the schema, but orchestrator
should not depend on it for skip-decision logic). Putting it in
``orchestrator.py`` means the L1 prompt (which is data) and the
orchestrator (which is behavior) can drift apart.

This module breaks the loop: both schema and orchestrator import from
here. The ``IdentityProfile.model_validator`` derives ``target_agents``
from ``intent`` using :data:`INTENT_TO_TARGET_AGENTS`; the
orchestrator's skip callback reads ``target_agents`` and trusts it
because the validator guarantees correctness.
"""

from __future__ import annotations

# Sub-agent names that can appear in IdentityProfile.target_agents.
# Order matches the pipeline order in create_lumi_pipeline().
# Refactor 2026-06-24: timeline_ranker + l5_synthesizer dropped — L4
# emits RecommendationResponse directly (URGENCY grouping + markdown
# formatting absorbed from L5's instruction).
LUMI_AGENT_NAMES: tuple[str, ...] = (
    "l2_eligibility",
    "l3_level",
    "l4_timeline",
)

# Canonical intent -> target_agents mapping. Each L1 routing intent
# narrows the set of downstream agents that need to run.
#
# - full_pipeline:    initial query, run L2 → L3 → L4 (4 LLM calls
#                     total counting L1).
# - filter_only:      re-filter existing eligibility results; skip L2.
# - freshness_check:  re-check last_verified_free on existing picks;
#                     skip L2 and L3.
# - drill_down:       user wants details on a specific resource. Only
#                     L4 runs — but with empty L3 matches, L4 will
#                     fire its own ask_back. The orchestrator returns
#                     that as a str.
# - out_of_scope:     no sub-agents; L1's apology is the final reply.
INTENT_TO_TARGET_AGENTS: dict[str, list[str]] = {
    "full_pipeline": [
        "l2_eligibility",
        "l3_level",
        "l4_timeline",
    ],
    "filter_only": ["l3_level", "l4_timeline"],
    "freshness_check": ["l4_timeline"],
    "drill_down": ["l4_timeline"],
    "out_of_scope": [],
}

# Default fallback when intent is unknown. Shouldn't happen — the
# IdentityProfile.intent field is typed as a LumiIntent Literal which
# rejects unknown values at parse time — but defense in depth.
DEFAULT_TARGET_AGENTS: list[str] = list(LUMI_AGENT_NAMES)
