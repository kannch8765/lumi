# Kaggle Competition Brief — AI Agents: Intensive Vibe Coding Capstone Project

> **Reference copy of the competition page** for Lumi's submission.
> Source: <https://www.kaggle.com/competitions/vibecoding-agents-capstone-project>
> Saved: 2026-06-21 (snapshot — verify against live page if anything changes).
> For Lumi's actual writeup, see `WRITEUP.md`.

## Quick metadata

| Field | Value |
|---|---|
| Title | AI Agents: Intensive Vibe Coding Capstone Project |
| Host | Kaggle (in partnership with Google's 5-Day AI Agents course) |
| Type | Hackathon / capstone project |
| Lumi track | **Agents for Good** |
| Announced | 2026-06-19 (during the 5-Day livestream) |
| Submissions due | **2026-07-06 11:59 PM PT** (15 days from snapshot) |
| Prize | Kaggle swag (non-monetary) — 3 awards per track |
| Entrants / Participants / Teams / Submissions | 2,622 / 79 / 77 / 77 |
| Citation | Brenda Flynn, Kanchana Patlolla, Polong Lin, Anant Nawalgaria, Fran Hinkelmann, Kinjal Parekh, Melissa Nalubwama-Mukasa, María Cruz, and Naz Bayrak. *AI Agents: Intensive Vibe Coding Capstone Project.* <https://kaggle.com/competitions/vibecoding-agents-capstone-project>, 2026. Kaggle. |

## Mission

> AI agents are rapidly changing how we interact with technology, enabling
> systems that can reason, take action, and complete complex tasks on behalf
> of users. In this capstone project, you'll apply the concepts, tools, and
> techniques learned throughout Kaggle's 5-Day AI Agents: Intensive Vibe
> Coding Course with Google to build an agent that solves a meaningful
> real-world problem.
>
> Whether you're creating an assistant that helps individuals stay
> organized, streamlines business processes, supports social impact
> initiatives, or explores a completely new idea, this project is an
> opportunity to move beyond experimentation and develop something useful,
> practical, and shareable. We encourage participants to think creatively,
> focus on delivering value, and demonstrate how agent-based systems can
> address real challenges.

## Submission requirements

A valid submission must contain **all four** of the following:

1. **Kaggle Writeup** — project report (≤ 2,500 words; over-limit may be
   penalized). Must select a Track. Title + subtitle + detailed analysis.
2. **Media Gallery** — cover image (required to submit) + other visuals.
3. **Attached Public Video** — ≤ 5 min, hosted on YouTube.
4. **Attached Project Link** — public URL to working product or interactive
   demo. If a live demo is not feasible, a public code repo (e.g. GitHub)
   with detailed setup instructions is acceptable. Must be publicly
   accessible (no login, no paywall).

> Any un-submitted or draft Writeups by the deadline will not be reviewed.

## Tracks

Lumi is submitted to **Agents for Good**:

> In the Agents for Good track, we'll be looking for submissions that help
> solve problems for humanity. From optimizing agriculture to managing
> public health, advancing education or supporting art and literature —
> this is the track for helping people.

Other tracks (for reference):

- **Agents for Business** — agents solving enterprise problems with cost
  or revenue impact.
- **Concierge Agents** — personal agents for individuals / families that
  keep personal information safe.
- **Freestyle** — anything that doesn't fit a bucket, as long as it
  showcases agent best practices.

> Note: Kaggle reserves the right to move winners between tracks after
> review if it seems appropriate.

## Evaluation criteria (100 points total)

### Key concepts — at least 3 of 6 must be demonstrated

| # | Key concept | Where to demonstrate |
|---|---|---|
| 1 | Agent / Multi-agent system (ADK) | Code |
| 2 | MCP Server | Code |
| 3 | Antigravity | Video |
| 4 | Security features | Code or Video |
| 5 | Deployability | Video |
| 6 | Agent skills (e.g., Agents CLI) | Code or Video |

### Category 1 — The Pitch (30 points)

| Criterion | Points | What we need |
|---|---:|---|
| Core Concept & Value | 10 | Innovation, relevance to Agents for Good track, central use of agents |
| YouTube Video Submission | 10 | Clarity + conciseness + messaging; problem / why agents / architecture / demo / build |
| Writeup | 10 | Articulates problem, solution, architecture, journey |

### Category 2 — The Implementation (70 points)

| Criterion | Points | What we need |
|---|---:|---|
| Technical Implementation | 50 | Architecture quality, code quality, meaningful agent use, clever tool use, code comments |
| Documentation | 20 | `README.md` covering problem / solution / architecture / setup / diagrams |

> **Deployment is optional for judging** but recommended. If we deploy,
> include reproduction docs.
> **DO NOT INCLUDE ANY API KEYS OR PASSWORDS IN YOUR CODE.** (Kaggle's
> own reminder — not specific to Lumi.)

## Timeline

| Date | Event |
|---|---|
| 2026-06-19 | Capstone announced during the 5-Day livestream |
| 2026-07-06 11:59 PM PT | **Submissions due** |

## Lumi coverage check

Mapping each Kaggle requirement to our task status:

| Kaggle requirement | Lumi status | Notes |
|---|---|---|
| Track: Agents for Good | ✅ Selected | Mission = free AI learning resources for students worldwide |
| Key concept 1: Multi-agent system (ADK) | ✅ 5-layer pipeline | L1 → L2 → L3 → L4 → L5 (SequentialAgent, 6 sub-agents) + ranker (parallel output stage). L5 Synthesizer has zero tools and emits the final markdown recommendation. |
| Key concept 2: MCP Server | ✅ 2 servers | `resource-catalog` (3 tools) + `web-search` (1 tool) |
| Key concept 3: Antigravity | 🟡 TBD — Task 28 | Demo video (Task 28 — owner-led) |
| Key concept 4: Security features | ✅ Defense-in-depth | Schema caps, tool whitelist, semgrep, prompt-injection suite (363 tests, 9 deselected for E2E + manual) |
| Key concept 5: Deployability | ✅ Task 27 | Test-deploy-then-tear-down completed 2026-06-22 (5 real gotchas captured in deploy/README.md + WRITEUP.md §6) |
| Key concept 6: Agent skills / CLI | ✅ Task 56 | adk CLI demonstrated in WRITEUP.md §5.6 (Task 56 done). `app/agents/agent.py` exposes `root_agent = create_lumi_pipeline()`. |
| Kaggle Writeup (≤ 2,500 words) | 🟡 §1-5 done | §6-7 pending real run data — Task 39 |
| Media Gallery (cover image) | ✅ Task 40 | [`writeup/cover.png`](./cover.png) — 833×1065, title + 4-layer pipeline + tagline (github/test counts) |
| Public Video (≤ 5 min) | ❌ Task 28 | Not started |
| Public Project Link | ✅ | Repo: <https://github.com/kannch8765/lumi> (already public); live demo URL pending Task 27 |
| Documentation: README.md | ✅ | Project root |
| No API keys in code | ✅ | `.env` gitignored, semgrep blocks AIza/sk-/AQ/ghp_ patterns |

**Current coverage: 6/6 key concepts demonstrated in code + security
docs. Remaining: Public Video (Task 28) and final submission (Task 30).**

## Citation (use this in the Writeup)

```
Brenda Flynn, Kanchana Patlolla, Polong Lin, Anant Nawalgaria,
Fran Hinkelmann, Kinjal Parekh, Melissa Nalubwama-Mukasa, María Cruz,
and Naz Bayrak. AI Agents: Intensive Vibe Coding Capstone Project.
https://kaggle.com/competitions/vibecoding-agents-capstone-project,
2026. Kaggle.
```

## Judges (Kaggle staff — for awareness only)

Tanvi Singhal · Laxmi Harikumar · Aman Tayal · Vijit Singh · Eric Schmidt
· Nilay Chauhan · Thilakraj Sripal · Naz Bayrak · Luis Sala ·
Martyna Plomecka · Tania Rodriguez Fuentes · Sara Wolley · Brenda Flynn

(These are the official judges listed on the competition page. We do not
need to name them in the Writeup — listing is just for our awareness.)
