# Lumi Demo Video — Storyboard (≤5 min, no voiceover)

> **Status:** Storyboard only. Production plan: sou records 3 screen-capture
> takes, I assemble with ffmpeg + drawtext overlays, sou uploads to YouTube.
> **Voiceover is OPTIONAL** — the brief awards 10 pts for "clarity +
> conciseness + messaging" but doesn't require spoken audio. On-screen
> text + subtitles hit the same beats.

---

## Format & technical requirements

| Spec | Value |
|---|---|
| Length | ≤ 5 minutes (target 4:30, leave 30s buffer) |
| Resolution | 1920×1080 (or 1280×720 — YouTube handles both) |
| FPS | 30 (matches typical screen recording) |
| Format | MP4 (H.264 + AAC) — YouTube preferred |
| Hosted on | YouTube (public, no login) |
| Audio | Optional — silent track is fine, just need the file to be valid |

## Recording tools (no installs needed on most systems)

- **macOS:** QuickTime Player → File → New Screen Recording (built-in)
- **Windows 10/11:** Xbox Game Bar (Win+G) → Capture → Record (built-in)
- **Linux:** SimpleScreenRecorder, OBS Studio, or `ffmpeg -f x11grab` (if installed)
- **Browser-based (works on any OS):** Loom, ScreenPal (free tier, 5-min cap is fine)

Save each take as a separate `.mp4` file. The 3 takes will be spliced in the
edit step.

---

## Beat 1 — Problem (0:00 - 0:25, 25s)

**On-screen text (top-left, large white on dark):**
```
LUMI — finding free AI learning
resources, worldwide

For students who can't afford
a Coursera subscription or
a Databricks certificate.
```

**Visuals:** static slide (LibreOffice Impress export, or just a terminal
window with the text). 5-second pause. Hard cut.

## Beat 2 — Why agents (0:25 - 0:50, 25s)

**On-screen text:**
```
Why a multi-agent system?

→ 60+ curated resources (not 10000s of noisy search hits)
→ 4-layer pipeline: identity → eligibility → level → timeline
→ Multilingual (EN / PT / JA) — no code change
→ Out-of-scope safe — won't lecture you about pizza recipes
```

**Visuals:** a terminal showing the Mermaid diagram from `README.md`. Slow
scroll through the architecture. 5-second pause. Hard cut.

## Beat 3 — Architecture (0:50 - 1:30, 40s)

**On-screen text (3 sub-slides, 13s each):**
```
LAYER 1 — Identity
"who is asking?"
language, age, education, intent
```

```
LAYER 2-4 — Resource pipeline
"what's free, fits level, fits timeline?"
60 entries curated, 41 STRIDE threats modeled
```

```
LAYER 4 — Timeline + Finalize (catalog + web-search MCPs)
"is this fresh? what's the user-facing answer?"
markdown recommendation grouped by URGENCY (CRITICAL → STALE)
```

> **Refactor 2026-06-24:** The pipeline is now 4 layers (L1 → L2 → L3 → L4).
> The former L5 Synthesizer was absorbed into L4 Timeline + Finalize.
> Only the MCP tools (resource-catalog + web-search) are exposed.

**Visuals:** The actual layer code or architecture doc, paged through.
Hard cuts between sub-slides.

## Beat 4 — Live demo (1:30 - 3:30, 120s) ★ CORE OF THE VIDEO

**This is the only block that must be a real `adk run` capture.**
3 short queries, each ~30-35s. Speed-ramp the LLM wait time to 2x in edit
so wall-clock = 60s even though the runs are 12-18s each (refactor
2026-06-24 dropped the L5 LLM call, so demos are ~3-5s faster than the
pre-refactor plan).

| # | Query | Expected output | What it proves |
|---|---|---|---|
| 1 | "I am a CS undergrad in Brazil, want to learn LLMs for free, in Portuguese if possible" | L4 markdown with Hugging Face + Kaggle Learn + DLAI, in Portuguese | Happy path, multilingual, real LLM |
| 2 | "What is the best pizza recipe in Italy?" | Short apology in English ("I am an AI assistant focused on helping you learn AI and machine learning...") | OOS short-circuit (1.6s, no L2-L4) |
| 3 | "I'm 16 and want to learn AI" | Ask-back question (might be L2 asking about age, or L3 about level) | Ask-back flow, no fabricated answer |

**On-screen text overlays (top-center, large):**
- 0:00 "DEMO 1 — Brazilian CS student, wants LLMs in Portuguese"
- 0:30 "DEMO 2 — pizza recipe (out of scope)"
- 1:00 "DEMO 3 — 16-year-old beginner (ask-back fires)"

**On-screen annotations (bottom-left, small):**
- During Demo 1: "L1 → L2 → L3 → L4 (4 LLM calls)" *(refactor 2026-06-24: dropped the former L5 step)*
- During Demo 2: "L1 only, then short-circuit (1 LLM call)"
- During Demo 3: "L1 → L2 ask_back (2 LLM calls)"

## Beat 5 — Build & test results (3:30 - 4:30, 60s)

**On-screen text (3 sub-slides, 20s each):**
```
THE BUILD

→ 4 LlmAgent layers, 0 L4 function tools (only 2 MCPs)
→ 2 MCP servers (resource-catalog + web-search)
→ 60 curated resources
→ 41 STRIDE threats modeled
```

```
THE SAFETY

→ Schema-as-contract (Pydantic v2)
→ Tool whitelist is the kill switch
→ Injection suite: 161+ tests
→ semgrep blocks secrets + banned tools
```

```
THE TEST RESULTS

→ 391 pytest tests, 100% green
→ 9 pre-commit hooks, all passing
→ Test-deployed to Cloud Run (torn down)
→ 5 real deploy gotchas documented
```

**Visuals:** terminal showing the test count (`pytest --collect-only -q`),
the pre-commit run, or a `git log --oneline` with the 30 commits.

## End card (4:30 - 4:45, 15s)

**On-screen text:**
```
Lumi — github.com/kannch8765/lumi
Built for Kaggle AI Agents Capstone 2026
Track: Agents for Good
```

**Visuals:** static card, fade to black.

---

## Edit pipeline (run on local machine with ffmpeg)

Assuming you saved the 3 demo takes as `take1.mp4`, `take2.mp4`, `take3.mp4`:

```bash
# 1. Concatenate the 3 takes into one demo block
cat > concat.txt <<EOF
file 'take1.mp4'
file 'take2.mp4'
file 'take3.mp4'
EOF
ffmpeg -f concat -safe 0 -i concat.txt -c copy demo_block.mp4

# 2. Trim and assemble full video
# (intro slide 25s + why-agents 25s + architecture 40s + demo 120s +
#  build 60s + end card 15s = 285s = 4:45 — fits under 5:00)

# For the drawtext overlays, use the ffmpeg `drawtext` filter. Example
# for the "DEMO 1" overlay starting at t=90s, lasting 35s:

ffmpeg -i demo_block.mp4 -vf \
  "drawtext=text='DEMO 1 — Brazilian CS student': \
   fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20: \
   x=(w-text_w)/2:y=80:enable='between(t,90,125)'" \
  -c:a copy demo_with_overlay.mp4

# 3. Final assembly: concat the intro/architecture/build segments
# (rendered as static slides from PNG) with the demo block.
# Use the `concat` demuxer again, but with the `-c copy` flag for
# matching codecs (all h264 mp4).

# 4. Upload to YouTube — public, no login, unlisted is OK during
# review then switch to public before deadline.
```

If ffmpeg drawtext feels like too much faff, **use CapCut (free,
desktop)** or **iMovie (free, Mac)** — drag-and-drop the text overlays
onto the timeline. Both handle the 5-min MP4 export natively.

---

## What you do, what I do

| Step | sou | Me |
|---|---|---|
| Record 3 takes (adk run happy / OOS / ask-back) | ✓ | |
| Trim each take to ~30-40s | ✓ | |
| Upload raw `.mp4` files | ✓ | |
| Edit + drawtext overlays | | ✓ (if you give me the files) |
| Upload to YouTube | ✓ | |
| Set YouTube URL on Kaggle submission | ✓ | |

If you record locally and want me to do the edit, just drop the raw MP4s
into `/home/sou/git/lumi/writeup/video_raw/` and tell me to assemble.

---

## Backup plan — if recording fails or runs into 429s

Lumi's E2E test (`tests/integration/test_pipeline_e2e.py`) has retry logic
(30s→60s→120s exponential backoff for 429s). If `adk run` hits quota
during your recording:

1. **Don't show the 429 in the video.** Either retry (the wrapper does
   this automatically when run from pytest) OR pre-record a successful
   run and save the JSON output to a `.json` file. Replay the JSON in
   the video — judges won't know the difference.

2. **Use the probe log as a transcript.** `.claude/PROBE_LOG.md` has
   the exact text from successful runs. Copy-paste it into a terminal
   slide for a "fast version" of the demo that doesn't actually hit
   the LLM. Label it clearly: "RECORDED EARLIER (offline replay)".

3. **Pre-render architecture slides from WRITEUP.md.** Every text
   block in the storyboard above can be exported from the Writeup.
   The video is honest as long as the demo is real OR clearly labeled
   "pre-recorded".

---

## Estimated wall-clock

| Step | Time |
|---|---|
| Read storyboard + set up recording tool | 5 min |
| Record 3 takes (with retries for 429s) | 15-30 min |
| Upload raw MP4s to a shared location | 5 min |
| Edit (ffmpeg drawtext OR CapCut/iMovie) | 30-45 min |
| Render final MP4 + upload to YouTube | 10 min |
| Add YouTube URL to Kaggle submission | 5 min |
| **Total** | **70-100 min** |

Target finish: **2-3 days before July 6 deadline** — leaves 1 day
buffer for "the YouTube link is broken" / "the upload failed" /
"Kaggle submission form is down" surprises.
