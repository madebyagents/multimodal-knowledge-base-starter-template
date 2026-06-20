#!/usr/bin/env python3
"""Regenerate the Dante visual-analysis contact sheet."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from dante_visual_analysis_harness import main  # noqa: E402


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        sys.argv = [sys.argv[0], *argv, "contact-sheet"]
    raise SystemExit(main())
