# Lumi

> **Mission**: Help students worldwide access free AI learning resources
> (courses, competitions, API credits, GPU resources) by removing
> financial, geographic, and informational barriers.

Lumi is a multi-agent system built for the
[Kaggle AI Agents: Intensive Vibe Coding Capstone Project](https://kaggle.com/competitions/vibecoding-agents-capstone-project)
(track: **Agents for Good**).

## Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full 4-layer pipeline design:

1. **L1 Identity Agent** — confirms who the user is
2. **L2 Eligibility Search Agent** — filters by region / age / institution
3. **L3 Level Filter Agent** — matches user's skill level
4. **L4 Timeline Agent** — annotates deadlines + freshness

Parallel output stage ranks the result by urgency / topic / value / sequence.

## Status

🚧 **Scaffolding** — design phase. See tasks tracked in the project board.

## License

TBD (Apache 2.0 likely, matching the secure-agent-lab codelab)
