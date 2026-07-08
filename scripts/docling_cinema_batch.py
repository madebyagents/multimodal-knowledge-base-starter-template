#!/usr/bin/env python3
"""Plan and run manifest-first Docling batches for external cinema PDFs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.docling_cinema_batch import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
