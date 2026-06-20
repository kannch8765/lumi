# Claude's Project Memory — Lumi

> This file is for me (Claude) to read when working in this project.
> It is **NOT** documentation for end users — keep it terse and
> project-scoped. For project design, see `ARCHITECTURE.md`.

## What is Lumi?

A multi-agent system that helps students worldwide find free AI learning
resources. Submitted to the Kaggle "AI Agents: Intensive Vibe Coding
Capstone Project", track: **Agents for Good**.

- **Repo**: `https://github.com/kannch8765/lumi` (public, for judges)
- **Deadline**: July 6, 2026 11:59 PM PT
- **Architecture**: 4-layer pipeline (Identity → Eligibility → Level →
  Timeline) + parallel output ranking. See `ARCHITECTURE.md`.

## Identity rules — READ FIRST

The user is **ゆう** (Japanese nickname) in private conversation with me.
In this project — which is **sou**'s public-facing work — the rules are:

1. **NEVER** write `ゆう` in code, comments, commit messages, file
   contents, or documentation. It is a private nickname.
2. **Use** `sou` or `kannch8765` when referring to the project owner in
   any artifact that ships.
3. **The project owner on GitHub is `kannch8765`**. This is the public
   identity for the Kaggle submission.
4. **Personal names from real data** (politicians, public figures,
   etc.) in datasets are fine and stay untouched.

## Commit rules

This is the most important part — judges will look at git history.

- **Author**: `kannch8765 <105340539+kannch8765@users.noreply.github.com>`
- **No impersonation**: never sign commits as "Antigravity", "Claude",
  "AI", or any product/brand. The author is always the human owner.
- **No `Co-Authored-By: Claude`** (or any other AI assistant). The
  human owns the work end-to-end.
- **No `Co-Authored-By: Antigravity`** either — the story "we used
  Antigravity IDE" is told in the Kaggle writeup, not in git metadata.
- **Message style**: lowercase type prefix, then description.
  - `feat: <thing added>`
  - `fix: <thing fixed>`
  - `chore: <maintenance>`
  - `docs: <doc change>`
  - `test: <test change>`
  - `refactor: <code change with no behavior change>`
- **Message body**: explain *why*, not *what*. The diff shows the what.

## Code rules

- **English code comments**. Japanese/Chinese only in conversational
  context with ゆう, never in shipped code.
- **No real names** (ゆう, 宝宝, etc.) in code, comments, log messages,
  or string literals.
- **No secrets in code** — `.env` only, gitignored.
- **Pydantic schemas** for all tool inputs (single source of truth).
- **No mocks in tests** — outcome-based, observe return value + state.
- **Pre-commit must pass** before commit. If semgrep blocks, refactor
  and re-stage.

## Privacy & security

- This is a **public repo**. Assume anything in git history is public.
- The Gemini API key (and any other API key) lives in `.env` (chmod 600,
  gitignored). Never in code, comments, or commit messages.
- Resource catalog may contain real course/competition URLs — that's
  intentional (the product is to surface these). But no user data ever.
- No PII collected or persisted beyond the chat session.

## Architecture ref

See `ARCHITECTURE.md` for:
- The 4-layer pipeline
- What each agent can / cannot do
- The "shift-left" 5-layer security model
- Background automation tasks
- Kaggle submission track + mission

Do not contradict the architecture doc without updating it first.

## Task tracking

Use `TaskCreate` for the 14 capstone tasks (scaffold + 4 agents + 2
MCPs + tests + deploy + video + writeup + submit). Mark `in_progress`
when starting, `completed` when done. Don't add tasks without reason.

## Anti-patterns to avoid

- ❌ Signing as Antigravity, Claude, or any non-human identity.
- ❌ Putting ゆう / 宝宝 / personal nicknames in code or docs.
- ❌ `Co-Authored-By` AI attribution lines.
- ❌ Mocking functions in tests (use outcome-based tests).
- ❌ Hardcoding API keys or secrets anywhere.
- ❌ Modifying files outside `lumi/` (don't touch other repos).
- ❌ Skipping pre-commit hooks with `--no-verify` to "save time".
- ❌ Promising features the agent can't deliver (see "Agent
  Limitations" in `ARCHITECTURE.md`).

## Working style

- Pause and ask before destructive actions (`rm -rf`, force push,
  rewriting history, deleting branches).
- Match ゆう's tone in chat (warm, 喵/宝), but keep code/docs
  professional and English.
- Run tests after every refactor. If they fail, fix or revert — don't
  paper over.
- Record major decisions in the project diary at
  `/home/claude-workspace/diary.md` (date heading + ゆう-facing summary).

## Subagent strategy

Lumi project work benefits from **parallel subagent execution** when
deliverables are independent. Use the Agent tool with
`run_in_background: true` to spawn multiple agents at once.

**When to spawn subagents in parallel:**

- 3+ independent deliverables (e.g., 3 separate docs, 2 different
  MCP servers, 4 different agents)
- Independent research tasks (e.g., curating different data slices)
- Different parts of a feature with no shared state (e.g., separate
  test files for separate agents)

**When NOT to use subagents:**

- Work depends on prior agent output
- Tightly-coupled code (e.g., refactor across multiple files)
- Tasks needing real-time user feedback
- Single trivial file edit (overhead exceeds gain)

**Critical lessons (2026-06-20):**

1. **"可以并行"** — Spawning 3 subagents in parallel ≈ 1 sequential
   agent's wall-clock time. **Saves 60%+** on documentation/data tasks.
   Verified on Lumi Phase 2: CONTEXT.md + STRIDE + catalog.json all
   finished in roughly the time of 1 sequential agent.

2. **Subagent hang diagnosis** — If a subagent seems stuck (no file
   written after 5+ minutes), the most common cause is that it was
   given permissions/tools that don't work in this env. The fix is
   to **constrain the prompt**, not just retry.
   - Symptom of Lumi Agent 2 v1: tried WebSearch/WebFetch, got 400
     errors, never wrote the file
   - Fix: kill + re-spawn with explicit "DO NOT use WebSearch /
     WebFetch" + "Write file directly with Write tool" + "5 min
     target" constraints
   - v2 finished in 252 lines in under 2 minutes

3. **Schema anticipates verification gaps** — When subagents curate
   data, design the schema to handle verification failures gracefully.
   Example from Lumi catalog: `last_verified_free: "2026-06-20"`
   field is exactly for the case where live URL verification is
   denied — the "Catalog refresh" background job (Task 33) will
   perform real rot detection and surface staleness via the timestamp.
   Leave the verification field in the schema, even if you can't
   verify live; it makes the gap surfaceable later.

## Cross-session handoff (read this first after a context compaction)

If you're a future Claude session resuming this project, **read these
files in this order** to recover full context:

1. `ARCHITECTURE.md` — the source of truth for design (4-layer
   pipeline, Two-Layer L0-L5 control model, prompt injection defenses,
   agent limitations, parallel output)
2. `CONTEXT.md` — security coding standards (21 rules across 5
   sections)
3. `threat_model.md` — STRIDE analysis (41 threats, 10 sections)
4. `resources/catalog.json` — 50 curated free AI resources
5. This file (`CLAUDE.md`) — rules for working in the project

**Key invariants that must survive any context loss:**

- **Author**: `kannch8765 <105340539+kannch8765@users.noreply.github.com>`
- **No AI impersonation** in commits (no Antigravity, no Claude, no
  `Co-Authored-By: AI/assistant`)
- **No ゆう in code/comments** (use `sou` or `kannch8765`)
- **English only** in code, comments, and committed docs
- **Tool whitelist is the kill switch** — never add `transfer_money`,
  account creation, or arbitrary URL tools (Layer B → Layer A interface)
- **Two-layer model** is real, not just documentation. Claude's L1
  code-gen choices (Layer B) directly determine Lumi's attack
  surface (Layer A)
- **Pre-commit is the handoff** — semgrep + pytest + ruff must
  pass before commit

**Project diary** for the conversation history:
`/home/claude-workspace/diary.md` (search "2026-06-20" or
"2026-06-21" for the Lumi kickoff session).

**External memory** (across all sessions):
- `feedback/use-subagents-for-parallel.md` — when to parallelize
- `feedback/subagent-hang-diagnose.md` — how to fix stuck agents
- `project/lumi-capstone.md` — project overview + state