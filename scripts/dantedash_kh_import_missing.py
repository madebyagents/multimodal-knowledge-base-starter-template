#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.deps import get_kb, get_settings  # noqa: E402
from app.knowledge_hub_client import KnowledgeHubClient, sanitize_public_payload  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "backend" / "runtime_reports" / "kh-cutover"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import missing DanteDash package rows through the official KH API.")
    parser.add_argument("--audit-summary", help="Existing kh-parity-audit-summary.json with real KH comparison evidence.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--run-id", default="kh-missing-import-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--knowledge-hub-base-url", default="")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--execute", action="store_true", help="Post missing rows to the KH-owned package import endpoint.")
    args = parser.parse_args()

    if not args.audit_summary:
        raise SystemExit("--audit-summary is required so missing rows come from real KH comparison evidence")

    rows = _load_rows(Path(args.audit_summary))
    candidates = [
        row
        for row in rows
        if row.get("row_class") == "canonical" and row.get("kh_relationship") in {"missing_in_kh", "missing_layer_in_kh"}
    ]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    mode_name = "execute" if args.execute else "dry-run"
    manifest_path = out_dir / f"kh-missing-import-{mode_name}.tsv"
    summary_path = out_dir / f"kh-missing-import-{mode_name}-summary.json"

    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "node_id",
                "file_id",
                "modality",
                "artifact_type",
                "package_key",
                "planned_action",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        for row in candidates:
            writer.writerow(
                {
                    "node_id": row.get("node_id", ""),
                    "file_id": row.get("file_id", ""),
                    "modality": row.get("modality", ""),
                    "artifact_type": row.get("artifact_type", ""),
                    "package_key": row.get("package_key", ""),
                    "planned_action": "import_through_kh_dantedash_packages_api",
                }
            )
    manifest_path.chmod(0o600)

    by_modality = Counter(str(row.get("modality") or "unknown") for row in candidates)
    by_artifact = Counter(str(row.get("artifact_type") or "unknown") for row in candidates)
    execution = _execute_import(args, candidates) if args.execute and candidates else {
        "status": "skipped",
        "batch_count": 0,
        "imported_count": 0,
        "invalid_count": 0,
        "failed_count": 0,
        "mutation_performed": False,
    }
    summary = {
        "run_id": args.run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "dry_run": not args.execute,
        "execute_supported": True,
        "mutation_performed": bool(execution.get("mutation_performed")),
        "candidate_count": len(candidates),
        "candidate_relationships": dict(Counter(str(row.get("kh_relationship") or "unknown") for row in candidates)),
        "by_modality": dict(by_modality),
        "by_artifact_type": dict(by_artifact),
        "manifest": _display_path(manifest_path),
        "execution": execution,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.chmod(0o600)
    print(json.dumps(sanitize_public_payload(summary), indent=2, sort_keys=True))
    return 0


def _execute_import(args: argparse.Namespace, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    kh_base_url = (args.knowledge_hub_base_url or settings.knowledge_hub_base_url).rstrip("/")
    client = KnowledgeHubClient(
        base_url=kh_base_url,
        actions_base_url=settings.knowledge_hub_actions_base_url,
        actions_bearer_token=settings.knowledge_hub_actions_bearer_token,
        timeout_s=max(settings.knowledge_hub_timeout_s, 30.0),
    )
    kb = get_kb()
    node_ids = [str(row.get("node_id") or "") for row in candidates if row.get("node_id")]
    batches = list(_chunks(node_ids, max(1, int(args.batch_size))))
    imported_count = 0
    invalid_count = 0
    failed_count = 0
    batch_reports = []
    for batch_index, batch_ids in enumerate(batches, start=1):
        rows = _load_chroma_rows(kb, batch_ids)
        missing = sorted(set(batch_ids) - {row["node_id"] for row in rows})
        if missing:
            failed_count += len(missing)
        payload = {
            "run_id": args.run_id,
            "execute": True,
            "reset_collection": False,
            "rows": rows,
        }
        response = client.dantedash_import_packages(payload)
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        if not response.get("ok"):
            failed_count += len(rows)
            batch_reports.append(
                {
                    "batch": batch_index,
                    "status": "failed",
                    "row_count": len(rows),
                    "missing_from_chroma": len(missing),
                    "error": response.get("error") or "knowledge_hub_import_failed",
                }
            )
            continue
        status = str(data.get("status") or "unknown")
        if status != "indexed":
            failed_count += len(rows)
            invalid_count += int(data.get("invalid_count") or 0)
            batch_reports.append(
                {
                    "batch": batch_index,
                    "status": status,
                    "row_count": len(rows),
                    "missing_from_chroma": len(missing),
                    "error": data.get("error") or data.get("failure_stage") or "knowledge_hub_import_not_indexed",
                    "invalid_count": int(data.get("invalid_count") or 0),
                }
            )
            continue
        imported_count += int(data.get("indexed_count") or 0)
        invalid_count += int(data.get("invalid_count") or 0)
        batch_reports.append(
            {
                "batch": batch_index,
                "status": status,
                "row_count": len(rows),
                "indexed_count": int(data.get("indexed_count") or 0),
                "invalid_count": int(data.get("invalid_count") or 0),
                "missing_from_chroma": len(missing),
                "manifest_asset_count": data.get("manifest_asset_count"),
            }
        )
    client.close()
    return {
        "status": "indexed" if failed_count == 0 and invalid_count == 0 else "partial",
        "batch_count": len(batches),
        "imported_count": imported_count,
        "invalid_count": invalid_count,
        "failed_count": failed_count,
        "mutation_performed": imported_count > 0,
        "batches": batch_reports,
    }


def _load_chroma_rows(kb: Any, node_ids: list[str]) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    payload = kb.collection.get(ids=node_ids, include=["metadatas", "documents", "embeddings"])
    ids = [str(item) for item in payload.get("ids", [])]
    metadatas = payload.get("metadatas") or []
    documents = payload.get("documents") or []
    embeddings = payload.get("embeddings")
    if embeddings is None:
        embeddings = []
    rows = []
    for node_id, metadata, document, embedding in zip(ids, metadatas, documents, embeddings, strict=False):
        vector = _embedding_to_list(embedding)
        if not vector:
            continue
        rows.append(
            {
                "node_id": node_id,
                "document": document or "",
                "embedding": vector,
                "metadata": dict(metadata or {}),
            }
        )
    return rows


def _embedding_to_list(value: Any) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        return []
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return []


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "[redacted-local-path]"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"Audit summary has no rows: {path}")
    return [item for item in rows if isinstance(item, dict)]


if __name__ == "__main__":
    raise SystemExit(main())
