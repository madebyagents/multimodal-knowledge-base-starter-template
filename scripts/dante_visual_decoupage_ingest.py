#!/usr/bin/env python3
"""Promote and ingest Dante premium decoupage bundles as linked Chroma nodes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.dante_visual.decoupage_ingest import (  # noqa: E402
    EXPECTED_TARGET_COUNT,
    ingest_decoupage_bundles,
    load_canonical_decoupage_bundles,
    promote_decoupage_run,
    selected_source_hashes_from_source_summary,
)
from app.dante_visual.manifest import load_visual_manifest, validate_run_id  # noqa: E402
from app.deps import get_kb  # noqa: E402
from dante_visual_analysis_harness import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    DEFAULT_VAULT_ROOT,
)
from dante_visual_decoupage_harness import resolve_paths as resolve_decoupage_paths  # noqa: E402

DEFAULT_SOURCE_RUN_ID = "visual-decoupage-gemini31-production-20260616-codex"
DEFAULT_RUN_ID = "visual-decoupage-ingest-20260616-codex"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--source-run-id", default=DEFAULT_SOURCE_RUN_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--promote-only", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args()

    if args.promote_only and args.ingest_only:
        raise ValueError("--promote-only and --ingest-only are mutually exclusive")

    source_run_id = validate_run_id(args.source_run_id)
    run_id = validate_run_id(args.run_id)
    vault_root = args.vault_root.resolve()
    dataset_root = normalize_dataset_root(vault_root, args.dataset_root)
    source_paths = resolve_decoupage_paths(vault_root, dataset_root, source_run_id)
    ingest_paths = resolve_decoupage_paths(vault_root, dataset_root, run_id)

    manifest = load_visual_manifest(source_paths["manifest_path"], source_paths["asset_root"])
    if not manifest.is_valid:
        payload = {"manifest": manifest.summary(), "issues": [issue.__dict__ for issue in manifest.issues]}
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    result: dict[str, object] = {
        "source_run_id": source_run_id,
        "run_id": run_id,
        "manifest_summary": manifest.summary(),
    }
    if not args.ingest_only:
        promotion = promote_decoupage_run(
            source_run_dir=source_paths["decoupage_manifest_run_dir"],
            canonical_sidecars_root=ingest_paths["decoupage_sidecars_root"],
            canonical_markdown_root=ingest_paths["decoupage_markdown_root"],
            analysis_root=ingest_paths["analysis_root"],
            manifest_run_dir=ingest_paths["decoupage_manifest_run_dir"],
            assets=manifest.assets,
            source_run_id=source_run_id,
            run_id=run_id,
        )
        result["promotion"] = promotion
        promotion_summary = promotion["summary"]
        if has_promotion_errors(promotion_summary):
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
    if args.promote_only:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    selected_hashes = selected_source_hashes_from_source_summary(
        source_paths["decoupage_manifest_run_dir"],
        source_run_id=source_run_id,
    )
    if len(selected_hashes) != EXPECTED_TARGET_COUNT:
        result["selected_source_hash_count"] = len(selected_hashes)
        result["error"] = f"Expected {EXPECTED_TARGET_COUNT} source hashes, found {len(selected_hashes)}"
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    bundles = load_canonical_decoupage_bundles(
        assets=manifest.assets,
        analysis_root=ingest_paths["analysis_root"],
        canonical_sidecars_root=ingest_paths["decoupage_sidecars_root"],
        canonical_markdown_root=ingest_paths["decoupage_markdown_root"],
        source_run_id=source_run_id,
        selected_source_sha256=selected_hashes,
    )
    result["bundle_count"] = len(bundles)
    result["selected_source_hash_count"] = len(selected_hashes)
    if len(bundles) != len(selected_hashes):
        result["error"] = f"Expected {len(selected_hashes)} canonical bundles, found {len(bundles)}"
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    kb = get_kb()
    ingest = ingest_decoupage_bundles(
        kb,
        bundles,
        manifest_run_dir=ingest_paths["decoupage_manifest_run_dir"],
        run_id=run_id,
        source_run_id=source_run_id,
        force=args.force,
        max_retries=args.max_retries,
    )
    result["ingest"] = ingest
    print(json.dumps(result, indent=2, sort_keys=True))
    summary = ingest["summary"]
    return 0 if summary["failed"] == 0 and summary["missing_linked_image"] == 0 else 1


def normalize_dataset_root(vault_root: Path, dataset_root: Path) -> Path:
    if dataset_root.is_absolute():
        return dataset_root.resolve().relative_to(vault_root.resolve())
    return dataset_root


def has_promotion_errors(summary: object) -> bool:
    if not isinstance(summary, dict):
        return True
    return any(
        int(summary.get(key, 0)) > 0
        for key in ("missing_source_file", "invalid_binding", "missing_manifest_asset", "failed")
    )


if __name__ == "__main__":
    raise SystemExit(main())
