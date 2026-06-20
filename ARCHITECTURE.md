# Lumi — Architecture

> **Mission**: Help students worldwide access free AI learning resources
> (courses, competitions, API credits, GPU resources) by removing
> financial, geographic, and informational barriers.

## Agent Pipeline (4-layer sequential, parallel output)

```
┌────────────────────────────────────────────────────────────────┐
│  USER QUERY                                                     │
│  "I'm a CS undergrad in Brazil, want to learn LLMs"             │
└──────────────────────────┬─────────────────────────────────────┘
                           ↓
              ╔═══════════════════════════╗
              ║  L1: IDENTITY AGENT       ║  ← "Who are you?"
              ║  ─────────────────────── ║
              ║  Output: UserProfile      ║
              ║  { level, location, age,  ║
              ║    goal, language,        ║
              ║    institution,           ║
              ║    constraints }          ║
              ╚═════════════╤═════════════╝
                            ↓
              ╔═══════════════════════════╗
              ║  L2: ELIGIBILITY SEARCH   ║  ← "Can you access this?"
              ║  ─────────────────────── ║
              ║  Filters by:              ║
              ║   - regional restrictions ║
              ║   - age requirements      ║
              ║   - institution rules     ║
              ║  Output: CandidateSet     ║
              ║   (already-eligible only) ║
              ╚═════════════╤═════════════╝
                            ↓
              ╔═══════════════════════════╗
              ║  L3: LEVEL FILTER AGENT   ║  ← "Is this right for you?"
              ║  ─────────────────────── ║
              ║  Drops resources that     ║
              ║  are too easy or too      ║
              ║  hard for the user.       ║
              ║  Output: MatchedSet       ║
              ╚═════════════╤═════════════╝
                            ↓
              ╔═══════════════════════════╗
              ║  L4: TIMELINE AGENT       ║  ← "Is this fresh?"
              ║  ─────────────────────── ║
              ║  Flags deadlines,         ║
              ║  freshness, "closes in    ║
              ║  3 days" labels.          ║
              ║  Output: FreshSet         ║
              ╚═════════════╤═════════════╝
                            ↓
              ╔═══════════════════════════╗
              ║  OUTPUT: RANKED LIST      ║  ← PARALLEL ranking
              ║  ─────────────────────── ║
              ║  Multiple sort strategies ║
              ║  run in parallel:         ║
              ║   - by urgency            ║
              ║   - by topic              ║
              ║   - by value saved        ║
              ║   - by learning sequence  ║
              ╚═══════════════════════════╝
```

### L1: Identity Agent

- **Input**: raw user message (free-form)
- **Output**: `UserProfile` (Pydantic schema)
- **Responsibility**: extract `level`, `location`, `age`, `goal`, `language`, `institution`, `constraints`
- **CANNOT do**:
  - Assume user info without asking
  - Bypass identity verification
  - Store profile beyond session

### L2: Eligibility Search Agent

- **Input**: `UserProfile`
- **Output**: `CandidateSet` — only resources the user CAN access
- **Filters applied**:
  - Geographic restrictions (some Kaggle/competitions are country-restricted)
  - Age requirements (some have 18+ rules)
  - Institution requirements (some need `.edu` email)
  - Language availability
- **CANNOT do**:
  - Actively sign user up
  - Verify eligibility with third parties on user's behalf
  - Bypass geo-restrictions

### L3: Level Filter Agent

- **Input**: `UserProfile` + `CandidateSet`
- **Output**: `MatchedSet` — only resources matching the user's skill level
- **Filters applied**:
  - Prerequisite alignment
  - Difficulty rating vs user's current skill
  - Drops "too easy" (boring) AND "too hard" (frustrating)
- **CANNOT do**:
  - Modify the resource's difficulty
  - Create new content to fill gaps
  - Promise skill progression

### L4: Timeline Agent

- **Input**: `MatchedSet`
- **Output**: `FreshSet` — resources annotated with deadlines and freshness
- **Annotations added**:
  - Submission deadlines for competitions
  - Course start dates
  - "Closes in N days" labels
  - "Last verified free on YYYY-MM-DD" stamps
- **CANNOT do**:
  - Predict the future
  - Guarantee continued availability
  - Reserve seats or queue on behalf of user

## Parallel Output Stage

Multiple ranking strategies can run in parallel and merge:

| Strategy | Question it answers |
|---|---|
| **By urgency** | "What should I do THIS WEEK?" |
| **By topic** | "I want all the LLM resources together" |
| **By value** | "What's the most expensive course I'm avoiding paying for?" |
| **By sequence** | "Teach me in order — first X, then Y" |

The user picks one view, or Lumi shows all four and lets them browse.

## Other Automation (Background Tasks)

These run autonomously without user interaction:

| Task | Frequency | Purpose |
|---|---|---|
| **Catalog refresh** | Weekly | Re-check curated resources are still free (rot detection) |
| **Eligibility re-check** | Monthly | Re-verify geo-restrictions (they can change) |
| **Freshness scan** | Daily | Flag competitions approaching deadline |
| **Feedback loop** | Per session | Collect user ratings → improve matching weights |

These are NOT user-facing. They run as cron-style jobs and update the underlying data.

## Agent Limitations (CANNOT DO — non-negotiable)

These are **hard boundaries** the agent must respect:

- ❌ **Browse arbitrary URLs** — only pre-vetted catalog + sanctioned search API
- ❌ **Process payments** — even if a paid resource is better, agent must not transact
- ❌ **Create accounts** on third-party platforms on the user's behalf
- ❌ **Verify personal eligibility** with external services (SSO, gov IDs, etc.)
- ❌ **Guarantee resources remain free** — explicit "last verified" timestamps
- ❌ **Provide legal/medical/financial/immigration advice** — redirect to qualified humans
- ❌ **Replace qualified counselors or mentors** — Lumi suggests, never prescribes
- ❌ **Store PII beyond session** — ephemeral only, never persisted to disk
- ❌ **Make decisions on behalf of user** — always present options, let user choose

## Security Foundation (Shift-Left Pattern)

Same 5-layer architecture proven in the secure-agent-lab codelab:

| Layer | Mechanism | Protects |
|---|---|---|
| **L1** CONTEXT.md | Paved roads for all agent code | S, T, D at design time |
| **L2** STRIDE skill | Threat model per agent + MCP boundary | T at planning time |
| **L3** TDD Plan Gate | "Security Boundaries & Assertions" required | All (test-first) |
| **L4** pre-commit + semgrep | Blocks secrets at commit time | I (info leakage) |
| **L5** runtime invariants | Pydantic schemas, locks, replay protection | T (runtime safety) |
| **Outer shell** | .gitignore, chmod 600, .env, pytest gate | I + regression |

## Track

Kaggle Capstone: **Agents for Good** — "advancing education" via accessible
information aggregation for students worldwide.

## Status

🚧 **Scaffolding** — design phase, no code yet.