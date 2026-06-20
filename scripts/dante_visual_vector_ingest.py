#!/usr/bin/env python3
"""CLI for idempotent Voyage vector ingest of Dante visual-reference assets."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env")
sys.path.insert(0, str(ROOT / "backend"))

from app.dante_visual.manifest import load_visual_manifest, resolve_inside, safe_relative_path, validate_run_id  # noqa: E402
from app.dante_visual.vector_ingest import collect_existing_source_hashes, ingest_visual_vectors  # noqa: E402
from app.deps import get_kb  # noqa: E402

DEFAULT_VAULT_ROOT = Path("/Users/vidigal/Dante")
DEFAULT_DATASET_ROOT = Path("commercial-film-production-kb/13-visual-reference-assets")
DEFAULT_EXTERNAL_ASSET_ROOT = Path("/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--asset-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("preflight", help="Validate manifest and report current vector-ingest state")

    ingest_parser = subcommands.add_parser("ingest", help="Embed source images into the multimodal sidecar with Voyage")
    ingest_parser.add_argument("--limit", type=int, default=None)
    ingest_parser.add_argument("--batch-size", type=int, default=8)
    ingest_parser.add_argument("--max-batch-mb", type=float, default=12.0)

    args = parser.parse_args()
    run_id = validate_run_id(args.run_id or default_run_id())
    paths = resolve_paths(args.vault_root, args.dataset_root, run_id, args.asset_root)

    if args.command == "preflight":
        return cmd_preflight(paths)
    if args.command == "ingest":
        return cmd_ingest(
            paths,
            limit=args.limit,
            batch_size=args.batch_size,
            max_batch_mb=args.max_batch_mb,
        )
    raise AssertionError(f"Unhandled command: {args.command}")


def default_run_id() -> str:
    return datetime.now(UTC).strftime("visual-vector-%Y%m%dT%H%M%SZ")


def resolve_paths(vault_root: Path, dataset_root: Path, run_id: str, asset_root: Path | None) -> dict[str, Path]:
    vault_abs = vault_root.resolve()
    dataset_rel = safe_relative_path(str(dataset_root), field_name="dataset_root")
    dataset_abs = resolve_inside(vault_abs, dataset_rel)
    asset_abs = (asset_root or DEFAULT_EXTERNAL_ASSET_ROOT).expanduser().resolve()
    if not asset_abs.exists():
        asset_abs = dataset_abs / "source-assets"
    analysis_root = dataset_abs / "analysis-cards"
    manifest_run_dir = analysis_root / "manifests" / run_id
    return {
        "vault_root": vault_abs,
        "dataset_root": dataset_abs,
        "asset_root": asset_abs,
        "manifest_path": asset_abs / "asset-manifest.tsv",
        "manifest_run_dir": manifest_run_dir,
    }


def cmd_preflight(paths: dict[str, Path]) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    payload = {
        "manifest": manifest.summary(),
        "vector_ingest": {
            "existing_dante_visual_hashes": None,
            "kb_available": False,
        },
    }
    try:
        kb = get_kb()
        payload["vector_ingest"]["existing_dante_visual_hashes"] = len(collect_existing_source_hashes(kb))
        payload["vector_ingest"]["kb_available"] = True
        payload["vector_ingest"]["collection_total_vectors"] = kb.count()
        payload["vector_ingest"]["count_by_modality"] = kb.count_by_modality()
    except Exception as exc:  # noqa: BLE001
        payload["vector_ingest"]["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if manifest.is_valid and payload["vector_ingest"]["kb_available"] else 2


def cmd_ingest(paths: dict[str, Path], *, limit: int | None, batch_size: int, max_batch_mb: float) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    if not manifest.is_valid:
        print(json.dumps({"manifest": manifest.summary()}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    kb = get_kb()
    result = ingest_visual_vectors(
        kb,
        manifest.assets,
        asset_root=paths["asset_root"],
        manifest_run_dir=paths["manifest_run_dir"],
        run_id=paths["manifest_run_dir"].name,
        limit=limit,
        batch_size=batch_size,
        max_batch_bytes=int(max_batch_mb * 1024 * 1024),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
