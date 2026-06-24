"""Live re-probes for the intent routing fix.

Runs the 5 probes that originally exposed the intent-routing bug
(A2/A3/A4 + regression checks C1/C3) and reports:
- Wall-clock latency
- Result type (TimelineResult / RecommendationResponse / str)
- DEBUG log lines from app.orchestrator (skip-callback evidence)

Usage:
    .venv/bin/python scripts/reprobes.py [--probe A2,A3,A4,C3,C1]

Quota-aware: ~30s spacing between full-pipeline probes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


def _setup_logging() -> None:
    """Capture DEBUG lines from app.orchestrator (skip-callback evidence)."""
    # Reset handlers — pytest may have installed a noisy root config.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.DEBUG)

    # Stream to stdout, app.orchestrator at DEBUG, everything else INFO.
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    # Quiet down noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _run_one(name: str, query: str) -> tuple[float, str]:
    """Run a single probe and return (latency_seconds, result_repr)."""
    from app.orchestrator import run_lumi_query

    t0 = time.perf_counter()
    result = await run_lumi_query(query)
    latency = time.perf_counter() - t0
    return latency, f"{type(result).__name__}: {str(result)[:150]}"


async def main(probes: list[str]) -> None:
    _setup_logging()
    # Load .env from project root for GEMINI_API_KEY.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not set — load .env first")

    # Probe definitions: (name, query, expected_intent, expected_max_latency_s).
    # A2/A3/A4 use follow-up phrasing that presupposes prior context, which
    # L1 classifies as non-full_pipeline (filter_only/freshness_check/drill_down).
    # Original probe phrasings ("I'm a GPU researcher in Japan...") were
    # standalone and L1 correctly classified them as full_pipeline — that
    # can't test the skip mechanism, so we use follow-ups here.
    all_probes: dict[str, tuple[str, str, str, float]] = {
        "A2": (
            "from those, only the ones that work in Japan",
            "filter_only",
            12.0,
        ),
        "A3": (
            "are those courses still free today?",
            "freshness_check",
            15.0,
        ),
        "A4": (
            "tell me more about the Kaggle Python course",
            "drill_down",
            6.0,
        ),
        "C3": (
            "What's the best pizza recipe in Italy?",
            "out_of_scope",
            3.0,
        ),
        "C1": (
            "I'm a CS undergrad in Brazil, want to learn LLMs for free",
            "full_pipeline",
            30.0,  # full pipeline — longest expected
        ),
    }

    print(f"\n{'=' * 70}\nRunning {len(probes)} probe(s)\n{'=' * 70}\n")
    results: list[tuple[str, float, str, float]] = []
    for probe_name in probes:
        if probe_name not in all_probes:
            print(f"⚠️  Unknown probe: {probe_name}, skipping")
            continue
        query, expected_intent, expected_max_s = all_probes[probe_name]

        print(f"\n{'─' * 70}")
        print(
            f"▶ {probe_name} | expected intent={expected_intent}, max={expected_max_s}s"
        )
        print(f"  query: {query!r}")

        try:
            latency, summary = await _run_one(probe_name, query)
        except Exception as exc:
            print(f"  ❌ EXCEPTION: {type(exc).__name__}: {exc}")
            results.append((probe_name, 0.0, f"EXC: {exc}", expected_max_s))
            continue

        status = "✅" if latency < expected_max_s else "❌"
        print(f"  {status} latency={latency:.2f}s (expected <{expected_max_s}s)")
        print(f"  → {summary}")
        results.append((probe_name, latency, summary, expected_max_s))

        # Quota-aware spacing — full-pipeline probes need ~25-30s between.
        if expected_max_s > 5:
            print("  ⏳ 25s quota cooling...")
            await asyncio.sleep(25)
        else:
            await asyncio.sleep(5)

    print(f"\n{'=' * 70}\nSummary\n{'=' * 70}\n")
    for name, lat, summary, max_s in results:
        ok = "✅" if lat < max_s else "❌"
        print(f"  {ok} {name}: {lat:.2f}s / max {max_s}s — {summary}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        default="A2,A3,A4,C3,C1",
        help="Comma-separated probe names (default: A2,A3,A4,C3,C1)",
    )
    args = parser.parse_args()
    asyncio.run(main([p.strip() for p in args.probe.split(",") if p.strip()]))
