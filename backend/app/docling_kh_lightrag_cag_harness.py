"""Post-Docling P0-P8 dry-run harness for cinema ingest/index planning."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

SCHEMA_VERSION = "post_docling_p0_p8_harness.v1"
NORMALIZED_SCHEMA_VERSION = "docling_normalized_output.v1"
CROSSWALK_SCHEMA_VERSION = "package_crosswalk.v1"
CAG_SCHEMA_VERSION = "cag_pack_candidate.v1"
CERTIFICATION_SCHEMA_VERSION = "p0_p8_certification.v1"

DEFAULT_ARTIFACT_ROOT = Path("logs/post-docling-p0-p8-harness")
DEFAULT_FULL_RUN = Path("logs/docling-runs/docling-cinema-full-20260703-ptbr-resumable")
DEFAULT_PENDING_RUN = Path("logs/docling-runs/docling-cinema-pending-c-20260704-ready")
DEFAULT_RETRY_RUN = Path("logs/docling-runs/docling-cinema-failed-retry-chunked5-b-20260705")
DEFAULT_OVERLAY_RUN = Path("logs/docling-runs/docling-cinema-enrichment-overlay-20260706")
DEFAULT_EXPECTED_TOTAL = 84
DEFAULT_QWEN_VISION_MODEL = "qwen-3.7-max"
DEFAULT_QWEN_OCR_MODEL = "qwen-ocr"
DEFAULT_QWEN_ENDPOINT_REGION = "cn-beijing"
DEFAULT_PUBLIC_ROOT = Path(__file__).resolve().parents[2]

SUCCESS_STATUSES = {"converted", "validation_warning", "needs_review"}
FULL_OVERLAY_LEVEL = "full_B_enriched"
BASE_ONLY_OVERLAY_LEVEL = "base_only_due_to_visual_timeout"
OVERLAY_QUALITY_STATUS = {
    FULL_OVERLAY_LEVEL: "enriched",
    BASE_ONLY_OVERLAY_LEVEL: "partial",
}
LEAK_RE = re.compile(r"(?:~|/(?:Users|home|private|tmp|Volumes|var|opt)/)[^\s\"')\]}>,;]+")
SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|secret|token|password|dsn)\b[\"']?\s*[:=]\s*[\"']?[^,\s}\"']+")
BARE_SECRET_RE = re.compile(
    r"(?i)(Bearer\s+[A-Za-z0-9._~+/=-]+|sk-(?:proj-)?[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
SENSITIVE_KEY_RE = re.compile(r"(?i)(api[_-]?key|secret|password|dsn|(?:^|[_-])token(?:$|[_-]))")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OUTPUT_FILE_KINDS = {
    ".md": "markdown",
    ".txt": "text",
    ".doctags": "doctags",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".svg": "image",
    ".csv": "table",
}
HEAVY_OUTPUT_FILE_KINDS = {
    ".html": "html",
    ".json": "structured_json",
    ".yaml": "structured_yaml",
    ".yml": "structured_yaml",
}

PhaseName = Literal[
    "P0",
    "P1",
    "P2",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
    "P8",
]
PHASE_ORDER: tuple[PhaseName, ...] = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7")


@dataclass(frozen=True)
class HarnessConfig:
    run_id: str
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT
    full_run: Path = DEFAULT_FULL_RUN
    pending_run: Path = DEFAULT_PENDING_RUN
    retry_run: Path = DEFAULT_RETRY_RUN
    overlay_run: Path = DEFAULT_OVERLAY_RUN
    expected_total: int = DEFAULT_EXPECTED_TOTAL
    apply: bool = False
    visual_provider: str = "qwen"
    visual_fallback_provider: str = "gemini"
    qwen_vision_model: str = DEFAULT_QWEN_VISION_MODEL
    qwen_ocr_model: str = DEFAULT_QWEN_OCR_MODEL
    qwen_endpoint_region: str = DEFAULT_QWEN_ENDPOINT_REGION
    qwen_base_url: str = ""
    qwen_api_key_configured: bool = False

    @property
    def run_dir(self) -> Path:
        return _resolve_public_path(self.artifact_root) / self.run_id


@dataclass(frozen=True)
class PhaseResult:
    phase: PhaseName
    name: str
    status: str
    input_hashes: dict[str, str] = field(default_factory=dict)
    output_paths: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    mutation_performed: bool = False
    blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DoclingRunEvidence:
    run_id: str
    run_dir: str
    summary_path: str
    output_index_path: str
    summary_hash: str
    output_index_hash: str
    converted_rows: int
    total_files: int
    by_status: dict[str, int]
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class OverlayEvidence:
    run_id: str
    run_dir: str
    summary_hash: str
    manifest_hash: str
    total_pages: int
    full_enriched_pages: int
    base_only_pages: int
    pages: list[dict[str, Any]]


def build_run_id() -> str:
    return f"post-docling-p0-p8-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"


def run_all(config: HarnessConfig) -> dict[str, Any]:
    if config.apply:
        raise ValueError("apply_mode_not_implemented_for_post_docling_harness")
    config.run_dir.mkdir(parents=True, exist_ok=True)

    phases: list[PhaseResult] = []
    try:
        proof, phase = prove_existing_docling(config)
    except Exception as exc:  # noqa: BLE001
        proof = {
            "schema_version": SCHEMA_VERSION,
            "run_id": config.run_id,
            "expected_total": config.expected_total,
            "converted_total": 0,
            "docling_conversion_invoked": False,
            "runs": [],
            "overlay": {},
        }
        phases.append(
            PhaseResult(
                phase="P0",
                name="existing-docling-proof",
                status="blocked",
                mutation_performed=False,
                blockers=[_public_exception_blocker(exc)],
            )
        )
        return _finish_run(config, proof, phases)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases)

    _, phase = write_package_contract(config, proof)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases)

    normalized, phase = normalize_docling_outputs(config, proof)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases, normalized=normalized)

    kh_candidates, phase = build_kh_multimodal_candidates(config, normalized)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases, normalized=normalized)

    lightrag_candidates, phase = build_lightrag_graph_candidates(config, normalized)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases, normalized=normalized)

    crosswalk, phase = build_package_crosswalk(config, normalized, kh_candidates, lightrag_candidates)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases, normalized=normalized, crosswalk=crosswalk)

    cag_candidates, crosswalk, phase = build_cag_pack_candidates(config, crosswalk)
    phases.append(phase)
    if phase.status == "blocked":
        return _finish_run(config, proof, phases, normalized=normalized, crosswalk=crosswalk, cag_candidates=cag_candidates)

    phases.append(validate_resume_ledger(config, phases))
    return _finish_run(config, proof, phases, normalized=normalized, crosswalk=crosswalk, cag_candidates=cag_candidates)


def _finish_run(
    config: HarnessConfig,
    proof: Mapping[str, Any],
    phases: list[PhaseResult],
    *,
    normalized: Sequence[Mapping[str, Any]] | None = None,
    crosswalk: Sequence[Mapping[str, Any]] | None = None,
    cag_candidates: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    _append_skipped_phases(phases)
    normalized_rows = list(normalized or [])
    crosswalk_rows = list(crosswalk or [])
    cag_rows = list(cag_candidates or [])
    certification, phase = certify_run(config, phases, normalized_rows, crosswalk_rows, cag_rows)
    phases.append(phase)

    ledger = {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.run_id,
        "dry_run": not config.apply,
        "mutation_performed": any(item.mutation_performed for item in phases),
        "phases": [asdict(item) for item in phases],
    }
    _write_json(config.run_dir / "phase-ledger.json", ledger)
    _write_markdown_report(config, proof, certification)
    return {"ledger": ledger, "certification": certification}


def _append_skipped_phases(phases: list[PhaseResult]) -> None:
    completed = {phase.phase for phase in phases}
    if not any(phase.status == "blocked" for phase in phases):
        return
    for phase_name in PHASE_ORDER:
        if phase_name in completed:
            continue
        phases.append(
            PhaseResult(
                phase=phase_name,
                name="skipped",
                status="skipped",
                mutation_performed=False,
                blockers=["skipped_due_to_upstream_blocker"],
            )
        )


def prove_existing_docling(config: HarnessConfig) -> tuple[dict[str, Any], PhaseResult]:
    runs = [
        load_docling_run(_resolve_public_path(config.full_run)),
        load_docling_run(_resolve_public_path(config.pending_run)),
        load_docling_run(_resolve_public_path(config.retry_run)),
    ]
    overlay = load_overlay(_resolve_public_path(config.overlay_run))
    converted_total = sum(run.converted_rows for run in runs)
    blockers: list[str] = []
    if converted_total != config.expected_total:
        blockers.append(f"converted_total_mismatch:{converted_total}!={config.expected_total}")

    source_hashes = [str(row.get("source_sha256") or "") for run in runs for row in run.rows if row.get("status") in SUCCESS_STATUSES]
    missing_success_hashes = sum(1 for item in source_hashes if not item)
    if missing_success_hashes:
        blockers.append(f"missing_success_hashes:{missing_success_hashes}")
    populated_hashes = [item for item in source_hashes if item]
    duplicate_success_hashes = len(populated_hashes) - len(set(populated_hashes))
    if duplicate_success_hashes:
        blockers.append(f"duplicate_success_hashes:{duplicate_success_hashes}")
    malformed_identity_count = sum(
        1
        for run in runs
        for row in run.rows
        if row.get("status") in SUCCESS_STATUSES and _malformed_source_identity(row)
    )
    if malformed_identity_count:
        blockers.append(f"malformed_success_source_identity:{malformed_identity_count}")

    proof = {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.run_id,
        "expected_total": config.expected_total,
        "converted_total": converted_total,
        "docling_conversion_invoked": False,
        "runs": [asdict(run) for run in runs],
        "overlay": asdict(overlay),
    }
    _write_json(config.run_dir / "p0-docling-proof.json", _public_payload(proof))
    status = "complete" if not blockers else "blocked"
    return proof, PhaseResult(
        phase="P0",
        name="existing-docling-proof",
        status=status,
        input_hashes={
            run.run_id: stable_hash({"summary": run.summary_hash, "output_index": run.output_index_hash})
            for run in runs
        }
        | {overlay.run_id: stable_hash({"summary": overlay.summary_hash, "manifest": overlay.manifest_hash})},
        output_paths=["p0-docling-proof.json"],
        counts={
            "converted_total": converted_total,
            "expected_total": config.expected_total,
            "overlay_pages": overlay.total_pages,
            "overlay_full_enriched": overlay.full_enriched_pages,
            "overlay_base_only": overlay.base_only_pages,
        },
        mutation_performed=False,
        blockers=blockers,
    )


def write_package_contract(config: HarnessConfig, proof: Mapping[str, Any]) -> tuple[dict[str, Any], PhaseResult]:
    source_run_ids = [
        str(run.get("run_id") or "")
        for run in proof.get("runs", [])
        if isinstance(run, Mapping) and run.get("run_id")
    ]
    contract = {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.run_id,
        "source_run_ids": source_run_ids,
        "expected_total": config.expected_total,
        "layers": [
            "docling_document",
            "docling_overlay_page",
            "kh_multimodal_candidate",
            "lightrag_graph_candidate",
            "package_crosswalk",
            "cag_pack_candidate",
        ],
        "identity_rule": "source_sha256_or_overlay_package_key",
        "visual_analysis": _visual_analysis_config(config),
        "docling_conversion_invoked": False,
        "mutation_performed": False,
    }
    blockers = _provider_config_blockers(config)
    _write_json(config.run_dir / "p1-package-contract.json", _public_payload(contract))
    return contract, PhaseResult(
        phase="P1",
        name="package-contract",
        status="complete" if not blockers else "blocked",
        output_paths=["p1-package-contract.json"],
        counts={"contract_layers": len(contract["layers"]), "source_runs": len(source_run_ids)},
        mutation_performed=False,
        blockers=blockers,
    )


def normalize_docling_outputs(config: HarnessConfig, proof: Mapping[str, Any]) -> tuple[list[dict[str, Any]], PhaseResult]:
    records: list[dict[str, Any]] = []
    run_dirs = [_resolve_public_path(config.full_run), _resolve_public_path(config.pending_run), _resolve_public_path(config.retry_run)]
    for run_index, run in enumerate(proof.get("runs", [])):
        run_id = str(run.get("run_id") or "")
        run_dir = run_dirs[run_index] if run_index < len(run_dirs) else _resolve_public_path(run.get("run_dir", ""))
        for row in run.get("rows", []):
            if not isinstance(row, dict):
                continue
            record = _normalized_docling_record(run_id, row)
            records.append(record)
            records.extend(_normalized_output_file_records(run_id, row, run_dir))

    overlay = proof.get("overlay", {})
    if isinstance(overlay, Mapping):
        for page in overlay.get("pages", []):
            if isinstance(page, dict):
                records.append(_normalized_overlay_record(str(overlay.get("run_id") or ""), page))

    path = config.run_dir / "docling-normalized-output.jsonl"
    _write_jsonl(path, records)
    summary = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "run_id": config.run_id,
        "total_records": len(records),
        "by_layer": _count_by(records, "artifact_layer"),
        "by_status": _count_by(records, "status"),
        "by_overlay_level": _count_by(records, "overlay_level"),
    }
    _write_json(config.run_dir / "docling-normalized-summary.json", summary)
    by_layer = summary["by_layer"]
    blockers = [] if records else ["no_normalized_records"]
    if records and not any(layer.startswith("docling_output") or layer in {"docling_extracted_image", "docling_table"} for layer in by_layer):
        blockers.append("missing_docling_output_file_records")
    blocked_output_records = sum(1 for record in records if record.get("artifact_layer") == "docling_output_file" and record.get("quality_status") == "blocked")
    if blocked_output_records:
        blockers.append(f"blocked_docling_output_records:{blocked_output_records}")
    return records, PhaseResult(
        phase="P2",
        name="docling-normalization",
        status="complete" if not blockers else "blocked",
        output_paths=["docling-normalized-output.jsonl", "docling-normalized-summary.json"],
        counts={"normalized_records": len(records), **{f"layer_{k}": v for k, v in summary["by_layer"].items()}},
        mutation_performed=False,
        blockers=blockers,
    )


def build_kh_multimodal_candidates(config: HarnessConfig, records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], PhaseResult]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        if record.get("artifact_layer") not in {"docling_document", "docling_overlay_page", "docling_output_file", "docling_extracted_image", "docling_table"}:
            continue
        status = _kh_candidate_status(record)
        candidate = {
            "candidate_id": f"kh_{stable_hash(record)[:20]}",
            "package_key": record.get("package_key"),
            "source_sha256": record.get("source_sha256", ""),
            "source_pdf_id": record.get("source_pdf_id", ""),
            "artifact_layer": record.get("artifact_layer"),
            "status": status,
            "modality": "image" if record.get("artifact_layer") == "docling_extracted_image" else "text",
            "visual_analysis": _visual_analysis_config(config),
            "mutation_performed": False,
            "provenance_hash": stable_hash(record),
        }
        candidates.append(_public_payload(candidate))
    _write_jsonl(config.run_dir / "kh-multimodal-candidates.jsonl", candidates)
    return candidates, PhaseResult(
        phase="P3",
        name="kh-multimodal-dry-run",
        status="complete" if candidates else "blocked",
        output_paths=["kh-multimodal-candidates.jsonl"],
        counts={"kh_candidates": len(candidates)},
        mutation_performed=False,
        blockers=[] if candidates else ["no_kh_candidates"],
    )


def build_lightrag_graph_candidates(config: HarnessConfig, records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], PhaseResult]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        if record.get("artifact_layer") != "docling_document":
            continue
        if record.get("status") not in SUCCESS_STATUSES:
            continue
        candidate = {
            "graph_document_id": f"lightrag_docling_{stable_hash(record)[:20]}",
            "package_key": record.get("package_key"),
            "source_sha256": record.get("source_sha256"),
            "source_relative_path": record.get("source_relative_path"),
            "content_role": "docling_source_provenance",
            "rights_status": "candidate_summary_only",
            "status": "candidate",
            "mutation_performed": False,
            "provenance_hash": stable_hash(record),
        }
        candidates.append(_public_payload(candidate))
    _write_jsonl(config.run_dir / "lightrag-graph-candidates.jsonl", candidates)
    return candidates, PhaseResult(
        phase="P4",
        name="lightrag-graph-dry-run",
        status="complete" if candidates else "blocked",
        output_paths=["lightrag-graph-candidates.jsonl"],
        counts={"lightrag_candidates": len(candidates)},
        mutation_performed=False,
        blockers=[] if candidates else ["no_lightrag_candidates"],
    )


def build_package_crosswalk(
    config: HarnessConfig,
    records: Sequence[Mapping[str, Any]],
    kh_candidates: Sequence[Mapping[str, Any]],
    lightrag_candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], PhaseResult]:
    kh_by_key = _group_first(kh_candidates, "package_key")
    graph_by_key = _group_first(lightrag_candidates, "package_key")
    crosswalk: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        package_key = str(record.get("package_key") or "")
        if not package_key or package_key in seen:
            continue
        seen.add(package_key)
        kh = kh_by_key.get(package_key, {})
        graph = graph_by_key.get(package_key, {})
        row = {
            "schema_version": CROSSWALK_SCHEMA_VERSION,
            "package_key": package_key,
            "public_label": record.get("public_label") or record.get("source_pdf_id") or package_key[:12],
            "layer": record.get("artifact_layer"),
            "source_sha256": record.get("source_sha256", ""),
            "kh_candidate_id": kh.get("candidate_id", ""),
            "graph_document_id": graph.get("graph_document_id", ""),
            "cag_pack_id": "",
            "status": _crosswalk_status(kh, graph),
            "provenance_hash": stable_hash({"record": record, "kh": kh, "graph": graph}),
        }
        crosswalk.append(_public_payload(row))
    _write_jsonl(config.run_dir / "package-crosswalk.jsonl", crosswalk)
    return crosswalk, PhaseResult(
        phase="P5",
        name="package-crosswalk",
        status="complete" if crosswalk else "blocked",
        output_paths=["package-crosswalk.jsonl"],
        counts={"crosswalk_rows": len(crosswalk)},
        mutation_performed=False,
        blockers=[] if crosswalk else ["no_crosswalk_rows"],
    )


def build_cag_pack_candidates(
    config: HarnessConfig,
    crosswalk: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], PhaseResult]:
    by_topic: dict[str, list[Mapping[str, Any]]] = {}
    for row in crosswalk:
        label = str(row.get("public_label") or "general")
        topic = slugify(label.split("--", 1)[0]) or "general"
        by_topic.setdefault(topic, []).append(row)

    candidates: list[dict[str, Any]] = []
    for topic, rows in sorted(by_topic.items()):
        evidence_hash = stable_hash([row.get("provenance_hash") for row in rows])
        candidate = {
            "schema_version": CAG_SCHEMA_VERSION,
            "cag_pack_id": f"cag_{topic}_{evidence_hash[:12]}",
            "topic": topic,
            "status": "available" if rows else "missing",
            "evidence_package_keys": [row.get("package_key") for row in rows],
            "source_hashes": [row.get("source_sha256") for row in rows if row.get("source_sha256")],
            "crosswalk_hash": evidence_hash,
            "raw_source_text_included": False,
            "mutation_performed": False,
        }
        candidates.append(_public_payload(candidate))
    _write_jsonl(config.run_dir / "cag-pack-candidates.jsonl", candidates)
    linked_crosswalk = link_cag_packs_to_crosswalk(config, crosswalk, candidates)
    blockers = _cag_crosswalk_blockers(linked_crosswalk, candidates)
    return candidates, linked_crosswalk, PhaseResult(
        phase="P6",
        name="cag-pack-candidates",
        status="complete" if candidates and not blockers else "blocked",
        output_paths=["cag-pack-candidates.jsonl", "package-crosswalk.jsonl"],
        counts={"cag_candidates": len(candidates), "cag_linked_crosswalk_rows": sum(1 for row in linked_crosswalk if row.get("cag_pack_id"))},
        mutation_performed=False,
        blockers=blockers if candidates else ["no_cag_candidates"],
    )


def link_cag_packs_to_crosswalk(
    config: HarnessConfig,
    crosswalk: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cag_by_package: dict[str, str] = {}
    for candidate in cag_candidates:
        cag_pack_id = str(candidate.get("cag_pack_id") or "")
        for package_key in candidate.get("evidence_package_keys", []):
            key = str(package_key or "")
            if key and cag_pack_id:
                cag_by_package.setdefault(key, cag_pack_id)

    linked: list[dict[str, Any]] = []
    for row in crosswalk:
        package_key = str(row.get("package_key") or "")
        linked_row = dict(row)
        linked_row["cag_pack_id"] = cag_by_package.get(package_key, "")
        linked_row["provenance_hash"] = stable_hash({"crosswalk": row, "cag_pack_id": linked_row["cag_pack_id"]})
        linked.append(_public_payload(linked_row))
    _write_jsonl(config.run_dir / "package-crosswalk.jsonl", linked)
    return linked


def certify_run(
    config: HarnessConfig,
    phases: Sequence[PhaseResult],
    normalized: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], PhaseResult]:
    blockers: list[str] = []
    if any(phase.mutation_performed for phase in phases):
        blockers.append("dry_run_mutation_detected")
    if not normalized:
        blockers.append("missing_normalized_docling_records")
    if not crosswalk:
        blockers.append("missing_package_crosswalk")
    if not cag_candidates:
        blockers.append("missing_cag_candidates")
    blockers.extend(_cag_crosswalk_blockers(crosswalk, cag_candidates))
    phase_blockers = [f"{phase.phase}:{blocker}" for phase in phases for blocker in phase.blockers]
    blockers.extend(phase_blockers)

    public_payload = {
        "phases": [asdict(phase) for phase in phases],
        "normalized": list(normalized),
        "crosswalk": list(crosswalk),
        "cag_candidates": list(cag_candidates),
    }
    artifact_payload = _read_phase_artifacts(config, phases)
    leaks = find_public_leaks(public_payload) + find_public_leaks(artifact_payload)
    if leaks:
        blockers.append("public_leak_detected")

    certification = {
        "schema_version": CERTIFICATION_SCHEMA_VERSION,
        "run_id": config.run_id,
        "ok": not blockers,
        "dry_run": not config.apply,
        "mutation_performed": any(phase.mutation_performed for phase in phases),
        "counts": {
            "normalized_records": len(normalized),
            "crosswalk_rows": len(crosswalk),
            "cag_candidates": len(cag_candidates),
            "leaks": len(leaks),
        },
        "blockers": blockers,
        "leak_samples": leaks[:10],
    }
    _write_json(config.run_dir / "p0-p8-certification.json", certification)
    return certification, PhaseResult(
        phase="P8",
        name="certification",
        status="complete" if certification["ok"] else "blocked",
        output_paths=["p0-p8-certification.json"],
        counts={key: int(value) for key, value in certification["counts"].items()},
        mutation_performed=False,
        blockers=blockers,
    )


def validate_resume_ledger(config: HarnessConfig, phases: Sequence[PhaseResult]) -> PhaseResult:
    blockers: list[str] = []
    artifact_paths = [path for phase in phases for path in phase.output_paths]
    for relative_path in sorted(set(artifact_paths)):
        if not (config.run_dir / relative_path).exists():
            blockers.append(f"missing_phase_artifact:{relative_path}")
    if any(phase.mutation_performed for phase in phases):
        blockers.append("phase_mutation_detected")
    return PhaseResult(
        phase="P7",
        name="resume-ledger",
        status="complete" if not blockers else "blocked",
        output_paths=["phase-ledger.json"],
        counts={"pre_certification_phases": len(phases) + 1, "phase_artifacts_checked": len(set(artifact_paths))},
        mutation_performed=False,
        blockers=blockers,
    )


def load_docling_run(run_dir: Path) -> DoclingRunEvidence:
    summary_path = run_dir / "docling-cinema-batch-summary.json"
    output_index_path = run_dir / "docling-cinema-batch-output-index.jsonl"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    if not output_index_path.exists():
        raise FileNotFoundError(output_index_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = list(_read_jsonl(output_index_path))
    converted_rows = sum(1 for row in rows if row.get("status") in SUCCESS_STATUSES)
    by_status = summary.get("by_status") if isinstance(summary.get("by_status"), dict) else _count_by(rows, "status")
    return DoclingRunEvidence(
        run_id=str(summary.get("run_id") or run_dir.name),
        run_dir=_public_path(run_dir),
        summary_path=_public_path(summary_path),
        output_index_path=_public_path(output_index_path),
        summary_hash=sha256_file(summary_path),
        output_index_hash=sha256_file(output_index_path),
        converted_rows=converted_rows,
        total_files=int(summary.get("total_files") or len(rows)),
        by_status={str(key): int(value) for key, value in by_status.items()},
        rows=[_public_payload(row) for row in rows],
    )


def load_overlay(run_dir: Path) -> OverlayEvidence:
    summary_path = run_dir / "overlay-summary.json"
    manifest_path = run_dir / "overlay-manifest.json"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = manifest.get("pages", []) if isinstance(manifest, dict) else manifest
    if not isinstance(pages, list):
        pages = []
    by_overlay = summary.get("by_overlay_level") if isinstance(summary.get("by_overlay_level"), dict) else _count_by(pages, "overlay_level")
    return OverlayEvidence(
        run_id=str(summary.get("run_id") or run_dir.name),
        run_dir=_public_path(run_dir),
        summary_hash=sha256_file(summary_path),
        manifest_hash=sha256_file(manifest_path),
        total_pages=int(summary.get("total_overlay_pages") or len(pages)),
        full_enriched_pages=int(by_overlay.get(FULL_OVERLAY_LEVEL, 0)),
        base_only_pages=int(by_overlay.get(BASE_ONLY_OVERLAY_LEVEL, 0)),
        pages=[_public_payload(page) for page in pages],
    )


def _normalized_docling_record(run_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    source_sha = str(row.get("source_sha256") or "")
    source_path = str(row.get("source_relative_path") or "")
    source_pdf_id = slugify(Path(source_path).stem)
    record = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "record_id": f"docling_doc_{source_sha[:20] or stable_hash(row)[:20]}",
        "package_key": source_sha or stable_hash(row),
        "public_label": source_pdf_id,
        "artifact_layer": "docling_document",
        "status": str(row.get("status") or "unknown"),
        "overlay_level": "none",
        "source_pdf_id": source_pdf_id,
        "source_relative_path": source_path,
        "source_sha256": source_sha,
        "docling_run_id": run_id,
        "docling_level": row.get("docling_level", ""),
        "topic_folder": row.get("topic_folder", ""),
        "page_count": _safe_int(row.get("page_count")),
        "output_relative_path": _public_path(row.get("output_relative_path", "")),
        "quality_status": _quality_status(str(row.get("status") or "")),
    }
    record["provenance_hash"] = stable_hash(record)
    return record


def _normalized_output_file_records(run_id: str, row: Mapping[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    output_relative = str(row.get("output_relative_path") or "")
    if not output_relative:
        return []
    resolved_run_dir = run_dir.resolve()
    output_dir = (resolved_run_dir / output_relative).resolve()
    try:
        output_dir.relative_to(resolved_run_dir)
    except ValueError:
        return [_blocked_output_directory_record(run_id, row, output_relative, "output_dir_outside_docling_run")]
    if not output_dir.is_dir():
        return [_blocked_output_directory_record(run_id, row, output_relative, "missing_output_dir")]

    source_sha = str(row.get("source_sha256") or "")
    source_path = str(row.get("source_relative_path") or "")
    source_pdf_id = slugify(Path(source_path).stem)
    records: list[dict[str, Any]] = []
    for path in sorted((item for item in output_dir.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        file_kind = OUTPUT_FILE_KINDS.get(path.suffix.lower())
        if not file_kind and path.suffix.lower() in HEAVY_OUTPUT_FILE_KINDS:
            records.append(_skipped_heavy_output_file_record(run_id, row, path, HEAVY_OUTPUT_FILE_KINDS[path.suffix.lower()]))
            continue
        if not file_kind:
            continue
        artifact_hash = sha256_file(path)
        artifact_layer = _artifact_layer_for_file_kind(file_kind)
        relative_output = _public_path(path)
        record = {
            "schema_version": NORMALIZED_SCHEMA_VERSION,
            "record_id": f"docling_file_{artifact_hash[:20]}",
            "package_key": f"{source_sha}:file:{artifact_hash[:20]}" if source_sha else f"file:{artifact_hash}",
            "public_label": f"{source_pdf_id}:{file_kind}",
            "artifact_layer": artifact_layer,
            "status": "available",
            "overlay_level": "none",
            "source_pdf_id": source_pdf_id,
            "source_relative_path": source_path,
            "source_sha256": source_sha,
            "docling_run_id": run_id,
            "output_relative_path": relative_output,
            "output_file_kind": file_kind,
            "artifact_sha256": artifact_hash,
            "quality_status": "usable",
        }
        record["provenance_hash"] = stable_hash(record)
        records.append(_public_payload(record))
    return records


def _skipped_heavy_output_file_record(run_id: str, row: Mapping[str, Any], path: Path, file_kind: str) -> dict[str, Any]:
    source_sha = str(row.get("source_sha256") or "")
    source_path = str(row.get("source_relative_path") or "")
    source_pdf_id = slugify(Path(source_path).stem)
    record = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "record_id": f"docling_heavy_file_{stable_hash({'run_id': run_id, 'path': _public_path(path)})[:20]}",
        "package_key": f"{source_sha}:heavy:{stable_hash(_public_path(path))[:20]}" if source_sha else f"heavy:{stable_hash(_public_path(path))}",
        "public_label": f"{source_pdf_id}:{file_kind}",
        "artifact_layer": "docling_output_file",
        "status": "skipped",
        "skip_reason": "heavy_duplicate_rendering_not_hashed",
        "overlay_level": "none",
        "source_pdf_id": source_pdf_id,
        "source_relative_path": source_path,
        "source_sha256": source_sha,
        "docling_run_id": run_id,
        "output_relative_path": _public_path(path),
        "output_file_kind": file_kind,
        "artifact_sha256": "",
        "quality_status": "skipped",
    }
    record["provenance_hash"] = stable_hash(record)
    return _public_payload(record)


def _blocked_output_directory_record(run_id: str, row: Mapping[str, Any], output_relative: str, reason: str) -> dict[str, Any]:
    source_sha = str(row.get("source_sha256") or "")
    source_path = str(row.get("source_relative_path") or "")
    source_pdf_id = slugify(Path(source_path).stem)
    record = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "record_id": f"docling_output_blocked_{stable_hash({'run_id': run_id, 'row': row, 'reason': reason})[:20]}",
        "package_key": f"{source_sha}:output-blocked" if source_sha else stable_hash(row),
        "public_label": f"{source_pdf_id}:output-blocked",
        "artifact_layer": "docling_output_file",
        "status": "blocked",
        "blocked_reason": reason,
        "overlay_level": "none",
        "source_pdf_id": source_pdf_id,
        "source_relative_path": source_path,
        "source_sha256": source_sha,
        "docling_run_id": run_id,
        "output_relative_path": _public_path(output_relative),
        "quality_status": "blocked",
    }
    record["provenance_hash"] = stable_hash(record)
    return _public_payload(record)


def _normalized_overlay_record(run_id: str, page: Mapping[str, Any]) -> dict[str, Any]:
    label = slugify(str(page.get("label") or "overlay"))
    page_number = _safe_int(page.get("page"))
    metrics = page.get("metrics") if isinstance(page.get("metrics"), dict) else {}
    record = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "record_id": f"docling_overlay_{label}_{page_number}",
        "package_key": f"overlay:{label}:{page_number}",
        "public_label": f"{label}:page-{page_number:04d}",
        "artifact_layer": "docling_overlay_page",
        "status": str(page.get("overlay_level") or "unknown"),
        "overlay_level": str(page.get("overlay_level") or "unknown"),
        "source_pdf_id": label,
        "source_relative_path": "",
        "source_sha256": "",
        "docling_run_id": run_id,
        "page": page_number,
        "selected_output": _public_path(page.get("selected_output", "")),
        "base_output": _public_path(page.get("base_output", "")),
        "metrics": metrics,
        "quality_status": _overlay_quality_status(str(page.get("overlay_level") or "unknown")),
    }
    record["provenance_hash"] = stable_hash(record)
    return _public_payload(record)


def _quality_status(status: str) -> str:
    if status == "converted":
        return "usable"
    if status in {"validation_warning", "needs_review"}:
        return "needs_review"
    if status == "failed":
        return "blocked"
    return "unknown"


def _artifact_layer_for_file_kind(file_kind: str) -> str:
    if file_kind == "image":
        return "docling_extracted_image"
    if file_kind == "table":
        return "docling_table"
    return "docling_output_file"


def _malformed_source_identity(row: Mapping[str, Any]) -> bool:
    source_sha = str(row.get("source_sha256") or "")
    source_path = str(row.get("source_relative_path") or "")
    if not SHA256_RE.fullmatch(source_sha):
        return True
    if not source_path:
        return True
    path = Path(source_path)
    if path.is_absolute():
        return True
    return any(part == ".." for part in path.parts)


def _kh_candidate_status(record: Mapping[str, Any]) -> str:
    if record.get("status") in SUCCESS_STATUSES or record.get("status") == "available":
        return "candidate"
    if record.get("overlay_level") == FULL_OVERLAY_LEVEL:
        return "candidate"
    return "blocked"


def _overlay_quality_status(overlay_level: str) -> str:
    return OVERLAY_QUALITY_STATUS.get(overlay_level, "unknown")


def _visual_analysis_config(config: HarnessConfig) -> dict[str, Any]:
    return {
        "provider": config.visual_provider,
        "fallback_provider": config.visual_fallback_provider,
        "qwen_vision_model": config.qwen_vision_model,
        "qwen_ocr_model": config.qwen_ocr_model,
        "endpoint_region": config.qwen_endpoint_region,
        "base_url_configured": bool(config.qwen_base_url),
        "api_key_configured": config.qwen_api_key_configured,
    }


def _provider_config_blockers(config: HarnessConfig) -> list[str]:
    blockers: list[str] = []
    if config.visual_provider != "qwen":
        blockers.append(f"visual_provider_not_qwen:{config.visual_provider}")
    if config.visual_fallback_provider != "gemini":
        blockers.append(f"visual_fallback_provider_not_gemini:{config.visual_fallback_provider}")
    if config.qwen_vision_model != DEFAULT_QWEN_VISION_MODEL:
        blockers.append(f"qwen_vision_model_mismatch:{config.qwen_vision_model}")
    if config.qwen_endpoint_region != DEFAULT_QWEN_ENDPOINT_REGION:
        blockers.append(f"qwen_endpoint_region_mismatch:{config.qwen_endpoint_region}")
    return blockers


def _cag_crosswalk_blockers(
    crosswalk: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
) -> list[str]:
    if not crosswalk or not cag_candidates:
        return []
    by_package = {str(row.get("package_key") or ""): str(row.get("cag_pack_id") or "") for row in crosswalk}
    missing_links = 0
    for candidate in cag_candidates:
        cag_pack_id = str(candidate.get("cag_pack_id") or "")
        for package_key in candidate.get("evidence_package_keys", []):
            if by_package.get(str(package_key or "")) != cag_pack_id:
                missing_links += 1
    return [f"cag_crosswalk_missing_links:{missing_links}"] if missing_links else []


def _crosswalk_status(kh: Mapping[str, Any], graph: Mapping[str, Any]) -> str:
    if kh and graph:
        return "linked"
    if kh or graph:
        return "partial"
    return "missing"


def _group_first(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    grouped: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in grouped:
            grouped[value] = row
    return grouped


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:96] or "item"


def find_public_leaks(value: Any) -> list[str]:
    leaks: list[str] = []
    for text in _iter_strings(value):
        if LEAK_RE.search(text) or SECRET_RE.search(text) or BARE_SECRET_RE.search(text):
            leaks.append(f"{stable_hash(text)[:16]}:{_public_string(text)[:180]}")
    return leaks


def _read_phase_artifacts(config: HarnessConfig, phases: Sequence[PhaseResult]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for phase in phases:
        for relative_path in phase.output_paths:
            path = config.run_dir / relative_path
            if not path.is_file():
                continue
            try:
                payload[relative_path] = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                payload[relative_path] = f"<artifact_read_error:{type(exc).__name__}>"
    return payload


def _public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = _public_key(str(key))
            if _is_sensitive_public_key(key_text):
                sanitized[key_text] = "<redacted:secret>"
            else:
                sanitized[key_text] = _public_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_public_payload(item) for item in value]
    if isinstance(value, Path):
        return _public_string(str(value))
    if isinstance(value, str):
        return _public_string(value)
    return value


def _is_sensitive_public_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(key)) and not key.lower().endswith("_configured")


def _public_key(key: str) -> str:
    if LEAK_RE.search(key) or SECRET_RE.search(key) or BARE_SECRET_RE.search(key):
        return f"<redacted:key:{stable_hash(key)[:12]}>"
    return _public_string(key)


def _public_string(value: str) -> str:
    redacted = SECRET_RE.sub(lambda match: f"{match.group(1)}=<redacted:secret>", value)
    redacted = BARE_SECRET_RE.sub("<redacted:secret>", redacted)
    return _public_path(redacted)


def _public_path(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        path = Path(text)
        if path.is_absolute():
            resolved = path.resolve()
            try:
                return resolved.relative_to(DEFAULT_PUBLIC_ROOT).as_posix()
            except ValueError:
                return "<redacted:absolute_path>"
    except (OSError, ValueError):
        pass
    return LEAK_RE.sub("<redacted:absolute_path>", text)


def _resolve_public_path(value: Any) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    return (DEFAULT_PUBLIC_ROOT / path).resolve()


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iter_strings(item)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            yield payload


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)


def _write_markdown_report(config: HarnessConfig, proof: Mapping[str, Any], certification: Mapping[str, Any]) -> None:
    lines = [
        "# Post-Docling P0-P8 Harness Report",
        "",
        f"- Run id: `{config.run_id}`",
        f"- Dry run: `{str(not config.apply).lower()}`",
        f"- Docling converted total: `{proof.get('converted_total')}`",
        f"- Certification ok: `{str(bool(certification.get('ok'))).lower()}`",
        f"- Mutation performed: `{str(bool(certification.get('mutation_performed'))).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = certification.get("blockers") if isinstance(certification.get("blockers"), list) else []
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- None")
    lines.append("")
    _write_text_atomic(config.run_dir / "report.md", "\n".join(lines))


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)


def _count_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "unknown") for row in rows).items()))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


def _public_exception_blocker(exc: Exception) -> str:
    return f"{type(exc).__name__}:{_public_string(str(exc))[:180]}"


def _any_env(*names: str) -> bool:
    return bool(_first_env(*names))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the post-Docling P0-P8 ingest/index dry-run harness.")
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--full-run", type=Path, default=DEFAULT_FULL_RUN)
    parser.add_argument("--pending-run", type=Path, default=DEFAULT_PENDING_RUN)
    parser.add_argument("--retry-run", type=Path, default=DEFAULT_RETRY_RUN)
    parser.add_argument("--overlay-run", type=Path, default=DEFAULT_OVERLAY_RUN)
    parser.add_argument("--expected-total", type=int, default=DEFAULT_EXPECTED_TOTAL)
    parser.add_argument("--visual-provider", default="qwen")
    parser.add_argument("--visual-fallback-provider", default="gemini")
    parser.add_argument("--qwen-vision-model", default=os.getenv("QWEN_VISION_MODEL", DEFAULT_QWEN_VISION_MODEL))
    parser.add_argument("--qwen-ocr-model", default=os.getenv("QWEN_OCR_MODEL", DEFAULT_QWEN_OCR_MODEL))
    parser.add_argument("--qwen-endpoint-region", default=os.getenv("QWEN_ENDPOINT_REGION", DEFAULT_QWEN_ENDPOINT_REGION))
    parser.add_argument("--qwen-base-url", default=_first_env("QWEN_BASE_URL", "DASHSCOPE_BASE_URL", "ALIBABA_QWEN_BASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Reserved for future apply paths; currently fails closed.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = HarnessConfig(
        run_id=args.run_id,
        artifact_root=args.artifact_root,
        full_run=args.full_run,
        pending_run=args.pending_run,
        retry_run=args.retry_run,
        overlay_run=args.overlay_run,
        expected_total=args.expected_total,
        apply=args.apply,
        visual_provider=args.visual_provider,
        visual_fallback_provider=args.visual_fallback_provider,
        qwen_vision_model=args.qwen_vision_model,
        qwen_ocr_model=args.qwen_ocr_model,
        qwen_endpoint_region=args.qwen_endpoint_region,
        qwen_base_url=args.qwen_base_url,
        qwen_api_key_configured=_any_env("QWEN_API_KEY", "DASHSCOPE_API_KEY", "ALIBABA_QWEN_API_KEY", "ALIBABA_API_KEY"),
    )
    result = run_all(config)
    print(json.dumps({"run_id": config.run_id, "run_dir": _public_path(config.run_dir), "ok": result["certification"]["ok"]}, indent=2))
    return 0 if result["certification"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
