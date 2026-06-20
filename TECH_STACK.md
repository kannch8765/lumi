# Tech Stack — Lumi

> Why each tool was chosen. Cross-references ARCHITECTURE.md (design),
> CONTEXT.md (security coding standards), threat_model.md (STRIDE).

## Summary table

| Layer | Choice | Version | Why |
|---|---|---|---|
| Language | Python | 3.11–3.13 | ADK 2.0 + FastAPI ecosystem requirement |
| Agent framework | `google-adk[gcp]` | 2.0.x | Google × Kaggle co-run capstone; native Cloud Run + Gemini integration |
| LLM (default) | Gemini | 2.5-flash | Free tier, fast, multimodal; swap to Anthropic/OpenAI via ADK `model=` param |
| Agent protocol | `mcp[cli]` (FastMCP) | 1.0.x | Standard MCP for tool servers; judges likely know it |
| Schema | Pydantic | 2.x | Dual citizenship (CONTEXT.md §Pydantic schemas); ADK already depends on it |
| Web framework | FastAPI + uvicorn | 0.115+ / 0.30+ | ADK's `get_fast_api_app` wraps FastAPI; matches shop-assistant |
| Telemetry | OpenTelemetry + google-cloud-logging | latest | ADK built-in OTEL instrumentation; Cloud Logging sinks |
| Package manager | `uv` | 0.11+ | Fast installs, lockfile, single tool for venv + deps + run |
| Linter | `ruff` | 0.4+ | Replaces black + isort + flake8 in one Rust tool |
| Type checker | `ty` (Astral) | latest | Same team as ruff/uv; faster than mypy |
| Test framework | `pytest` + `pytest-asyncio` | 9.x / 1.x | De facto Python testing standard; async mode for ADK |
| Pre-commit | `pre-commit` + `pre-commit-hooks` | 4.x / 5.x | Gates commits with ruff + semgrep + whitespace fixes |
| Secret scanner | `semgrep` (custom rules) | 1.100+ | Local-first, no cloud; rules in `.semgrep/rules.yaml` |
| Build backend | `hatchling` | latest | uv-compatible; standard for ADK 2.0 projects |
| Container | Docker (`python:3.12-slim`) | — | Cloud Run requires OCI images; pattern mirrors shop-assistant |
| Deploy target | Cloud Run | — | Google-managed, scales to zero, free tier generous |

## Detailed rationale

### Why `google-adk 2.0`?

1. **Capstone alignment** — Kaggle's "AI Agents: Intensive Vibe Coding Capstone"
   is co-run with Google. ADK is the official Google agent framework. Using
   it earns no penalty and gains reviewer familiarity.
2. **Built-in MCP support** — ADK 2.0 speaks MCP natively. No glue code to
   connect our resource-catalog + web-search servers.
3. **OTEL instrumentation** — `google-adk[gcp]` ships OpenTelemetry for Gemini
   calls, so we get free traces in Cloud Logging without writing middleware.
4. **Cloud Run ergonomics** — `get_fast_api_app(agents_dir=...)` produces a
   production-ready FastAPI app with `/chat`, `/feedback`, eval endpoints,
   and a web playground. No 50-line `main.py` boilerplate.

### Why Gemini as default LLM?

- Free tier covers the demo + Kaggle writeup workload
- Multimodal (we may want screenshot-in / voice-in for v2)
- Native ADK integration (`google.adk.models.G Gemini(...)`)
- **Escape hatch**: any LlmAgent takes a `model=` kwarg, so swapping to
  `anthropic:claude-sonnet-4-6` or `openai:gpt-5` is a one-line change.
  The architecture does not depend on Gemini specifically.

### Why MCP (FastMCP)?

- **Industry standard** — Anthropic-published, adopted by every major agent
  framework. Judges recognize it.
- **The kill switch lives here** — ARCHITECTURE.md §Two-Layer L0–L5: the
  tool whitelist is enforced by what tools the MCP server *exposes*. An
  agent literally cannot transfer money if the MCP server doesn't have a
  `transfer_money` tool. This is stronger than prompt-level guards.
- **Local + remote same API** — FastMCP servers run as subprocesses
  locally (dev) or as Cloud Run services (prod). Code is identical.

### Why Pydantic v2 (not dataclasses)?

- **Dual citizenship** — ARCHITECTURE.md calls out: Pydantic schemas are
  written in Layer B (Claude's code-gen) and enforced in Layer A (Lumi's
  runtime). The same schema is the tool-input contract for MCP and the
  validation gate for the agent's tool calls.
- **Runtime + static** — Pydantic gives runtime validation; `ty` and `ruff`
  give static checks. Both share the same type definitions.
- **ADK already depends on it** — no extra install.

### Why `uv` (not pip + venv)?

- **Speed** — uv installs Lumi's full dep tree in seconds (verified during
  Task 35: 50+ packages in under a minute).
- **Lockfile** — `uv.lock` is the same format as pip's `requirements.txt`
  but deterministic. Cloud Run builds need reproducibility.
- **Single tool** — `uv sync`, `uv run`, `uv add`, `uv pip` replace
  pip + pip-tools + virtualenv.

### Why `ruff` (not black + flake8 + isort)?

- **One tool, one config** — ruff replaces three Python tools with a single
  Rust binary. Same team as `uv`. Same config format as pyproject.
- **Fast** — runs in <100ms on Lumi's full source. Pre-commit stays quick.
- **Configured in pyproject.toml** — `select = ["E", "F", "W", "I", "C",
  "B", "UP", "RUF"]` covers everything we need.

### Why `semgrep` (not gitleaks + trufflehog + detect-secrets)?

- **One config file** — `.semgrep/rules.yaml` defines all secret patterns
  in one place. Adding a new pattern (e.g., for a future provider) is one
  rule entry.
- **Lumi-specific rules** — semgrep can express the "tool whitelist is
  the kill switch" rule (e.g., `lumi-no-transfer-money-tool`). This is
  impossible with pure regex-based secret scanners.
- **No cloud dependency** — semgrep runs entirely local. No data leaves
  the repo. (gitleaks + trufflehog require GitHub Actions secrets for
  hosted scans; semgrep does not.)

### Why `ty` (not mypy / pyright)?

- **Same team as `uv` and `ruff`** — Astral's Rust-based type checker.
  Installing it alongside ruff gives a consistent dev experience.
- **Fast** — first-party type checker for uv-managed projects.
- **Permissive defaults** — `ty` doesn't error on dynamic patterns ADK
  uses (e.g., `LlmAgent(name="app")` reflection). mypy would emit dozens
  of false positives.

### Why Docker + Cloud Run (not Vercel / Railway / Fly)?

- **Google stack alignment** — capstone co-run with Google → judges expect
  Cloud Run. Same as why we picked ADK.
- **Free tier** — 2M requests/month free, scales to zero.
- **Port 8080 + uvicorn pattern** — Dockerfile CMD matches shop-assistant
  exactly. Reusable mental model.

## What this stack does NOT include

These were considered and rejected:

- ❌ **Streamlit / Gradio frontend** — ADK web UI is sufficient for the
  capstone demo. Adding a custom frontend expands deploy surface without
  adding demo value.
- ❌ **Postgres / Redis** — Lumi has no persistent state beyond the
  resource catalog (file-based JSON) and session memory (in-memory by
  default; ADK provides session backends if we ever need them).
- ❌ **LangChain / LlamaIndex** — would conflict with ADK's native tool /
  agent model. Adding it would be dead weight.
- ❌ **LangGraph** — Lumi's pipeline is sequential (L1 → L2 → L3 → L4 →
  output), not a graph of branching state machines. ADK's
  `SequentialAgent` covers this cleanly.

## How this stack maps to the Two-Layer L0–L5 model

| Layer | Tool / file | Role |
|---|---|---|
| A — L0 Entry | FastAPI + Cloud Run | Public-facing surface; first thing the user hits |
| A — L1 Tool whitelist | MCP server's `tools=[...]` | The kill switch — what Lumi can do |
| A — L2 MCP boundary | FastMCP stdio / HTTP | Hard isolation between Lumi and the outside world |
| A — L3 Agent logic | `google-adk` `LlmAgent` | Reasoning layer; constrained by L1 + L2 |
| A — L4 Output | Pydantic response schemas | Typed return; matches input contract |
| A — L5 Deploy | Docker + Cloud Run | Operationally hardened runtime |
| B — L0 Input boundary | `.claude/CLAUDE.md` (gitignored) | Claude's per-project memory |
| B — L1 Code gen | ruff + ty + Pydantic | Claude's *own* constraints on what code is acceptable |
| B — L2 Pre-commit | `.pre-commit-config.yaml` | Gate before commit; blocks bad patterns |
| B — L3 Review | semgrep custom rules | AST-aware block on kill-switch violations |
| B — L4 Repo | Git + .gitignore | Working history; provenance for judges |
| B — L5 Infra | uv lockfile + Dockerfile | Deterministic build; reproducible deploy |

This is the **handoff surface** — every row in Layer B either constrains
what code Claude generates, or catches violations before they reach Layer
A. The pre-commit hook is the literal "compile + test" gate between
layers (cf. ARCHITECTURE.md §Two-Layer model).
