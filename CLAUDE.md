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