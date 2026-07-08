"""Idempotent Voyage vector ingest for Dante visual-reference assets."""
from __future__ import annotations

import csv
import io
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from llama_index.core.schema import TextNode

from app.kb import MIME_BY_EXT
from app.providers import ProviderError

from .manifest import VisualAsset, resolve_inside, safe_relative_path, validate_run_id
from .safe_io import safe_write_text

DATASET_ID = "dante-visual-reference-assets"
VECTOR_INGEST_SCHEMA_VERSION = "dante_visual_vector_ingest.v1"


@dataclass
class VectorIngestRow:
    row_number: int
    image_id: str
    source_sha256: str
    category: str
    group: str
    new_relative_path: str
    status: str
    node_id: str = ""
    error: str = ""


@dataclass(frozen=True)
class VectorIngestSummary:
    schema_version: str
    run_id: str
    dataset_id: str
    total_selected: int
    existing_before: int
    embedded: int
    skipped_existing: int
    skipped_duplicate_in_run: int
    failed: int
    batch_size: int
    max_batch_bytes: int
    started_at: str
    finished_at: str


def collect_existing_source_hashes(kb: Any, *, dataset_id: str = DATASET_ID) -> set[str]:
    """Return already-ingested Dante visual SHA-256 values from Chroma metadata."""
    try:
        data = kb.collection.get(where={"dataset_id": dataset_id}, include=["metadatas"])
    except Exception:
        data = kb.collection.get(include=["metadatas"])
    hashes: set[str] = set()
    for meta in data.get("metadatas") or []:
        if not isinstance(meta, dict):
            continue
        if meta.get("dataset_id") != dataset_id:
            continue
        source_sha = meta.get("source_sha256")
        if isinstance(source_sha, str) and source_sha:
            hashes.add(source_sha)
    return hashes


def ingest_visual_vectors(
    kb: Any,
    assets: list[VisualAsset],
    *,
    asset_root: Path,
    manifest_run_dir: Path,
    run_id: str,
    limit: int | None = None,
    batch_size: int = 8,
    max_batch_bytes: int = 12 * 1024 * 1024,
    dataset_id: str = DATASET_ID,
    max_retries: int = 3,
) -> dict[str, object]:
    run_id = validate_run_id(run_id)
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if max_batch_bytes < 1:
        raise ValueError("max_batch_bytes must be >= 1")
    started_at = _utc_now()
    selected_assets = assets[:limit] if limit is not None else assets
    existing_hashes = collect_existing_source_hashes(kb, dataset_id=dataset_id)
    existing_before = len(existing_hashes)
    rows, queued = _plan_rows(selected_assets, existing_hashes)

    for batch in _iter_batches(queued, max_count=batch_size, max_bytes=max_batch_bytes):
        try:
            _embed_batch(
                kb,
                batch,
                asset_root=asset_root,
                run_id=run_id,
                dataset_id=dataset_id,
                existing_hashes=existing_hashes,
                max_retries=max_retries,
            )
        except Exception as exc:
            for asset, row in batch:
                row.status = "failed"
                row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            _write_run_artifacts(
                manifest_run_dir,
                rows,
                _summary(
                    run_id,
                    rows,
                    selected_assets,
                    existing_before,
                    batch_size,
                    max_batch_bytes,
                    started_at,
                    dataset_id,
                ),
            )
            raise
        for asset, row in batch:
            row.status = "embedded"
            row.node_id = node_id_for(asset)
        _write_run_artifacts(
            manifest_run_dir,
            rows,
            _summary(
                run_id,
                rows,
                selected_assets,
                existing_before,
                batch_size,
                max_batch_bytes,
                started_at,
                dataset_id,
            ),
        )

    summary = _summary(
        run_id,
        rows,
        selected_assets,
        existing_before,
        batch_size,
        max_batch_bytes,
        started_at,
        dataset_id,
    )
    _write_run_artifacts(manifest_run_dir, rows, summary)
    return {
        "summary": asdict(summary),
        "manifest_path": str((manifest_run_dir / "vector-ingest-manifest.tsv").resolve()),
        "summary_path": str((manifest_run_dir / "vector-ingest-summary.json").resolve()),
    }


def node_id_for(asset: VisualAsset) -> str:
    return f"dante_visual_img_{asset.sha256[:32]}"


def _plan_rows(
    assets: list[VisualAsset],
    existing_hashes: set[str],
) -> tuple[list[VectorIngestRow], list[tuple[VisualAsset, VectorIngestRow]]]:
    rows: list[VectorIngestRow] = []
    queued: list[tuple[VisualAsset, VectorIngestRow]] = []
    seen_in_run: set[str] = set()
    for asset in assets:
        status = "queued"
        if asset.sha256 in existing_hashes:
            status = "skipped_existing"
        elif asset.sha256 in seen_in_run:
            status = "skipped_duplicate_in_run"
        row = VectorIngestRow(
            row_number=asset.row_number,
            image_id=asset.image_id,
            source_sha256=asset.sha256,
            category=asset.category,
            group=asset.group,
            new_relative_path=asset.new_relative_path,
            status=status,
            node_id=node_id_for(asset) if status == "skipped_existing" else "",
        )
        rows.append(row)
        if status == "queued":
            queued.append((asset, row))
            seen_in_run.add(asset.sha256)
    return rows, queued


def _iter_batches(
    queued: list[tuple[VisualAsset, VectorIngestRow]],
    *,
    max_count: int,
    max_bytes: int,
) -> list[list[tuple[VisualAsset, VectorIngestRow]]]:
    batches: list[list[tuple[VisualAsset, VectorIngestRow]]] = []
    current: list[tuple[VisualAsset, VectorIngestRow]] = []
    current_bytes = 0
    for item in queued:
        asset, _row = item
        would_exceed_count = len(current) >= max_count
        would_exceed_bytes = current_bytes > 0 and current_bytes + asset.bytes > max_bytes
        if current and (would_exceed_count or would_exceed_bytes):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += asset.bytes
    if current:
        batches.append(current)
    return batches


def _embed_batch(
    kb: Any,
    batch: list[tuple[VisualAsset, VectorIngestRow]],
    *,
    asset_root: Path,
    run_id: str,
    dataset_id: str,
    existing_hashes: set[str],
    max_retries: int,
) -> None:
    payloads: list[tuple[bytes, str]] = []
    asset_paths: list[Path] = []
    for asset, _row in batch:
        relative_path = safe_relative_path(asset.new_relative_path, field_name="new_relative_path")
        asset_path = resolve_inside(asset_root, relative_path)
        asset_paths.append(asset_path)
        mime_type = MIME_BY_EXT.get(asset_path.suffix.lower(), "image/jpeg")
        payloads.append((asset_path.read_bytes(), mime_type))

    embeddings = _embed_with_retries(kb, payloads, max_retries=max_retries)
    nodes: list[TextNode] = []
    for (asset, _row), asset_path, embedding in zip(batch, asset_paths, embeddings, strict=True):
        nodes.append(
            TextNode(
                id_=node_id_for(asset),
                text=_node_text(asset),
                metadata=_node_metadata(asset, asset_path, run_id=run_id, dataset_id=dataset_id),
                embedding=_l2_normalize(embedding),
            )
        )
    kb.vector_store.add(nodes)
    for asset, _row in batch:
        existing_hashes.add(asset.sha256)


def _embed_with_retries(kb: Any, payloads: list[tuple[bytes, str]], *, max_retries: int) -> list[list[float]]:
    attempt = 0
    while True:
        try:
            if hasattr(kb.embedder, "embed_many_bytes"):
                return kb.embedder.embed_many_bytes(payloads, input_type="document")
            return [kb.embedder.embed_bytes(data, mime, input_type="document") for data, mime in payloads]
        except (ProviderError, httpx.HTTPError):
            attempt += 1
            if attempt > max_retries:
                raise
            time.sleep(min(2**attempt, 20))


def _node_text(asset: VisualAsset) -> str:
    return "\n".join(
        [
            "[Dante visual reference image]",
            f"Image ID: {asset.image_id}",
            f"Category: {asset.category}",
            f"Group: {asset.group}",
            f"Dimensions: {asset.width}x{asset.height}",
            f"Source path: {asset.new_relative_path}",
            "Use: commercial film production, cinematic reference, art direction, cinematography, editing, visual research.",
        ]
    )


def _node_metadata(asset: VisualAsset, asset_path: Path, *, run_id: str, dataset_id: str) -> dict[str, object]:
    return {
        "id": node_id_for(asset),
        "dataset_id": dataset_id,
        "source_sha256": asset.sha256,
        "original_name": asset.file_name,
        "file_path": str(asset_path.resolve()),
        "upload_time": _utc_now(),
        "file_size": asset.bytes,
        "modality": "image",
        "dante_image_id": asset.image_id,
        "category": asset.category,
        "group": asset.group,
        "new_relative_path": asset.new_relative_path,
        "width": asset.width,
        "height": asset.height,
        "run_id": run_id,
        "batch_or_note": asset.batch_or_note,
        "tags": f"{dataset_id},{asset.category},{asset.group},film-reference,visual-reference",
    }


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 0:
        return [float(value) for value in values]
    return [float(value) / norm for value in values]


def _write_run_artifacts(manifest_run_dir: Path, rows: list[VectorIngestRow], summary: VectorIngestSummary) -> None:
    safe_write_text(
        manifest_run_dir / "vector-ingest-manifest.tsv",
        _rows_to_tsv(rows),
        root=manifest_run_dir,
    )
    safe_write_text(
        manifest_run_dir / "vector-ingest-summary.json",
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        root=manifest_run_dir,
    )


def _rows_to_tsv(rows: list[VectorIngestRow]) -> str:
    output = io.StringIO()
    fields = [
        "row_number",
        "image_id",
        "source_sha256",
        "category",
        "group",
        "new_relative_path",
        "status",
        "node_id",
        "error",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    return output.getvalue()


def _summary(
    run_id: str,
    rows: list[VectorIngestRow],
    selected_assets: list[VisualAsset],
    existing_before: int,
    batch_size: int,
    max_batch_bytes: int,
    started_at: str,
    dataset_id: str,
) -> VectorIngestSummary:
    return VectorIngestSummary(
        schema_version=VECTOR_INGEST_SCHEMA_VERSION,
        run_id=run_id,
        dataset_id=dataset_id,
        total_selected=len(selected_assets),
        existing_before=existing_before,
        embedded=sum(1 for row in rows if row.status == "embedded"),
        skipped_existing=sum(1 for row in rows if row.status == "skipped_existing"),
        skipped_duplicate_in_run=sum(1 for row in rows if row.status == "skipped_duplicate_in_run"),
        failed=sum(1 for row in rows if row.status == "failed"),
        batch_size=batch_size,
        max_batch_bytes=max_batch_bytes,
        started_at=started_at,
        finished_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
