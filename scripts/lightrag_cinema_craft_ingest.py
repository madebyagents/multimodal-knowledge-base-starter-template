#!/usr/bin/env python3
"""Run guarded LightRAG cinema craft ingest."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.lightrag_cinema_craft_ingest import ingest_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(ingest_main())
