# Lumi — ASCII Art Diagrams

> Hand-drawn ASCII art for the demo video. Big, clean, monospace-friendly.
> No Unicode tricks (en-dashes, em-dashes, box-drawing chars avoided for
> terminal compatibility). All diagrams fit ≤80 cols.
>
> **How to use in the video:** paste into a terminal `cat > diagram.txt`,
> then `cat diagram.txt` in the recording — looks like a code slide.

---

## 1. Architecture Map — the 4-layer pipeline

```
+----------------------------------------------------------------+
|                       LUMI  PIPELINE                          |
|            (4 layers, 1 user query in)                          |
+----------------------------------------------------------------+

  [ USER QUERY ]                       e.g. "I'm a CS undergrad in
        |                               Brazil, want to learn LLMs
        v                               for free, in Portuguese"
  +-----------+
  |    L1     |   Identity Agent
  |  (no LLM) |   extracts: language, age, education, skill,
  |           |   intent, target_agents
  +-----+-----+   no tools. typed Pydantic output.
        |
        |  target_agents = [L2, L3, L4]   (full_pipeline)
        |  target_agents = [L4]          (freshness_check / drill_down)
        |  target_agents = []            (out_of_scope)
        v
  +-----------+
  |    L2     |   Eligibility Agent
  | (catalog  |   60 curated resources, 3 MCP tools:
  |   MCP)    |     search_catalog, get_resource_by_id, list_by_type
  +-----+-----+   output: candidates that match age / country / cost
        |
        v
  +-----------+
  |    L3     |   Level Filter Agent
  | (catalog  |   matches candidate resources to user's skill level
  |   MCP)    |   "absolute beginner" -> explainers, not courses
  +-----+-----+   output: fit_score ranked candidates
        |
        v
  +-----------+
  |    L4     |   Timeline + Finalize Agent
  | (catalog  |   adds urgency + deadlines + freshness, then emits
  |   + web   |   the user-facing markdown recommendation directly
  |  search)  |   2 MCP servers: catalog + web-search
  +-----+-----+   SERVER-AUTHORITATIVE date (no LLM hallucination)
        |         groups by URGENCY (CRITICAL -> STALE)
        |         refuses to invent URLs
        v
  +-----------+
  |   USER    |   friendly markdown, in user's language,
  |  ANSWER   |   with follow-up question
  +-----------+
```

> **Refactor 2026-06-24:** The former `RANKER` (code-only sort) and
> `L5` (Synthesizer) boxes were absorbed into L4 Timeline + Finalize.
> `app/ranking.py` is retained as a library for a future real-time
> web-search deployment.

### Compact version (for tighter video frames)

```
  L1          L2          L3          L4
Identity  -> Eligibility -> Level   -> Timeline + Finalize
no tools     3 MCP tools  3 MCP   2 MCP servers, emits markdown
Pyd out      candidates   fit     urgency+date -> reply
```

---

## 2. Target Audience Map — who uses Lumi

```
+----------------------------------------------------------------+
|                   WHO IS  LUMI  FOR ?                         |
+----------------------------------------------------------------+

                +-----------------------+
                |  STUDENT  PROFILE     |
                |  wants to learn AI    |
                |  needs FREE resources |
                |  no $ for Coursera    |
                +-----------+-----------+
                            |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
  +-------------+    +--------------+    +-------------+
  | ABSOLUTE    |    |  ALREADY     |    |  ADVANCED   |
  | BEGINNER    |    |  LEARNING    |    |  (uni+ /    |
  | (never      |    |  (some Py,   |    |  built      |
  |  coded)     |    |  some ML)    |    |  own LLM)   |
  +------+------+    +-------+------+    +------+------+
         |                  |                  |
         v                  v                  v
  explainers:          resources:         resources:
  Code.org             Kaggle Learn       CS231n
  Scratch              HF LLM Course      CS224n
  CS50                 DLAI Short         fast.ai
  Khan Academy         FreeCodeCamp       Full Stack
  Grasshopper          Kaggle Comp.       Deep Learning
  CodeCombat           Hugging Face       LLM Bootcamp
  Progate              AWS credits
  Dotinstall          GCP credits
  MDN                  HF Agents
                          |
                          v
                   +-------------+
                   |  GEOGRAPHY  |   optional filter:
                   |  matters?   |     - brazil  (PT)
                   +------+------+     - japan   (JA)
                          |            - nigeria (no filter)
                          v            - global
                   +-------------+
                   |  AGE  /     |   optional filter:
                   |  ELIGIBILITY|     - 13+  (Scratch, Code.org)
                   |  matters?   |     - 16+  (most platforms)
                   +-------------+     - 18+  (Kaggle, GCP, AWS)


+----------------------------------------------------------------+
|  OUT  OF  SCOPE : Lumi politely declines, no lecture about     |
|  pizza recipes or movie reviews. Brief OOS apology string.    |
+----------------------------------------------------------------+
```

### The 5-intent router (compact)

```
   USER QUERY
        |
        v
  +-----------+
  |    L1     |   intent = ?
  |   intent  |   (1 LLM call)
  |   router  |
  +-----+-----+-----+-----+-----+-----+
        |     |     |     |     |     |
        v     v     v     v     v     v
      full  filter fresh  drill  OOS   ???  (fallback: full)
       |      |     |      |      |
       v      v     v      v      v
     L2-4  L3-4   L4     L4   short
                       only         circuit
```

---

## 3. Cost-optimization story (the "why this matters" diagram)

```
+----------------------------------------------------------------+
|   WITHOUT  INTENT  ROUTING  (buggy Lumi)                       |
+----------------------------------------------------------------+

  query  -->  L1  -->  L2  -->  L3  -->  L4
  (all 4 LLM calls, every time)

  14-22s latency  |  $0.004 per query  |  15 RPM quota burns fast

+----------------------------------------------------------------+
|   WITH  INTENT  ROUTING  (current Lumi, post-refactor)         |
+----------------------------------------------------------------+

  query  -->  L1
              |
              +--> target_agents=[L2, L3, L4]  (full pipeline,   ~14s)
              +--> target_agents=[L3, L4]      (filter_only,     ~8s)
              +--> target_agents=[L4]          (freshness,       ~6s)
              +--> target_agents=[L4]          (drill_down,      ~3s)
              +--> target_agents=[]            (out_of_scope,  1.6s)

  intent determines LLM calls, latency, and cost.
```

> **Refactor 2026-06-24:** Latency numbers dropped ~3-5s (no L5 LLM
> call). L4-only paths (``freshness`` / ``drill_down``) now skip the
> earlier layers entirely.

---

## 4. Security model (the 2-layer control diagram)

```
+================================================================+
|   LAYER  A  :  PRODUCT  RUNTIME                                |
|   (the agent, in production)                                    |
+================================================================+

  USER  --query-->  L1 -> L2 -> L3 -> L4  --reply--> USER
                    |    |    |    |
                    v    v    v    v
                  [tool whitelist = kill switch]
                  [schema = contract]
                  [output = Pydantic, no free text]

+================================================================+
|   LAYER  B  :  DEVELOPER  PROCESS                              |
|   (before any code runs in production)                          |
+================================================================+

  9 pre-commit hooks:
    - ruff format
    - ruff check (UP / F / RUF / B / E / W rules)
    - mypy
    - bandit
    - semgrep (secrets + banned tools + L4 injection patterns)
    - lumi_guard (custom: blocks personal info, blocked paths)
    - gitleaks
    - detect-private-key
    - check-yaml / check-toml / trailing-whitespace

  Pydantic schema-as-contract:
    - same schema is MCP tool input AND static type AND Pydantic model
    - "if it compiles AND tests pass, it's correct"

  Threat model:
    - 41 STRIDE rows, each with mitigation
    - injected patterns tested in 161+ unit tests
    - L4 explicitly refuses to echo "system prompt" / "my instructions"
      (refactor 2026-06-24: this defense was migrated from L5 to L4)

+================================================================+
|   HANDOFF  :  pre-commit is the Layer B -> Layer A handoff     |
|   (no commit without all 9 hooks green)                         |
+================================================================+
```

---

## 5. The "5-beat video" flow (storyboard visual)

```
+----------------------------------------------------------------+
|   LUMI  DEMO  VIDEO  ( 4 min 45 sec )                          |
+----------------------------------------------------------------+

  [ 0:00 ]  BEAT 1 :  PROBLEM           ( 25 sec )
            "students can't find free AI resources"
  [ 0:25 ]  BEAT 2 :  WHY  AGENTS       ( 25 sec )
            "matching > displaying"
  [ 0:50 ]  BEAT 3 :  ARCHITECTURE      ( 40 sec )
            "4 layers, 0 L4 function tools, 2 MCP servers"
  [ 1:30 ]  BEAT 4 :  LIVE  DEMO        ( 120 sec )   <- 3 takes
            "PT / OOS / ask-back"
  [ 3:30 ]  BEAT 5 :  BUILD + TESTS     ( 60 sec )
            "378 tests, 9 hooks, 60 resources, 41 threats"
  [ 4:30 ]  END  CARD                  ( 15 sec )
            "github.com/kannch8765/lumi"
```

---

## Rendering notes

- All diagrams fit in **80 columns** (terminal default).
- All use **ASCII only** — no Unicode box-drawing, no special chars.
- For the video, paste each diagram into a `.txt` file, then `cat` it in
  the recording. Looks like a code slide, judges can read it.
- If 80-col is too narrow for your video frame, **upscale the font** in
  the terminal settings (default Mac Terminal: Cmd-+). The diagrams
  scale linearly.
- For 4K frames: use **alacritty** or **kitty** terminal — both render
  monospace at 200+ DPI cleanly.
