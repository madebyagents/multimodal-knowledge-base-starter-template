"""Idempotent ingest for premium Dante decoupage bundles."""
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

from .decoupage import DECOUPAGE_PROFILE_ID, DECOUPAGE_SCHEMA_NAME
from .manifest import VisualAsset
from .safe_io import safe_write_text
from .vector_ingest import DATASET_ID

DECOUPAGE_INGEST_SCHEMA_VERSION = "dante_visual_decoupage_ingest.v1"
DECOUPAGE_ARTIFACT_TYPE = "visual_decoupage_bundle"
DECOUPAGE_PROVIDER = "gemini"
DECOUPAGE_MODEL = "gemini-3.1-pro-preview"
DECOUPAGE_SOURCE_API_SURFACE = "Gemini Developer API"
DECOUPAGE_NODE_PREFIX = "dante_visual_decoupage_"
EXPECTED_TARGET_COUNT = 2093
EXPECTED_THRESHOLD = 0.87

SEARCHABLE_FIELDS = (
    "one_line",
    "decoupage_spine",
    "composition",
    "camera_lens",
    "lighting",
    "color",
    "art_direction",
    "costume",
    "performance",
    "registers",
    "lineage",
    "distinction",
    "grounding",
    "proactive_adjacencies",
    "opinion",
)


@dataclass(frozen=True)
class DecoupageBundle:
    image_id: str
    source_sha256: str
    category: str
    group: str
    image_relative_path: str
    image_file_name: str
    image_width: int
    image_height: int
    sidecar_json_path: Path
    markdown_path: Path
    sidecar_json_relative_path: str
    markdown_relative_path: str
    source_run_id: str
    sidecar: dict[str, Any]
    markdown: str


@dataclass
class PromotionRow:
    row_number: int
    image_id: str
    source_sha256: str
    category: str
    group: str
    status: str
    source_json_path: str
    source_markdown_path: str
    canonical_json_relative_path: str
    canonical_markdown_relative_path: str
    json_action: str = ""
    markdown_action: str = ""
    json_backup_path: str = ""
    markdown_backup_path: str = ""
    source_json_sha256: str = ""
    source_markdown_sha256: str = ""
    previous_json_sha256: str = ""
    previous_markdown_sha256: str = ""
    error: str = ""


@dataclass(frozen=True)
class PromotionSummary:
    schema_version: str
    run_id: str
    source_run_id: str
    dataset_id: str
    artifact_type: str
    total_selected: int
    promoted: int
    already_same: int
    backed_up_replaced: int
    missing_source_file: int
    invalid_binding: int
    missing_manifest_asset: int
    failed: int
    started_at: str
    finished_at: str


@dataclass
class DecoupageIngestRow:
    row_number: int
    image_id: str
    source_sha256: str
    category: str
    group: str
    status: str
    node_id: str
    linked_image_node_id: str
    decoupage_json_relative_path: str
    decoupage_markdown_relative_path: str
    error: str = ""


@dataclass(frozen=True)
class DecoupageIngestSummary:
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


def decoupage_node_id_for(source_sha256: str) -> str:
    return f"{DECOUPAGE_NODE_PREFIX}{source_sha256[:32]}"


def image_node_id_for_source_hash(source_sha256: str) -> str:
    return f"dante_visual_img_{source_sha256[:32]}"


def validate_source_run_summary(run_dir: Path, *, source_run_id: str) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected: dict[str, Any] = {
        "final": True,
        "provider": DECOUPAGE_PROVIDER,
        "api_surface": DECOUPAGE_SOURCE_API_SURFACE,
        "uses_vertex": False,
        "model": DECOUPAGE_MODEL,
        "target_count": EXPECTED_TARGET_COUNT,
        "ok_count": EXPECTED_TARGET_COUNT,
        "error_count": 0,
        "threshold": EXPECTED_THRESHOLD,
        "pass": True,
    }
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        actual = summary.get(key)
        if isinstance(expected_value, float):
            try:
                if abs(float(actual) - expected_value) > 0.00001:
                    mismatches.append(f"{key}={actual!r}")
            except (TypeError, ValueError):
                mismatches.append(f"{key}={actual!r}")
        elif actual != expected_value:
            mismatches.append(f"{key}={actual!r}")
    average = summary.get("average_confidence_overall")
    try:
        if float(average) < EXPECTED_THRESHOLD:
            mismatches.append(f"average_confidence_overall={average!r}")
    except (TypeError, ValueError):
        mismatches.append(f"average_confidence_overall={average!r}")
    if run_dir.name != source_run_id:
        mismatches.append(f"run_dir.name={run_dir.name!r}")
    results = summary.get("results")
    if not isinstance(results, list):
        mismatches.append("results=<not a list>")
    elif len(results) != EXPECTED_TARGET_COUNT:
        mismatches.append(f"results_count={len(results)!r}")
    else:
        for index, row in enumerate(results, 1):
            if not isinstance(row, dict):
                mismatches.append(f"results[{index}]=<not an object>")
                continue
            if row.get("status") != "ok":
                mismatches.append(f"results[{index}].status={row.get('status')!r}")
            for field in ("sidecar_json", "sidecar_markdown", "image_id"):
                if not str(row.get(field) or "").strip():
                    mismatches.append(f"results[{index}].{field}=<missing>")
            for field in ("sidecar_json", "sidecar_markdown"):
                try:
                    source_path = _source_path(row, field, run_dir)
                except ValueError as exc:
                    mismatches.append(f"results[{index}].{field}={exc}")
                    continue
                if not source_path.is_file():
                    mismatches.append(f"results[{index}].{field}=<missing file>")
    if mismatches:
        raise ValueError(f"Decoupage source run failed validation: {', '.join(mismatches)}")
    return summary


def promote_decoupage_run(
    *,
    source_run_dir: Path,
    canonical_sidecars_root: Path,
    canonical_markdown_root: Path,
    analysis_root: Path,
    manifest_run_dir: Path,
    assets: list[VisualAsset],
    source_run_id: str,
    run_id: str,
    dataset_id: str = DATASET_ID,
) -> dict[str, object]:
    started_at = _utc_now()
    source_summary = validate_source_run_summary(source_run_dir, source_run_id=source_run_id)
    by_image_id = {asset.image_id: asset for asset in assets}
    by_source_sha256 = {asset.sha256: asset for asset in assets}
    by_new_relative_path = {asset.new_relative_path: asset for asset in assets}
    rows: list[PromotionRow] = []
    results = source_summary["results"]
    for index, result in enumerate(results, 1):
        image_id = str(result.get("image_id") or "").strip()
        asset = _asset_for_result(
            result,
            source_run_dir=source_run_dir,
            by_source_sha256=by_source_sha256,
            by_new_relative_path=by_new_relative_path,
            by_image_id=by_image_id,
        )
        if asset is None:
            rows.append(
                PromotionRow(
                    row_number=index,
                    image_id=image_id,
                    source_sha256="",
                    category="",
                    group="",
                    status="missing_manifest_asset",
                    source_json_path=str(result.get("sidecar_json") or ""),
                    source_markdown_path=str(result.get("sidecar_markdown") or ""),
                    canonical_json_relative_path="",
                    canonical_markdown_relative_path="",
                    error=f"Missing manifest asset for image_id: {image_id}",
                )
            )
            continue
        rows.append(
            _promote_one(
                row_number=index,
                asset=asset,
                result=result,
                source_run_dir=source_run_dir,
                canonical_sidecars_root=canonical_sidecars_root,
                canonical_markdown_root=canonical_markdown_root,
                analysis_root=analysis_root,
                manifest_run_dir=manifest_run_dir,
            )
        )
        _write_promotion_artifacts(
            manifest_run_dir,
            rows,
            _promotion_summary(
                rows,
                run_id=run_id,
                source_run_id=source_run_id,
                dataset_id=dataset_id,
                started_at=started_at,
            ),
        )
    summary = _promotion_summary(
        rows,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        started_at=started_at,
    )
    _write_promotion_artifacts(manifest_run_dir, rows, summary)
    return {
        "summary": asdict(summary),
        "manifest_path": str((manifest_run_dir / "decoupage-promotion-manifest.tsv").resolve()),
        "summary_path": str((manifest_run_dir / "decoupage-promotion-summary.json").resolve()),
    }


def load_canonical_decoupage_bundles(
    *,
    assets: list[VisualAsset],
    analysis_root: Path,
    canonical_sidecars_root: Path,
    canonical_markdown_root: Path,
    source_run_id: str,
    selected_source_sha256: set[str] | None = None,
) -> list[DecoupageBundle]:
    bundles: list[DecoupageBundle] = []
    seen_hashes: set[str] = set()
    for asset in assets:
        if selected_source_sha256 is not None and asset.sha256 not in selected_source_sha256:
            continue
        if asset.sha256 in seen_hashes:
            continue
        sidecar_path = _canonical_json_path(asset, canonical_sidecars_root)
        markdown_path = _canonical_markdown_path(asset, canonical_markdown_root)
        if not sidecar_path.exists() or not markdown_path.exists():
            continue
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        _validate_sidecar_binding(sidecar, asset)
        bundles.append(
            DecoupageBundle(
                image_id=asset.image_id,
                source_sha256=asset.sha256,
                category=asset.category,
                group=asset.group,
                image_relative_path=asset.new_relative_path,
                image_file_name=asset.file_name,
                image_width=asset.width,
                image_height=asset.height,
                sidecar_json_path=sidecar_path,
                markdown_path=markdown_path,
                sidecar_json_relative_path=str(sidecar_path.resolve().relative_to(analysis_root.resolve())),
                markdown_relative_path=str(markdown_path.resolve().relative_to(analysis_root.resolve())),
                source_run_id=source_run_id,
                sidecar=sidecar,
                markdown=markdown_path.read_text(encoding="utf-8", errors="replace"),
            )
        )
        seen_hashes.add(asset.sha256)
    return bundles


def collect_existing_decoupage_node_ids(kb: Any, *, dataset_id: str = DATASET_ID) -> set[str]:
    try:
        data = kb.collection.get(where={"artifact_type": DECOUPAGE_ARTIFACT_TYPE}, include=["metadatas"])
    except Exception:
        data = kb.collection.get(include=["metadatas"])
    ids = data.get("ids") or []
    metas = data.get("metadatas") or []
    existing: set[str] = set()
    for node_id, meta in zip(ids, metas, strict=False):
        meta = meta or {}
        if meta.get("dataset_id") == dataset_id and meta.get("artifact_type") == DECOUPAGE_ARTIFACT_TYPE:
            existing.add(str(node_id))
    return existing


def ingest_decoupage_bundles(
    kb: Any,
    bundles: list[DecoupageBundle],
    *,
    manifest_run_dir: Path,
    run_id: str,
    source_run_id: str,
    force: bool = False,
    dataset_id: str = DATASET_ID,
    max_retries: int = 3,
) -> dict[str, object]:
    started_at = _utc_now()
    existing_decoupage_ids = collect_existing_decoupage_node_ids(kb, dataset_id=dataset_id)
    rows: list[DecoupageIngestRow] = []
    queued: list[tuple[DecoupageBundle, DecoupageIngestRow]] = []

    for index, bundle in enumerate(bundles, 1):
        node_id = decoupage_node_id_for(bundle.source_sha256)
        linked_image_node_id = image_node_id_for_source_hash(bundle.source_sha256)
        status = "queued"
        error = ""
        if node_id in existing_decoupage_ids and not force:
            status = "skipped_existing"
        elif not _node_exists(kb, linked_image_node_id):
            status = "missing_linked_image"
            error = f"Missing linked image node: {linked_image_node_id}"
        row = DecoupageIngestRow(
            row_number=index,
            image_id=bundle.image_id,
            source_sha256=bundle.source_sha256,
            category=bundle.category,
            group=bundle.group,
            status=status,
            node_id=node_id,
            linked_image_node_id=linked_image_node_id,
            decoupage_json_relative_path=bundle.sidecar_json_relative_path,
            decoupage_markdown_relative_path=bundle.markdown_relative_path,
            error=error,
        )
        rows.append(row)
        if status == "queued":
            queued.append((bundle, row))

    for bundle, row in queued:
        try:
            text = build_decoupage_bundle_text(bundle)
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
            if force and row.node_id in existing_decoupage_ids:
                _upsert_text_node(kb, node)
                existing_decoupage_ids.discard(row.node_id)
            else:
                kb.vector_store.add([node])
            row.status = "embedded"
        except Exception as exc:
            row.status = "failed"
            row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        _write_ingest_artifacts(
            manifest_run_dir,
            rows,
            _ingest_summary(
                rows,
                run_id=run_id,
                source_run_id=source_run_id,
                dataset_id=dataset_id,
                force=force,
                started_at=started_at,
            ),
        )

    summary = _ingest_summary(
        rows,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        force=force,
        started_at=started_at,
    )
    _write_ingest_artifacts(manifest_run_dir, rows, summary)
    return {
        "summary": asdict(summary),
        "manifest_path": str((manifest_run_dir / "decoupage-ingest-manifest.tsv").resolve()),
        "summary_path": str((manifest_run_dir / "decoupage-ingest-summary.json").resolve()),
    }


def selected_source_hashes_from_source_summary(source_run_dir: Path, *, source_run_id: str) -> set[str]:
    summary = validate_source_run_summary(source_run_dir, source_run_id=source_run_id)
    hashes: set[str] = set()
    for index, row in enumerate(summary["results"], 1):
        source_json_path = _source_path(row, "sidecar_json", source_run_dir)
        sidecar = json.loads(source_json_path.read_text(encoding="utf-8"))
        binding = sidecar.get("_dante_binding")
        if not isinstance(binding, dict) or not binding.get("source_sha256"):
            raise ValueError(f"Missing _dante_binding.source_sha256 in result row {index}")
        hashes.add(str(binding["source_sha256"]))
    if len(hashes) != len(summary["results"]):
        raise ValueError(f"Duplicate source_sha256 values in source run: {len(hashes)} unique for {len(summary['results'])} rows")
    return hashes


def build_decoupage_bundle_text(bundle: DecoupageBundle) -> str:
    sidecar = bundle.sidecar
    parts = [
        "[Dante premium decoupage bundle]",
        f"Image ID: {bundle.image_id}",
        f"Category: {bundle.category}",
        f"Group: {bundle.group}",
        f"Image: {bundle.image_relative_path}",
        f"Markdown decoupage: {bundle.markdown_relative_path}",
        f"JSON sidecar: {bundle.sidecar_json_relative_path}",
        f"Source run: {bundle.source_run_id}",
        f"Provider: {_binding_value(sidecar, 'provider', DECOUPAGE_PROVIDER)}",
        f"Model: {_binding_value(sidecar, 'model', DECOUPAGE_MODEL)}",
        f"Confidence: {_field_value((sidecar.get('provenance') or {}).get('confidence_overall'))}",
        "",
        "## Searchable decoupage fields",
    ]
    for field in SEARCHABLE_FIELDS:
        parts.append(_structured_line(field, sidecar.get(field)))
    parts.extend(
        [
            "",
            "## Markdown handoff",
            bundle.markdown.strip(),
        ]
    )
    return "\n".join(part for part in parts if part is not None)


def _promote_one(
    *,
    row_number: int,
    asset: VisualAsset,
    result: dict[str, Any],
    source_run_dir: Path,
    canonical_sidecars_root: Path,
    canonical_markdown_root: Path,
    analysis_root: Path,
    manifest_run_dir: Path,
) -> PromotionRow:
    source_json_path = _source_path(result, "sidecar_json", source_run_dir)
    source_markdown_path = _source_path(result, "sidecar_markdown", source_run_dir)
    canonical_json_path = _canonical_json_path(asset, canonical_sidecars_root)
    canonical_markdown_path = _canonical_markdown_path(asset, canonical_markdown_root)
    row = PromotionRow(
        row_number=row_number,
        image_id=asset.image_id,
        source_sha256=asset.sha256,
        category=asset.category,
        group=asset.group,
        status="pending",
        source_json_path=str(source_json_path),
        source_markdown_path=str(source_markdown_path),
        canonical_json_relative_path=str(canonical_json_path.resolve(strict=False).relative_to(analysis_root.resolve())),
        canonical_markdown_relative_path=str(canonical_markdown_path.resolve(strict=False).relative_to(analysis_root.resolve())),
    )

    if not source_json_path.exists() or not source_markdown_path.exists():
        row.status = "missing_source_file"
        row.error = "Missing source JSON or Markdown"
        return row

    try:
        sidecar_text = source_json_path.read_text(encoding="utf-8")
        sidecar = json.loads(sidecar_text)
        _validate_sidecar_binding(sidecar, asset)
    except Exception as exc:
        row.status = "invalid_binding"
        row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        return row

    markdown_text = source_markdown_path.read_text(encoding="utf-8", errors="replace")
    row.source_json_sha256 = _sha256_text(sidecar_text)
    row.source_markdown_sha256 = _sha256_text(markdown_text)
    if canonical_json_path.exists():
        row.previous_json_sha256 = _file_sha256(canonical_json_path)
    if canonical_markdown_path.exists():
        row.previous_markdown_sha256 = _file_sha256(canonical_markdown_path)
    try:
        row.json_action, row.json_backup_path = _promote_text_file(
            source_text=sidecar_text,
            target_path=canonical_json_path,
            target_root=analysis_root,
            manifest_run_dir=manifest_run_dir,
            relative_for_backup=row.canonical_json_relative_path,
        )
        row.markdown_action, row.markdown_backup_path = _promote_text_file(
            source_text=markdown_text,
            target_path=canonical_markdown_path,
            target_root=analysis_root,
            manifest_run_dir=manifest_run_dir,
            relative_for_backup=row.canonical_markdown_relative_path,
        )
    except Exception as exc:
        row.status = "failed"
        row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        return row

    actions = {row.json_action, row.markdown_action}
    if "backed_up_replaced" in actions:
        row.status = "backed_up_replaced"
    elif "promoted" in actions:
        row.status = "promoted"
    else:
        row.status = "already_same"
    return row


def _asset_for_result(
    result: dict[str, Any],
    *,
    source_run_dir: Path,
    by_source_sha256: dict[str, VisualAsset],
    by_new_relative_path: dict[str, VisualAsset],
    by_image_id: dict[str, VisualAsset],
) -> VisualAsset | None:
    source_json_path = _source_path(result, "sidecar_json", source_run_dir)
    if source_json_path.exists():
        try:
            sidecar = json.loads(source_json_path.read_text(encoding="utf-8"))
            binding = sidecar.get("_dante_binding")
        except Exception:
            binding = None
        if isinstance(binding, dict):
            source_sha256 = str(binding.get("source_sha256") or "")
            new_relative_path = str(binding.get("new_relative_path") or "")
            if source_sha256 and source_sha256 in by_source_sha256:
                return by_source_sha256[source_sha256]
            if new_relative_path and new_relative_path in by_new_relative_path:
                return by_new_relative_path[new_relative_path]
    image_id = str(result.get("image_id") or "").strip()
    return by_image_id.get(image_id)


def _source_path(result: dict[str, Any], field: str, source_run_dir: Path) -> Path:
    value = str(result.get(field) or "").strip()
    if not value:
        return source_run_dir / "__missing__"
    path = Path(value)
    source_root = source_run_dir.resolve()
    candidate = path.resolve() if path.is_absolute() else (source_root / path).resolve()
    try:
        candidate.relative_to(source_root)
    except ValueError as exc:
        raise ValueError(f"path escapes source run: {value!r}") from exc
    return candidate


def _promote_text_file(
    *,
    source_text: str,
    target_path: Path,
    target_root: Path,
    manifest_run_dir: Path,
    relative_for_backup: str,
) -> tuple[str, str]:
    if not target_path.exists():
        safe_write_text(target_path, source_text, root=target_root)
        return "promoted", ""
    current_text = target_path.read_text(encoding="utf-8", errors="replace")
    source_sha = _sha256_text(source_text)
    current_sha = _sha256_text(current_text)
    if current_sha == source_sha:
        return "already_same", ""
    backup_relative = Path("backups") / Path(relative_for_backup)
    backup_path = manifest_run_dir / backup_relative.with_name(
        f"{backup_relative.name}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.{current_sha[:12]}.bak"
    )
    safe_write_text(backup_path, current_text, root=manifest_run_dir)
    safe_write_text(target_path, source_text, root=target_root)
    return "backed_up_replaced", str(backup_path.resolve())


def _canonical_json_path(asset: VisualAsset, root: Path) -> Path:
    return root / asset.category / asset.group / f"{asset.file_stem}.json"


def _canonical_markdown_path(asset: VisualAsset, root: Path) -> Path:
    return root / asset.category / asset.group / f"{asset.file_stem}.md"


def _validate_sidecar_binding(sidecar: dict[str, Any], asset: VisualAsset) -> None:
    if sidecar.get("asset_id") != asset.image_id:
        raise ValueError(f"asset_id mismatch: {sidecar.get('asset_id')!r} != {asset.image_id!r}")
    binding = sidecar.get("_dante_binding")
    if not isinstance(binding, dict):
        raise ValueError("Missing _dante_binding object")
    expected = {
        "image_id": asset.image_id,
        "source_sha256": asset.sha256,
        "new_relative_path": asset.new_relative_path,
        "provider": DECOUPAGE_PROVIDER,
        "model": DECOUPAGE_MODEL,
        "api_surface": DECOUPAGE_SOURCE_API_SURFACE,
        "uses_vertex": False,
    }
    mismatches = [key for key, expected_value in expected.items() if binding.get(key) != expected_value]
    if mismatches:
        details = ", ".join(f"{key}={binding.get(key)!r}" for key in mismatches)
        raise ValueError(f"_dante_binding mismatch: {details}")


def _bundle_metadata(
    bundle: DecoupageBundle,
    *,
    node_id: str,
    linked_image_node_id: str,
    run_id: str,
    source_run_id: str,
    dataset_id: str,
) -> dict[str, object]:
    sidecar = bundle.sidecar
    tags = [
        dataset_id,
        DECOUPAGE_ARTIFACT_TYPE,
        bundle.category,
        bundle.group,
        "premium-decoupage",
        "gemini",
    ]
    return {
        "id": node_id,
        "dataset_id": dataset_id,
        "artifact_type": DECOUPAGE_ARTIFACT_TYPE,
        "schema": DECOUPAGE_SCHEMA_NAME,
        "profile_id": DECOUPAGE_PROFILE_ID,
        "provider": _binding_value(sidecar, "provider", DECOUPAGE_PROVIDER),
        "model": _binding_value(sidecar, "model", DECOUPAGE_MODEL),
        "api_surface": _binding_value(sidecar, "api_surface", DECOUPAGE_SOURCE_API_SURFACE),
        "uses_vertex": bool(_binding_value(sidecar, "uses_vertex", False)),
        "source_sha256": bundle.source_sha256,
        "original_name": f"{bundle.image_id} premium decoupage",
        "file_path": str(bundle.markdown_path.resolve()),
        "upload_time": _utc_now(),
        "file_size": bundle.markdown_path.stat().st_size,
        "modality": "text",
        "dante_image_id": bundle.image_id,
        "linked_image_file_id": linked_image_node_id,
        "preview_image_file_id": linked_image_node_id,
        "decoupage_json_path": str(bundle.sidecar_json_path.resolve()),
        "decoupage_markdown_path": str(bundle.markdown_path.resolve()),
        "decoupage_json_relative_path": bundle.sidecar_json_relative_path,
        "decoupage_markdown_relative_path": bundle.markdown_relative_path,
        "image_relative_path": bundle.image_relative_path,
        "image_file_name": bundle.image_file_name,
        "category": bundle.category,
        "group": bundle.group,
        "width": bundle.image_width,
        "height": bundle.image_height,
        "run_id": run_id,
        "source_run_id": source_run_id,
        "lens": str(sidecar.get("lens") or ""),
        "confidence_overall": float((sidecar.get("provenance") or {}).get("confidence_overall") or 0),
        "decoupage_json_sha256": _file_sha256(bundle.sidecar_json_path),
        "decoupage_markdown_sha256": _file_sha256(bundle.markdown_path),
        "tags": ",".join(tags),
    }


def _binding_value(sidecar: dict[str, Any], key: str, fallback: Any) -> Any:
    binding = sidecar.get("_dante_binding")
    if isinstance(binding, dict) and key in binding:
        return binding[key]
    return fallback


def _structured_line(label: str, value: Any) -> str:
    return f"- {label}: {_field_value(value)}"


def _field_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _node_exists(kb: Any, node_id: str) -> bool:
    data = kb.collection.get(ids=[node_id], include=["metadatas"])
    return bool(data.get("ids"))


def _upsert_text_node(kb: Any, node: TextNode) -> None:
    upsert = getattr(kb.collection, "upsert", None)
    if upsert is None:
        raise RuntimeError("Force reingest requires a Chroma collection with upsert support")
    upsert(
        ids=[node.node_id],
        documents=[node.text],
        metadatas=[node.metadata],
        embeddings=[node.embedding],
    )


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_promotion_artifacts(manifest_run_dir: Path, rows: list[PromotionRow], summary: PromotionSummary) -> None:
    safe_write_text(
        manifest_run_dir / "decoupage-promotion-manifest.tsv",
        _rows_to_tsv(rows),
        root=manifest_run_dir,
    )
    safe_write_text(
        manifest_run_dir / "decoupage-promotion-summary.json",
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        root=manifest_run_dir,
    )


def _write_ingest_artifacts(manifest_run_dir: Path, rows: list[DecoupageIngestRow], summary: DecoupageIngestSummary) -> None:
    safe_write_text(
        manifest_run_dir / "decoupage-ingest-manifest.tsv",
        _rows_to_tsv(rows),
        root=manifest_run_dir,
    )
    safe_write_text(
        manifest_run_dir / "decoupage-ingest-summary.json",
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        root=manifest_run_dir,
    )


def _rows_to_tsv(rows: list[Any]) -> str:
    output = io.StringIO()
    fields = list(asdict(rows[0]).keys()) if rows else ["row_number", "status", "error"]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    return output.getvalue()


def _promotion_summary(
    rows: list[PromotionRow],
    *,
    run_id: str,
    source_run_id: str,
    dataset_id: str,
    started_at: str,
) -> PromotionSummary:
    return PromotionSummary(
        schema_version=DECOUPAGE_INGEST_SCHEMA_VERSION,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        artifact_type=DECOUPAGE_ARTIFACT_TYPE,
        total_selected=len(rows),
        promoted=sum(1 for row in rows if row.status == "promoted"),
        already_same=sum(1 for row in rows if row.status == "already_same"),
        backed_up_replaced=sum(1 for row in rows if row.status == "backed_up_replaced"),
        missing_source_file=sum(1 for row in rows if row.status == "missing_source_file"),
        invalid_binding=sum(1 for row in rows if row.status == "invalid_binding"),
        missing_manifest_asset=sum(1 for row in rows if row.status == "missing_manifest_asset"),
        failed=sum(1 for row in rows if row.status == "failed"),
        started_at=started_at,
        finished_at=_utc_now(),
    )


def _ingest_summary(
    rows: list[DecoupageIngestRow],
    *,
    run_id: str,
    source_run_id: str,
    dataset_id: str,
    force: bool,
    started_at: str,
) -> DecoupageIngestSummary:
    return DecoupageIngestSummary(
        schema_version=DECOUPAGE_INGEST_SCHEMA_VERSION,
        run_id=run_id,
        source_run_id=source_run_id,
        dataset_id=dataset_id,
        artifact_type=DECOUPAGE_ARTIFACT_TYPE,
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
