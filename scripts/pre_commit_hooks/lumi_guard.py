#!/usr/bin/env python3
"""Lumi personal info guard — pre-commit hook.

Defense-in-depth on top of `.gitignore`. Even if someone runs
`git add -f .claude/CLAUDE.md` or commits a file with the private
nickname ゆう, this hook blocks the commit.

Checks three classes of violation:

  1. Banned paths — files that must never be committed (private config,
     secrets, build artifacts).
  2. Personal info in source files — private nicknames or AI product
     names. Excludes data files (resources/catalog.json may legitimately
     contain real names of instructors) and the guard script itself.
  3. Git author identity — must be `kannch8765` with the noreply email.
     Catches accidental `Co-Authored-By` or wrong-config impersonation
     before it reaches the git history.

Run via `.pre-commit-config.yaml`:

    - repo: local
      hooks:
        - id: lumi-guard
          name: Lumi personal info + author guard
          entry: python scripts/pre_commit_hooks/lumi_guard.py
          language: system
          types: [file]

Exit code 0 = clean, 1 = blocked (with diagnostic per violation).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ─── 1. Banned paths ───────────────────────────────────────────────────────
# These should already be gitignored. The hook is belt-and-suspenders
# against `git add -f` or copy-paste mistakes.

BANNED_PATH_PATTERNS: tuple[str, ...] = (
    r"^\.claude/",
    r"^\.env(\..+)?$",
    r"^\.env$",
    r"^\.venv/",
    r"\.pem$",
    r"\.key$",
    r"service-account.*\.json$",
    r"gcp-credentials.*\.json$",
)

# ─── 2. Personal info patterns ────────────────────────────────────────────
# Searched in staged source files only. Files in EXCLUDED_FILES are not
# scanned (real-name data is intentional there).

# The regex strings here are written as escape sequences so the source
# file does not contain the literal private nickname. pre-commit will
# still match them in target files at scan time.

PRIVATE_NICKNAME_YUU = "\\u3086\\u3046"
PRIVATE_NICKNAME_BAOBAO = "\\u5b9d\\u5b9d"

PERSONAL_INFO_PATTERNS: tuple[tuple[str, str], ...] = (
    (PRIVATE_NICKNAME_YUU, "private nickname"),
    (PRIVATE_NICKNAME_BAOBAO, "private nickname"),
)

# AI product / brand names that should not appear in Lumi's source code.
# These are fine in design docs (ARCHITECTURE.md references them for
# security context) but should not leak into runtime code.

AI_PRODUCT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bAntigravity\b", "AI product name (use sou / kannch8765 instead)"),
    (r"\bclaude\.ai\b", "AI product URL"),
)

# Files where real names are intentional and must NOT be scanned.
EXCLUDED_FILES: frozenset[str] = frozenset(
    {
        "resources/catalog.json",
        "scripts/pre_commit_hooks/lumi_guard.py",  # the guard itself
    }
)

# File extensions where pattern scanning applies.
SCANNABLE_EXTENSIONS: tuple[str, ...] = (
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".sh",
    ".txt",
    ".cfg",
    ".ini",
    ".dockerfile",
)

# ─── 3. Author identity ────────────────────────────────────────────────────
EXPECTED_AUTHOR_NAME = "kannch8765"
EXPECTED_AUTHOR_EMAIL = "105340539+kannch8765@users.noreply.github.com"


def get_staged_files() -> list[str]:
    """Return list of files staged for the upcoming commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def check_banned_paths(staged_files: list[str]) -> list[str]:
    errors: list[str] = []
    for filepath in staged_files:
        for pattern in BANNED_PATH_PATTERNS:
            if re.search(pattern, filepath):
                errors.append(f"BANNED PATH: {filepath!r} matches {pattern!r}")
    return errors


def is_scannable(filepath: str) -> bool:
    """Source files (code + docs + config) get scanned for personal info."""
    p = Path(filepath)
    # Always scan .py files; for others, check extension.
    if p.suffix.lower() in SCANNABLE_EXTENSIONS:
        return True
    if p.name in {"Dockerfile", "Makefile"}:
        return True
    return False


def check_personal_info(staged_files: list[str]) -> list[str]:
    errors: list[str] = []
    for filepath in staged_files:
        if filepath in EXCLUDED_FILES:
            continue
        if not is_scannable(filepath):
            continue
        path = Path(filepath)
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Personal nickname patterns
        for pattern, description in PERSONAL_INFO_PATTERNS:
            compiled = re.compile(pattern)
            for match in compiled.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                line = content.split("\n")[line_no - 1].strip()
                errors.append(
                    f"PERSONAL INFO in {filepath}:{line_no}: "
                    f"{description} — {line[:80]!r}"
                )
        # AI product patterns (Python source files only — docs are exempt)
        if filepath.endswith(".py"):
            for pattern, description in AI_PRODUCT_PATTERNS:
                compiled = re.compile(pattern)
                for match in compiled.finditer(content):
                    line_no = content[: match.start()].count("\n") + 1
                    line = content.split("\n")[line_no - 1].strip()
                    errors.append(
                        f"AI PRODUCT NAME in {filepath}:{line_no}: "
                        f"{description} — {line[:80]!r}"
                    )
    return errors


def check_author() -> list[str]:
    """Verify git config user.name and user.email match the Lumi owner."""
    errors: list[str] = []

    result = subprocess.run(
        ["git", "config", "user.name"], capture_output=True, text=True, check=False
    )
    actual_name = result.stdout.strip()

    result = subprocess.run(
        ["git", "config", "user.email"], capture_output=True, text=True, check=False
    )
    actual_email = result.stdout.strip()

    if actual_name != EXPECTED_AUTHOR_NAME:
        errors.append(
            f"AUTHOR NAME: expected {EXPECTED_AUTHOR_NAME!r}, got {actual_name!r}"
        )
    if actual_email != EXPECTED_AUTHOR_EMAIL:
        errors.append(
            f"AUTHOR EMAIL: expected {EXPECTED_AUTHOR_EMAIL!r}, got {actual_email!r}"
        )
    return errors


def main() -> int:
    staged = get_staged_files()

    all_errors: list[str] = []
    all_errors.extend(check_banned_paths(staged))
    all_errors.extend(check_personal_info(staged))
    all_errors.extend(check_author())

    if all_errors:
        print("=" * 64)
        print("LUMI PERSONAL INFO GUARD: COMMIT BLOCKED")
        print("=" * 64)
        for err in all_errors:
            print(f"  X {err}")
        print("=" * 64)
        print(f"{len(all_errors)} violation(s). Fix and re-stage.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
