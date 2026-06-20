#!/usr/bin/env python3
"""Ingest Dante visual-analysis cards as linked searchable bundles."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.dante_visual.card_ingest import VisualCardBundle, ingest_visual_card_bundles  # noqa: E402
from app.dante_visual.cards import read_card  # noqa: E402
from app.dante_visual.manifest import validate_run_id  # noqa: E402
from app.deps import get_kb  # noqa: E402
from dante_visual_analysis_harness import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    DEFAULT_VAULT_ROOT,
    resolve_paths,
)


DEFAULT_SOURCE_RUN_ID = "visual-gemini-batch100-stratified-compressed-20260613-codex"
DEFAULT_RUN_ID = "visual-card-bundle-ingest-batch100-20260614-codex"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--source-run-id", default=DEFAULT_SOURCE_RUN_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    source_run_id = validate_run_id(args.source_run_id)
    run_id = validate_run_id(args.run_id)
    source_paths = resolve_paths(args.vault_root, args.dataset_root, source_run_id)
    ingest_paths = resolve_paths(args.vault_root, args.dataset_root, run_id)
    manifest_path = source_paths["manifest_run_dir"] / "analysis-manifest.tsv"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)

    bundles = load_bundles_from_manifest(
        manifest_path,
        analysis_root=source_paths["analysis_root"],
    )
    kb = get_kb()
    result = ingest_visual_card_bundles(
        kb,
        bundles,
        manifest_run_dir=ingest_paths["manifest_run_dir"],
        run_id=run_id,
        source_run_id=source_run_id,
        force=args.force,
        max_retries=args.max_retries,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["failed"] == 0 and result["summary"]["missing_linked_image"] == 0 else 1


def load_bundles_from_manifest(manifest_path: Path, *, analysis_root: Path) -> list[VisualCardBundle]:
    rows = list(csv.DictReader(manifest_path.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    bundles: list[VisualCardBundle] = []
    seen_source_hashes: set[str] = set()
    for row in rows:
        if row.get("error"):
            continue
        image_id = str(row.get("image_id") or "").strip()
        if not image_id:
            continue
        card_json_rel = str(row.get("card_json") or "").strip()
        card_md_rel = str(row.get("card_markdown") or "").strip()
        if not card_json_rel or not card_md_rel:
            continue
        card_json_path = (analysis_root / card_json_rel).resolve()
        card_markdown_path = (analysis_root / card_md_rel).resolve()
        if not card_json_path.exists():
            raise FileNotFoundError(card_json_path)
        if not card_markdown_path.exists():
            raise FileNotFoundError(card_markdown_path)
        card = read_card(card_json_path)
        source = card["source"]
        asset = card["asset"]
        source_sha256 = str(source["sha256"])
        if source_sha256 in seen_source_hashes:
            continue
        bundles.append(
            VisualCardBundle(
                image_id=image_id,
                source_sha256=source_sha256,
                category=str(source["category"]),
                group=str(source["group"]),
                image_relative_path=str(source["new_relative_path"]),
                image_file_name=str(asset["file_name"]),
                image_width=int(source["width"]),
                image_height=int(source["height"]),
                card_json_path=card_json_path,
                card_markdown_path=card_markdown_path,
                card_json_relative_path=card_json_rel,
                card_markdown_relative_path=card_md_rel,
                card_run_id=str(card["run_id"]),
                card=card,
                markdown=card_markdown_path.read_text(encoding="utf-8", errors="replace"),
            )
        )
        seen_source_hashes.add(source_sha256)
    return bundles


if __name__ == "__main__":
    raise SystemExit(main())
