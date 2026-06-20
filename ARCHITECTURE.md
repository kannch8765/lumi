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

## Two-Layer Control Model (L0–L5)

> **Key principle**: *"If a control lives in the prompt, the LLM can
> ignore it."* Real hard controls live OUTSIDE the agent's conversation
> context — in code, schemas, infrastructure, and developer tooling.
>
> Lumi has **two separate layers of hard controls**, each with its own
> L0–L5 stack, serving different audiences.

### Layer A — Lumi product (protects the **end user**)

These controls govern the deployed Lumi agent when real students use it.

| Level | Control | Mechanism | What it prevents |
|---|---|---|---|
| **L0** Entry | Input rate limit | Per-IP/session token bucket | Abuse / DoS |
| | Request validation | Pydantic on raw input | Type confusion / injection |
| | Ephemeral session | No disk write, lost on exit | PII persistence |
| **L1** Tool whitelist | Tool registration | Only MCP-exposed tools exist | Calling arbitrary tools / URLs |
| | Tool input schema | Pydantic at tool boundary | Wrong-type parameters |
| | Tool output sanitization | Schema + scrubbing | PII leaking into LLM context |
| **L2** MCP server boundary | Resource catalog MCP | Curated static data, LLM can't edit | Hallucinated / fabricated resources |
| | Search MCP | Bounded results, keyword filter | Wandering to random URLs |
| | MCP auth | Only Lumi's agents can call | Third parties calling our MCP |
| **L3** Agent logic | L1 Identity | Profile extracted, Pydantic-validated | Bad profile / type errors |
| | L2 Eligibility | Rules in **code** (geo/age dict), not prompt | Skipping eligibility |
| | L3 Level Filter | Level in catalog metadata, code-queried | Fudging difficulty |
| | L4 Timeline | Pydantic datetime, code-computed deadline | Wrong dates / fake freshness |
| | Pipeline ordering | Orchestrator code forces L1→L2→L3→L4 | Skipping a layer |
| **L4** Model output | Output schema | Final response is structured | Free-text PII leak |
| | Refusal surfacing | LLM refusals shown verbatim to user | Hiding model anomalies |
| | Hallucination guard | Only catalog + search hits returned | LLM fabrication |
| **L5** Deployment / infra | HTTPS only | Cloud Run enforces TLS | MITM |
| | API key in .env | `chmod 600`, gitignored | Key leak |
| | Audit log | Every recommendation recorded, PII-free | Untraceable / PII in logs |
| | Deploy isolation | Cloud Run ≠ dev machine | Dev environment exposure |

### Layer B — Claude coding Lumi (protects the **codebase**)

These controls govern me (Claude) when writing the Lumi code in this
project. They make sure the development process doesn't introduce
vulnerabilities into Layer A.

| Level | Control | Mechanism | What it prevents |
|---|---|---|---|
| **L0** Input boundary | Project CLAUDE.md | Read at session start | Claude going off-topic / touching wrong project |
| | Codebase scope | Only edit `lumi/`, never sibling repos | Modifying `secure-agent-lab` etc. |
| | Commit rules | `git config` + CLAUDE.md | Claude impersonating Antigravity / Claude |
| **L1** Code generation | Pydantic schemas | Required on every tool input | Weak types / bad schemas |
| | Type hints | mypy must pass | Runtime type errors |
| | English comments | Locked in CLAUDE.md | `ゆう` / `宝宝` / 喵 leaking into code |
| | No secrets in code | `.env` + pre-commit catches | Keys in git |
| | No mocks in tests | Outcome-based, locked in CLAUDE.md | False-green / testing the wrong thing |
| **L2** Pre-commit | semgrep secrets | Custom rule, blocks `AIza*` / `AQ.*` | Key commits |
| | ruff / black | Style enforcement | Style drift |
| | pytest gate | Must pass before commit | Regressions / false-green |
| | No co-authored-by AI | CLAUDE.md + commit-msg hook | Claude leaving its name |
| **L3** Code review | Manual user review | Every PR reviewed by ゆう | Architectural drift |
| | Architecture compliance | Cross-check vs ARCHITECTURE.md | Deviating from design |
| | Threat model check | Cross-check vs CONTEXT.md / STRIDE | Missing security boundary |
| **L4** Repo / workspace | Branching | Feature branches, master protected | Mistakenly editing main |
| | .gitignore | `.env` / `.venv` / `artifacts/` | Junk files in git |
| | Test isolation | pytest fixtures, no global state | Test pollution |
| | CHANGELOG | Per-release note | Untraceable changes |
| **L5** Infra | Secrets in .env | `chmod 600` | Keys lying around |
| | Per-project .venv | No shared dependency tree | Dep conflicts / pollution |
| | Pre-commit installed | Each repo, once | Forgotten install |
| | CI/CD (future) | Tests run on push | Break-after-push surprise |

### The bridge — how Layer B choices propagate to Layer A

```
            Layer B (Claude writes code)          Layer A (Lumi runs)
            ───────────────────────────          ──────────────────
            
  Claude writes new tool ───────────────► Tool appears in Lumi's set
       │                                        │
       │         ┌── pre-commit ──┐              │
       ├────────►│  semgrep       │──────────────┤
       │         │  pytest        │  blocks bad  │
       │         │  ruff          │   code from  │
       │         └────────────────┘  reaching    │
       │                              Layer A    │
       │                                        │
  Claude writes Pydantic schema ──────► runtime validation in Layer A
       │                                        │
       │                                        ▼
  Claude writes STRIDE threat model ─► risks explicit, reviewed at L3
```

**Key insights**:

- **Pre-commit IS the handoff** — it doesn't just catch "developer
  mistakes", it stops code that *would become* a runtime vulnerability
  in Layer A. This is the literal "shift left" mechanism.
- **Pydantic schema has dual citizenship** — it's written by Claude
  (Layer B) and enforced at runtime by Lumi (Layer A). The same artifact
  protects in both worlds.
- **STRIDE threat model is shared** — it covers both development-time
  risks (e.g., Claude introducing a vulnerability) AND runtime risks
  (e.g., Lumi hallucinating). One threat model, two consumers.
- **Claude's L1 choices directly determine Layer A's attack surface**:
  if Claude adds a `transfer_money` tool (Layer B), then Lumi *can*
  transfer money (Layer A). The tool whitelist is the most important
  Layer B → Layer A interface.

## Track

Kaggle Capstone: **Agents for Good** — "advancing education" via accessible
information aggregation for students worldwide.

## Status

🚧 **Scaffolding** — design phase, no code yet.