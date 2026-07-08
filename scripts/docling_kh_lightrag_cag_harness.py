#!/usr/bin/env python3
"""Run the post-Docling P0-P8 ingest/index dry-run harness."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))

from app.docling_kh_lightrag_cag_harness import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
