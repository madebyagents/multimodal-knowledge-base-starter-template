#!/usr/bin/env python3
"""Build Black Label post-Docling multimodal package plans."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))

from app.docling_black_label_package import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
