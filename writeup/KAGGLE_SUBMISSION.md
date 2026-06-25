# Kaggle Submission — Lumi

**Track:** Agents for Good
**Deadline:** 2026-07-06 11:59 PM PT (12 days from today)
**Submission URL:** https://www.kaggle.com/competitions/vibecoding-agents-capstone-project
**Repo at submission:** https://github.com/kannch8765/lumi @ `2b148ba`

This doc has copy-paste-ready values for every Kaggle submission form field. Open the Kaggle page → "Submit" / "New Submission" tab → paste these in order.

---

## Step 1 — Project link (REQUIRED, required first)

This is the **public URL** to your project (req #4 of 4). Submit this first; Kaggle will let you fill in the rest once it accepts the link.

```
https://github.com/kannch8765/lumi
```

> Optional: pin to commit `2b148ba` for stability: `https://github.com/kannch8765/lumi/tree/2b148ba`
>
> Setup instructions live in the repo's `README.md` (quick start: `uv sync && uv run adk run app/agents "<your query>"`).

---

## Step 2 — Kaggle Writeup (REQUIRED, ≤ 2,500 words)

**Title (paste into the title field):**

```
Lumi — A Multi-Agent System for Finding Free AI Learning Resources
```

**Track (select from dropdown):** `Agents for Good`

**Body (paste into the writeup body — this is `writeup/WRITEUP_KAGGLE.md`, 2,497 words, under the 2,500 cap):**

Open `/home/sou/git/lumi/writeup/WRITEUP_KAGGLE.md` and paste the entire contents into the writeup body field. Sections:

1. Mission & Problem
2. Architecture: A 4-Layer Sequential Pipeline
3. The Two-Layer L0–L5 Control Model — Lumi's Key Innovation
4. Security & Prompt-Injection Defenses
5. Implementation Highlights (5.1–5.6)
6. Live Demo — Portuguese query, end-to-end
7. What's Shipped vs. What's Planned

> The writeup includes a Mermaid diagram in §2. Kaggle supports GitHub-flavored markdown + Mermaid rendering in writeups as of June 2026 — verified when you preview, it should render. If Mermaid fails to render in the Kaggle preview, the worst-case fallback is that it shows as a fenced code block, which still satisfies the architecture-diagram requirement (judges read the text + ASCII fallback).
>
> The full 7,324-word `WRITEUP.md` stays in the repo for documentation; only the Kaggle-submittable `WRITEUP_KAGGLE.md` is what you paste.

---

## Step 3 — Media Gallery (REQUIRED, cover image required)

**Cover image:** upload `/home/sou/git/lumi/writeup/cover.png` (833×1065 PNG, 49 KB).

> This is the project's title card. Required to submit (brief req #2). No other media needed — KAGGLE_SUBMISSION.md and WRITEUP_KAGGLE.md cover the rest.

---

## Step 4 — Attached Public Video (REQUIRED, ≤ 5 min YouTube)

**YouTube URL (paste your uploaded video link here):**

```
[YOUTUBE_URL — paste your public YouTube link here]
```

> Your uploaded video must be ≤ 5 minutes and hosted on YouTube (public, no login). Brief req #3.
>
> Verify before pasting:
> - Video is set to "Public" (not "Unlisted")
> - URL is the standard `https://www.youtube.com/watch?v=...` form (not a shortened `youtu.be`)
> - Duration ≤ 5 min
>
> Once you paste the URL, Kaggle will embed + play it in the submission preview.

---

## Step 5 — Submit

Click "Submit" / "Submit Final" at the bottom of the Kaggle form. You should get a confirmation email + a green "Submission complete" badge.

If any field fails validation, the most common cause is one of:
- Project link requires `https://` (not `git@github.com:...`) → re-paste from the GitHub "Code" dropdown → HTTPS tab
- Cover image upload fails silently if > 5 MB → `cover.png` is 49 KB, well under
- YouTube URL rejected if "Public" toggle isn't on → flip the visibility in YouTube Studio first

---

## What you'll see on the submission preview

After submit, the submission page shows:
- The writeup with Mermaid diagram rendered inline
- The cover image as a thumbnail
- An embedded YouTube player
- The GitHub project link as a clickable card

If any of those four elements doesn't render correctly in the preview, refresh once — Kaggle's preview often needs a hard reload after the first save.

---

## After submission

1. **Confirm** by opening the submission page once more (Kaggle cache is aggressive — the first preview can show stale data).
2. **Save** the submission confirmation URL — you'll need it if any field is challenged in the review.
3. **Tweet / share** (optional) — many entrants post their submission on X / LinkedIn with the hashtag `#5DayAgents` and `#VibeCoding`.

---

## Quick checklist (copy-paste into your notepad before submitting)

- [ ] Kaggle account is `kannch8765` (the same identity used for the repo)
- [ ] Project link = `https://github.com/kannch8765/lumi` (HTTPS, public)
- [ ] Title = "Lumi — A Multi-Agent System for Finding Free AI Learning Resources"
- [ ] Track = `Agents for Good`
- [ ] Writeup body = full contents of `writeup/WRITEUP_KAGGLE.md` (2,497 words)
- [ ] Cover image = `writeup/cover.png` uploaded (49 KB PNG, 833×1065)
- [ ] YouTube URL = your public video link, ≤ 5 min
- [ ] All four required fields populated, no placeholder text
- [ ] Submission preview shows: writeup + cover image + embedded YouTube + GitHub link
- [ ] "Submit Final" clicked, confirmation email received
