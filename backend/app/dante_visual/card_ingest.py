"""Idempotent ingest for Dante visual-analysis card bundles."""
from __future__ import annotations

import csv
import hashlib
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

from app.providers import ProviderError

from .safe_io import safe_write_text
from .vector_ingest import DATASET_ID

CARD_INGEST_SCHEMA_VERSION = "dante_visual_card_ingest.v1"
CARD_ARTIFACT_TYPE = "visual_analysis_bundle"


@dataclass(frozen=True)
class VisualCardBundle:
    image_id: str
    source_sha256: str
    category: str
    group: str
    image_relative_path: str
    image_file_name: str
    image_width: int
    image_height: int
    card_json_path: Path
    card_markdown_path: Path
    card_json_relative_path: str
    card_markdown_relative_path: str
    card_run_id: str
    card: dict[str, Any]
    markdown: str


@dataclass
class CardIngestRow:
    row_number: int
    image_id: str
    source_sha256: str
    category: str
    group: str
    status: str
    node_id: str
    linked_image_node_id: str
    card_json_relative_path: str
    card_markdown_relative_path: str
    error: str = ""


@dataclass(frozen=True)
class CardIngestSummary:
    schema_version: str
    run_id: str
    source_run_id: str
    dataset_id: str
    artifact_type: str
    total_selected: int
    embedded: int
    skipped_existing: int
    missing_linked_image: int
    failed: int
    force: bool
    started_at: str
    finished_at: str


def card_node_id_for(source_sha256: str) -> str:
    return f"dante_visual_card_{source_sha256[:32]}"


def collect_existing_card_node_ids(kb: Any, *, dataset_id: str = DATASET_ID) -> set[str]:
    try:
        data = kb.collection.get(where={"artifact_type": CARD_ARTIFACT_TYPE}, include=["metadatas"])
    except Exception:
        data = kb.collection.get(include=["metadatas"])
    ids = data.get("ids") or []
    metas = data.get("metadatas") or []
    existing: set[str] = set()
    for node_id, meta in zip(ids, metas, strict=False):
        meta = meta or {}
        if meta.get("dataset_id") == dataset_id and meta.get("artifact_type") == CARD_ARTIFACT_TYPE:
            existing.add(str(node_id))
    return existing


def ingest_visual_card_bundles(
    kb: Any,
    bundles: list[VisualCardBundle],
    *,
    manifest_run_dir: Path,
    run_id: str,
    source_run_id: str,
    force: bool = False,
    dataset_id: str = DATASET_ID,
    max_retries: int = 3,
) -> dict[str, object]:
    started_at = _utc_now()
    existing_card_ids = collect_existing_card_node_ids(kb, dataset_id=dataset_id)
    rows: list[CardIngestRow] = []
    queued: list[tuple[VisualCardBundle, CardIngestRow]] = []

    if force:
        candidate_ids = [card_node_id_for(bundle.source_sha256) for bundle in bundles]
        if candidate_ids:
            kb.collection.delete(ids=candidate_ids)
        existing_card_ids.difference_update(candidate_ids)

    for index, bundle in enumerate(bundles, 1):
        node_id = card_node_id_for(bundle.source_sha256)
        linked_image_node_id = node_id_for_source_hash(bundle.source_sha256)
        status = "queued"
        error = ""
        if node_id in existing_card_ids:
            status = "skipped_existing"
        elif not _node_exists(kb, linked_image_node_id):
            status = "missing_linked_image"
            error = f"Missing linked image node: {linked_image_node_id}"
        row = CardIngestRow(
            row_number=index,
            image_id=bundle.image_id,
            source_sha256=bundle.source_sha256,
            category=bundle.category,
            group=bundle.group,
            status=status,
            node_id=node_id,
            linked_image_node_id=linked_image_node_id,
            card_json_relative_path=bundle.card_json_relative_path,
            card_markdown_relative_path=bundle.card_markdown_relative_path,
            error=error,
        )
        rows.append(row)
        if status == "queued":
            queued.append((bundle, row))

    for bundle, row in queued:
        try:
            text = build_card_bundle_text(bundle)
            embedding = _embed_text_with_retries(kb, text, max_retries=max_retries)
            node = TextNode(
                id_=row.node_id,
                text=text,
                metadata=_bundle_metadata(
                    bundle,
                    node_id=row.node_id,
                    linked_image_node_id=row.linked_image_node_id,
                    run_id=run_id,
                    source_run_id=source_run_id,
                    dataset_id=dataset_id,
                ),
                embedding=_l2_normalize(embedding),
            )
            kb.vector_store.add([node])
            row.status = "embedded"
        except Exception as exc:
            row.status = "failed"
            row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        _write_run_artifacts(
            manifest_run_dir,
            rows,
            _summary(
                rows,
                run_id=run_id,
                source_run_id=source_run_id,
                dataset_id=dataset_id,
                force=force,
                started_at=started_at,
            ),
        )

    summary = _summary(
        rows,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        force=force,
        started_at=started_at,
    )
    _write_run_artifacts(manifest_run_dir, rows, summary)
    return {
        "summary": asdict(summary),
        "manifest_path": str((manifest_run_dir / "card-ingest-manifest.tsv").resolve()),
        "summary_path": str((manifest_run_dir / "card-ingest-summary.json").resolve()),
    }


def node_id_for_source_hash(source_sha256: str) -> str:
    return f"dante_visual_img_{source_sha256[:32]}"


def build_card_bundle_text(bundle: VisualCardBundle) -> str:
    card = bundle.card
    analysis = card.get("normalized_analysis") or {}
    judgment = card.get("editorial_judgment") or {}
    compact_json = {
        "image_id": card.get("image_id"),
        "run_id": card.get("run_id"),
        "source": card.get("source"),
        "asset": card.get("asset"),
        "normalized_analysis": analysis,
        "editorial_judgment": judgment,
        "review_assets": card.get("review_assets"),
        "technical_visual_qc": card.get("technical_visual_qc"),
        "continuity_qc": card.get("continuity_qc"),
        "ai_artifact_qc": card.get("ai_artifact_qc"),
        "product_brand_qc": card.get("product_brand_qc"),
        "text_in_frame": card.get("text_in_frame"),
        "skill_kb": card.get("skill_kb"),
    }
    parts = [
        "[Dante visual analysis bundle]",
        f"Image ID: {bundle.image_id}",
        f"Category: {bundle.category}",
        f"Group: {bundle.group}",
        f"Image: {bundle.image_relative_path}",
        f"Markdown card: {bundle.card_markdown_relative_path}",
        f"JSON card: {bundle.card_json_relative_path}",
        f"Card run: {bundle.card_run_id}",
        f"Judgment: score={judgment.get('score')} tier={judgment.get('tier')} recommendation={judgment.get('recommendation')}",
        "",
        "## Searchable visual fields",
        _analysis_line("Subject", analysis, "subject"),
        _analysis_line("Shot size", analysis, "shot_size"),
        _analysis_line("Composition", analysis, "composition"),
        _analysis_line("Lighting", analysis, "lighting"),
        _analysis_line("Texture", analysis, "texture"),
        _analysis_line("Emotion", analysis, "emotion"),
        _analysis_line("Narrative use", analysis, "narrative_use"),
        _analysis_line("Color palette", analysis, "color_palette"),
        _analysis_line("Cinematography notes", analysis, "cinematography_notes"),
        _analysis_line("Direction references", analysis, "direction_references"),
        _analysis_line("Director opinion", analysis, "director_opinion"),
        _analysis_line("DOP/art director opinion", analysis, "dop_art_director_opinion"),
        _analysis_line("Additional read", analysis, "additional_read"),
        _analysis_line("Visual tags", analysis, "visual_tags"),
        "",
        "## Markdown card",
        bundle.markdown.strip(),
        "",
        "## Compact JSON card",
        json.dumps(compact_json, ensure_ascii=False, sort_keys=True),
    ]
    return "\n".join(part for part in parts if part is not None)


def _analysis_line(label: str, analysis: dict[str, Any], key: str) -> str:
    return f"- {label}: {_field_value(analysis.get(key))}"


def _field_value(value: Any) -> str:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _bundle_metadata(
    bundle: VisualCardBundle,
    *,
    node_id: str,
    linked_image_node_id: str,
    run_id: str,
    source_run_id: str,
    dataset_id: str,
) -> dict[str, object]:
    tags = [
        dataset_id,
        CARD_ARTIFACT_TYPE,
        bundle.category,
        bundle.group,
        "visual-analysis-card",
        "gemini",
    ]
    return {
        "id": node_id,
        "dataset_id": dataset_id,
        "artifact_type": CARD_ARTIFACT_TYPE,
        "source_sha256": bundle.source_sha256,
        "original_name": f"{bundle.image_id} visual analysis",
        "file_path": str(bundle.card_markdown_path.resolve()),
        "upload_time": _utc_now(),
        "file_size": bundle.card_markdown_path.stat().st_size,
        "modality": "text",
        "dante_image_id": bundle.image_id,
        "linked_image_file_id": linked_image_node_id,
        "preview_image_file_id": linked_image_node_id,
        "card_json_path": str(bundle.card_json_path.resolve()),
        "card_markdown_path": str(bundle.card_markdown_path.resolve()),
        "card_json_relative_path": bundle.card_json_relative_path,
        "card_markdown_relative_path": bundle.card_markdown_relative_path,
        "image_relative_path": bundle.image_relative_path,
        "image_file_name": bundle.image_file_name,
        "category": bundle.category,
        "group": bundle.group,
        "width": bundle.image_width,
        "height": bundle.image_height,
        "run_id": run_id,
        "source_run_id": source_run_id,
        "card_run_id": bundle.card_run_id,
        "card_json_sha256": _file_sha256(bundle.card_json_path),
        "card_markdown_sha256": _file_sha256(bundle.card_markdown_path),
        "tags": ",".join(tags),
    }


def _node_exists(kb: Any, node_id: str) -> bool:
    data = kb.collection.get(ids=[node_id], include=["metadatas"])
    return bool(data.get("ids"))


def _embed_text_with_retries(kb: Any, text: str, *, max_retries: int) -> list[float]:
    attempt = 0
    while True:
        try:
            if hasattr(kb, "_embed_text"):
                return kb._embed_text(text, input_type="document")
            return kb.embedder.embed_text(text, input_type="document")
        except (ProviderError, httpx.HTTPError):
            attempt += 1
            if attempt > max_retries:
                raise
            time.sleep(min(2**attempt, 20))


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 0:
        return [float(value) for value in values]
    return [float(value) / norm for value in values]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_run_artifacts(manifest_run_dir: Path, rows: list[CardIngestRow], summary: CardIngestSummary) -> None:
    safe_write_text(
        manifest_run_dir / "card-ingest-manifest.tsv",
        _rows_to_tsv(rows),
        root=manifest_run_dir,
    )
    safe_write_text(
        manifest_run_dir / "card-ingest-summary.json",
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        root=manifest_run_dir,
    )


def _rows_to_tsv(rows: list[CardIngestRow]) -> str:
    output = io.StringIO()
    fields = [
        "row_number",
        "image_id",
        "source_sha256",
        "category",
        "group",
        "status",
        "node_id",
        "linked_image_node_id",
        "card_json_relative_path",
        "card_markdown_relative_path",
        "error",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    return output.getvalue()


def _summary(
    rows: list[CardIngestRow],
    *,
    run_id: str,
    source_run_id: str,
    dataset_id: str,
    force: bool,
    started_at: str,
) -> CardIngestSummary:
    return CardIngestSummary(
        schema_version=CARD_INGEST_SCHEMA_VERSION,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        artifact_type=CARD_ARTIFACT_TYPE,
        total_selected=len(rows),
        embedded=sum(1 for row in rows if row.status == "embedded"),
        skipped_existing=sum(1 for row in rows if row.status == "skipped_existing"),
        missing_linked_image=sum(1 for row in rows if row.status == "missing_linked_image"),
        failed=sum(1 for row in rows if row.status == "failed"),
        force=force,
        started_at=started_at,
        finished_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
