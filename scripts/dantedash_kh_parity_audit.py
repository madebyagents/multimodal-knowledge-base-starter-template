#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.deps import get_kb  # noqa: E402
from app.kb_parity import audit_kb, package_key_from_metadata, write_audit_manifests  # noqa: E402
from app.knowledge_hub_client import sanitize_public_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Chroma to Knowledge Hub parity audit.")
    parser.add_argument("--run-id", default="kh-parity-audit-local", help="Stable audit run id.")
    parser.add_argument(
        "--knowledge-hub-manifest",
        help="Optional JSON/CSV/TSV manifest with Knowledge Hub asset rows for matched/missing classification.",
    )
    parser.add_argument(
        "--require-knowledge-hub-manifest",
        action="store_true",
        help="Fail if --knowledge-hub-manifest is omitted.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "backend" / "runtime_reports" / "kh-parity"),
        help="Private output directory for audit manifests.",
    )
    parser.add_argument("--no-write", action="store_true", help="Print summary without writing manifests.")
    args = parser.parse_args()
    if args.require_knowledge_hub_manifest and not args.knowledge_hub_manifest:
        raise SystemExit("--knowledge-hub-manifest is required when --require-knowledge-hub-manifest is set")

    kb = get_kb()
    kh_keys = _read_manifest_keys(Path(args.knowledge_hub_manifest)) if args.knowledge_hub_manifest else None
    audit = audit_kb(kb, run_id=args.run_id, kh_package_keys=kh_keys)
    summary = {
        "generated_at": audit.generated_at,
        "run_id": audit.run_id,
        "total_rows": audit.total_rows,
        "by_modality": audit.by_modality,
        "by_class": audit.by_class,
        "by_kh_relationship": audit.by_kh_relationship,
        "by_vector_provenance": audit.by_vector_provenance,
    }
    if not args.no_write:
        summary["manifests"] = sanitize_public_payload(write_audit_manifests(audit, args.output_dir))

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _read_manifest_keys(path: Path) -> set[str]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {_manifest_key(item) for item in _json_rows(payload) if _manifest_key(item)}

    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open(newline="", encoding="utf-8") as fh:
        return {_manifest_key(row) for row in csv.DictReader(fh, delimiter=delimiter) if _manifest_key(row)}


def _json_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "items", "results", "data", "assets"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _manifest_key(row: dict[str, Any]) -> str:
    for field in ("source_sha256", "dante_image_id", "content_hash", "asset_id", "asset_identity", "relative_path"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return package_key_from_metadata(row)


if __name__ == "__main__":
    raise SystemExit(main())
