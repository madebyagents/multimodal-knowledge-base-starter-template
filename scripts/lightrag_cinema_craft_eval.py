#!/usr/bin/env python3
"""Run LightRAG cinema craft retrieval evals."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.lightrag_cinema_craft_ingest import eval_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(eval_main())
