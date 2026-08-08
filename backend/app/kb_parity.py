from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .knowledge_hub_client import sanitize_public_payload


SUPPORTED_MODALITIES = {"image", "text", "pdf", "video"}


@dataclass(frozen=True)
class KbParityRow:
    node_id: str
    file_id: str
    modality: str
    artifact_type: str
    package_key: str
    row_class: str
    kh_relationship: str
    vector_provenance: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class KbParityAudit:
    generated_at: str
    run_id: str
    total_rows: int
    by_modality: dict[str, int]
    by_class: dict[str, int]
    by_kh_relationship: dict[str, int]
    by_vector_provenance: dict[str, int]
    rows: list[KbParityRow]


def package_key_from_metadata(metadata: Mapping[str, Any] | None, node_id: str = "") -> str:
    meta = metadata or {}
    for field in (
        "source_sha256",
        "dante_image_id",
        "preview_image_file_id",
        "linked_image_file_id",
        "file_id",
        "id",
    ):
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return node_id


def package_layer_from_metadata(metadata: Mapping[str, Any] | None) -> str:
    meta = metadata or {}
    modality = (_first_text(meta, ("modality", "media_type")) or "unknown").lower()
    artifact_type = (_first_text(meta, ("artifact_type", "source_kind")) or "unknown").lower()
    return f"{modality}:{artifact_type}"


def vector_provenance_status(metadata: Mapping[str, Any] | None) -> str:
    meta = metadata or {}
    model = _first_text(meta, ("embedding_model", "embed_model", "embedding_provider_model", "model"))
    dimensions = meta.get("embedding_dimensions") or meta.get("embedding_dim") or meta.get("dimensions")
    has_source = bool(_first_text(meta, ("source_sha256", "file_id", "dante_image_id")))
    has_modality = bool(_first_text(meta, ("modality",)))

    if model and "voyage" in model.lower() and _as_int(dimensions) == 1024 and has_source and has_modality:
        return "verified"
    if model or dimensions or has_source:
        return "partial"
    return "embedding_provenance_unknown"


def classify_rows(
    ids: Sequence[str],
    metadatas: Sequence[Mapping[str, Any] | None],
    kh_package_keys: Iterable[str] | None = None,
    kh_package_layers: Mapping[str, Iterable[str]] | None = None,
) -> list[KbParityRow]:
    kh_keys = {key for key in (kh_package_keys or []) if key}
    kh_layers = {
        str(package_key): {str(layer) for layer in layers if layer}
        for package_key, layers in (kh_package_layers or {}).items()
        if package_key
    }
    file_ids = set(ids)
    for meta in metadatas:
        if not meta:
            continue
        for field in ("file_id", "id"):
            value = meta.get(field)
            if isinstance(value, str) and value:
                file_ids.add(value)
    node_counts = Counter(ids)

    rows: list[KbParityRow] = []
    for node_id, raw_meta in zip(ids, metadatas, strict=False):
        meta = raw_meta or {}
        file_id = _first_text(meta, ("file_id", "id")) or node_id
        modality = (_first_text(meta, ("modality",)) or "unknown").lower()
        artifact_type = _first_text(meta, ("artifact_type",)) or "unknown"
        package_key = package_key_from_metadata(meta, node_id)
        row_class, reasons = _classify_row(node_id, meta, file_ids, node_counts[node_id])
        kh_relationship = _kh_relationship(
            package_key=package_key,
            layer_key=package_layer_from_metadata(meta),
            kh_keys=kh_keys,
            kh_layers=kh_layers,
        )
        rows.append(
            KbParityRow(
                node_id=node_id,
                file_id=file_id,
                modality=modality,
                artifact_type=artifact_type,
                package_key=package_key,
                row_class=row_class,
                kh_relationship=kh_relationship,
                vector_provenance=vector_provenance_status(meta),
                reasons=tuple(reasons),
            )
        )
    return rows


def audit_kb(
    kb: Any,
    *,
    run_id: str,
    kh_package_keys: Iterable[str] | None = None,
    kh_package_layers: Mapping[str, Iterable[str]] | None = None,
) -> KbParityAudit:
    collection_payload = kb.collection.get(include=["metadatas"])
    ids = [str(item) for item in collection_payload.get("ids", [])]
    metadatas = collection_payload.get("metadatas", [])
    rows = classify_rows(ids, metadatas, kh_package_keys=kh_package_keys, kh_package_layers=kh_package_layers)
    by_modality = _safe_count_by_modality(kb, rows)

    return KbParityAudit(
        generated_at=datetime.now(UTC).isoformat(),
        run_id=run_id,
        total_rows=len(rows),
        by_modality=by_modality,
        by_class=dict(Counter(row.row_class for row in rows)),
        by_kh_relationship=dict(Counter(row.kh_relationship for row in rows)),
        by_vector_provenance=dict(Counter(row.vector_provenance for row in rows)),
        rows=rows,
    )


def write_audit_manifests(audit: KbParityAudit, output_dir: str | Path) -> dict[str, str]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    summary_path = out_dir / "kh-parity-audit-summary.json"
    manifest_path = out_dir / "kh-parity-audit-manifest.tsv"

    summary_payload = asdict(audit)
    summary_payload["rows"] = [_row_public_dict(row) for row in audit.rows]
    _write_private_json(summary_path, summary_payload)

    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "node_id",
                "file_id",
                "modality",
                "artifact_type",
                "package_key",
                "row_class",
                "kh_relationship",
                "vector_provenance",
                "reasons",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        for row in audit.rows:
            payload = _row_public_dict(row)
            payload["reasons"] = ",".join(row.reasons)
            writer.writerow(payload)
    manifest_path.chmod(0o600)

    return {"summary": str(summary_path), "manifest": str(manifest_path)}


def evaluate_result_parity(
    chroma_results: Sequence[Mapping[str, Any]],
    knowledge_hub_results: Sequence[Mapping[str, Any]],
    *,
    min_asset_overlap: float = 0.8,
) -> dict[str, Any]:
    chroma_keys = {_result_package_key(item) for item in chroma_results}
    kh_keys = {_result_package_key(item) for item in knowledge_hub_results}
    chroma_keys.discard("")
    kh_keys.discard("")
    overlap = chroma_keys & kh_keys
    recall = len(overlap) / len(chroma_keys) if chroma_keys else 1.0
    precision = len(overlap) / len(kh_keys) if kh_keys else 1.0 if not chroma_keys else 0.0

    return {
        "chroma_assets": len(chroma_keys),
        "knowledge_hub_assets": len(kh_keys),
        "overlap_assets": len(overlap),
        "asset_recall": recall,
        "asset_precision": precision,
        "threshold": min_asset_overlap,
        "passed": recall >= min_asset_overlap,
        "missing_from_knowledge_hub": sorted(chroma_keys - kh_keys),
        "extra_in_knowledge_hub": sorted(kh_keys - chroma_keys),
    }


def _classify_row(
    node_id: str,
    metadata: Mapping[str, Any],
    file_ids: set[str],
    node_count: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    modality = (_first_text(metadata, ("modality",)) or "unknown").lower()

    if _truthy(metadata.get("accepted_exclusion")):
        return "accepted_exclusion", ["explicit_accepted_exclusion"]
    if node_count > 1:
        return "duplicate", ["duplicate_node_id"]
    if _truthy(metadata.get("duplicate_of")):
        return "duplicate", ["explicit_duplicate_of"]
    if _truthy(metadata.get("stale")) or _truthy(metadata.get("deprecated")):
        return "stale", ["explicit_stale_or_deprecated"]
    if modality not in SUPPORTED_MODALITIES:
        return "unsupported", [f"unsupported_modality:{modality}"]

    for link_field in ("linked_image_file_id", "preview_image_file_id"):
        linked = _first_text(metadata, (link_field,))
        if linked and linked not in file_ids:
            reasons.append(f"missing_{link_field}")
    if reasons:
        return "orphaned", reasons

    return "canonical", ["canonical_candidate"]


def _kh_relationship(
    *,
    package_key: str,
    layer_key: str,
    kh_keys: set[str],
    kh_layers: Mapping[str, set[str]],
) -> str:
    if kh_layers:
        layers = kh_layers.get(package_key)
        if layers is None:
            return "missing_in_kh"
        return "matched" if layer_key in layers else "missing_layer_in_kh"
    if not kh_keys:
        return "not_compared"
    return "matched" if package_key in kh_keys else "missing_in_kh"


def _row_public_dict(row: KbParityRow) -> dict[str, Any]:
    return sanitize_public_payload(asdict(row))


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _first_text(metadata: Mapping[str, Any], fields: Sequence[str]) -> str:
    for field in fields:
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _safe_count_by_modality(kb: Any, rows: Sequence[KbParityRow]) -> dict[str, int]:
    try:
        return dict(kb.count_by_modality())
    except Exception:
        return dict(Counter(row.modality for row in rows))


def _result_package_key(result: Mapping[str, Any]) -> str:
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        key = package_key_from_metadata(metadata)
        if key:
            return key
    return package_key_from_metadata(result)
