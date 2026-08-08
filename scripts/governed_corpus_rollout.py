#!/usr/bin/env python3
"""Build a provider-free governed corpus P0 dry-run."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.governed_corpus_rollout import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
