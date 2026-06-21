"""Lumi pytest configuration.

Loads `.env` (gitignored) at session start so tests that need
`GEMINI_API_KEY` can read it via `os.environ`. Without this, E2E and
integration tests would have to be invoked with `--env-file` or by
manually exporting the variable.

This is intentionally a no-op when `.env` is missing (e.g. CI without
the file) — tests that need the key should `@pytest.mark.skipif` on
`os.getenv("GEMINI_API_KEY")` and document the requirement.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above tests/).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
