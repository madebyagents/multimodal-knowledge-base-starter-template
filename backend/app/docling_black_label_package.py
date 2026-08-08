"""Black Label post-Docling package builder.

This module consumes a certified post-Docling P0-P8 dry-run and emits a
second-stage, dry-run-only package set for premium multimodal ingest planning.
It does not call visual providers, Knowledge Hub, or LightRAG apply endpoints.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import multiprocessing as mp
import os
import secrets
import stat
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from . import docling_kh_lightrag_cag_harness as p0p8
from .lightrag_cinema_craft_ingest import (
    DEFAULT_LIGHTRAG_BASE_URL,
    LightRAGClient,
    fetch_existing_document_index,
    public_error,
)

SCHEMA_VERSION = "docling_black_label_package.v1"
ASSET_REGISTRY_SCHEMA_VERSION = "black_label_asset_registry.v1"
CARD_SCHEMA_VERSION = "black_label_card_manifest.v1"
VISUAL_QUEUE_SCHEMA_VERSION = "black_label_visual_enrichment_queue.v1"
KH_PLAN_SCHEMA_VERSION = "black_label_kh_apply_plan.v1"
LIGHTRAG_PLAN_SCHEMA_VERSION = "black_label_lightrag_apply_plan.v1"
CAG_MANIFEST_SCHEMA_VERSION = "black_label_cag_pack_manifest.v1"
EVAL_SCHEMA_VERSION = "black_label_eval_suite.v1"
CERTIFICATION_SCHEMA_VERSION = "black_label_certification.v1"
GOVERNED_ROLLOUT_SCHEMA_VERSION = "dantedash.governed_corpus_rollout.v1"
GOVERNED_ROLLOUT_PROVENANCE = "governed_corpus_rollout_v1"
LEGACY_ROLLOUT_PROVENANCE = "legacy_p0p8_v1"
GOVERNED_P1_AUTHORIZATION_BLOCKER = "governed_p1_controller_not_authorized"
GOVERNED_P1_PROVENANCE_BLOCKER = "governed_p1_provenance_not_recognized"
LIGHTRAG_BINDING_MIGRATION_FILE = "lightrag-input-binding-migration.json"
LEGACY_SOURCE_ATTESTATION_SCHEMA_VERSION = "black_label_legacy_source_attestation.v1"
LEGACY_SOURCE_BUNDLE_BINDING_SCHEMA_VERSION = "black_label_source_bundle_binding.v1"
LEGACY_BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION = "black_label_generation_recipe.v1"
BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION = "black_label_generation_recipe.v2"
LIGHTRAG_FENCE_SCHEMA_VERSION = "black_label_lightrag_mutation_fence.v1"
LIGHTRAG_FENCE_RECEIPT_SCHEMA_VERSION = "black_label_lightrag_mutation_fence_receipt.v1"
LIGHTRAG_STAGE_CLAIM_SCHEMA_VERSION = "black_label_lightrag_stage_claim.v1"

DEFAULT_ARTIFACT_ROOT = Path("logs/black-label-docling")
DEFAULT_SOURCE_ROOT = Path("logs/post-docling-p0-p8-harness")
DEFAULT_QWEN_VISION_MODEL = p0p8.DEFAULT_QWEN_VISION_MODEL
DEFAULT_QWEN_OCR_MODEL = p0p8.DEFAULT_QWEN_OCR_MODEL
DEFAULT_QWEN_ENDPOINT_REGION = p0p8.DEFAULT_QWEN_ENDPOINT_REGION
DEFAULT_CARD_MAX_CHARS = 6000
DEFAULT_TEXT_READ_CHARS = 64000
DEFAULT_EVAL_THRESHOLD = 0.94
TEXT_FILE_KINDS = {"markdown", "text", "doctags"}
MEDIA_FILE_KINDS = {"image"}
TABLE_FILE_KINDS = {"table"}
CARD_ROLES = {
    "source_card",
    "concept_card",
    "relation_card",
    "visual_evidence_card",
    "craft_application_card",
    "retrieval_eval_card",
}
RIGHTS_BLOCK_PATTERNS = (
    "full screenplay",
    "full script",
    "subtitle dump",
    "lyrics",
    "long quote",
    "copied transcript",
    "full chapter",
    "full essay",
)
TOPIC_KEYWORDS = {
    "cinematography": ("cinematography", "camera", "lens", "wide", "close-up", "shot", "frame"),
    "lighting": ("lighting", "light", "shadow", "chiaroscuro", "exposure", "neon"),
    "editing-montage": ("editing", "montage", "cut", "continuity", "sequence"),
    "directing": ("directing", "director", "actor", "performance", "blocking"),
    "camera-movement": ("movement", "dolly", "crane", "handheld", "tracking", "steadicam"),
    "color-art-direction": ("color", "production-design", "art-direction", "costume", "palette"),
    "documentary-ethics": ("documentary", "ethics", "reality", "archive", "witness"),
    "advertising-film": ("advertising", "commercial", "brand", "product", "campaign"),
    "visual-prompt-translation": ("ai", "prompt", "reference", "translation", "image"),
}

CommandName = Literal[
    "run-all",
    "refresh-certification",
    "migrate-legacy-bindings",
    "apply-lightrag-sample",
    "apply-lightrag-stage",
]
LightRAGApplyStage = Literal[
    "one_document_sample",
    "five_document_sample",
    "topic_cluster_sample",
    "full_corpus_after_certification",
]
LIGHTRAG_SAMPLE_LEDGER = "lightrag-sample-apply-ledger.json"
LIGHTRAG_STAGE_ORDER: tuple[LightRAGApplyStage, ...] = (
    "one_document_sample",
    "five_document_sample",
    "topic_cluster_sample",
    "full_corpus_after_certification",
)
LIGHTRAG_STAGE_LEDGER_FILES: dict[str, str] = {
    "one_document_sample": LIGHTRAG_SAMPLE_LEDGER,
    "five_document_sample": "lightrag-five-document-sample-apply-ledger.json",
    "topic_cluster_sample": "lightrag-topic-cluster-sample-apply-ledger.json",
    "full_corpus_after_certification": "lightrag-full-corpus-apply-ledger.json",
}
LIGHTRAG_STAGE_LIMITS: dict[str, int | None] = {
    "one_document_sample": 1,
    "five_document_sample": 5,
    "topic_cluster_sample": 100,
    "full_corpus_after_certification": None,
}
LIGHTRAG_STAGE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "one_document_sample": (),
    "five_document_sample": ("one_document_sample",),
    "topic_cluster_sample": ("five_document_sample",),
    "full_corpus_after_certification": ("one_document_sample", "five_document_sample", "topic_cluster_sample"),
}
LIGHTRAG_ROLE_PRIORITY = {
    "source_card": 0,
    "concept_card": 1,
    "relation_card": 2,
    "craft_application_card": 3,
    "visual_evidence_card": 4,
    "retrieval_eval_card": 5,
}
DEFAULT_LIGHTRAG_BATCH_MAX_CARDS = 25
DEFAULT_LIGHTRAG_BATCH_MAX_CHARS = 60000
FULL_CORPUS_QUERY_RECOVERY_LIMIT = 10
LIGHTRAG_QUERY_RECOVERY_LIMITS: dict[str, int] = {
    "one_document_sample": 1,
    "five_document_sample": 5,
    "topic_cluster_sample": 10,
    "full_corpus_after_certification": FULL_CORPUS_QUERY_RECOVERY_LIMIT,
}


@dataclass(frozen=True)
class BlackLabelConfig:
    run_id: str
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT
    source_run: Path | None = None
    black_label_run: Path | None = None
    source_root: Path = DEFAULT_SOURCE_ROOT
    apply: bool = False
    max_card_chars: int = DEFAULT_CARD_MAX_CHARS
    text_read_chars: int = DEFAULT_TEXT_READ_CHARS
    limit_pdfs: int | None = None
    visual_provider: str = "qwen"
    visual_fallback_provider: str = "gemini"
    qwen_vision_model: str = DEFAULT_QWEN_VISION_MODEL
    qwen_ocr_model: str = DEFAULT_QWEN_OCR_MODEL
    qwen_endpoint_region: str = DEFAULT_QWEN_ENDPOINT_REGION
    qwen_base_url: str = ""
    qwen_api_key_configured: bool = False
    eval_threshold: float = DEFAULT_EVAL_THRESHOLD
    lightrag_base_url: str = DEFAULT_LIGHTRAG_BASE_URL
    lightrag_timeout_s: float = 90.0
    lightrag_poll_interval_s: float = 5.0
    lightrag_poll_timeout_s: float = 1800.0
    lightrag_stage: LightRAGApplyStage = "one_document_sample"
    lightrag_batch_max_cards: int = DEFAULT_LIGHTRAG_BATCH_MAX_CARDS
    lightrag_batch_max_chars: int = DEFAULT_LIGHTRAG_BATCH_MAX_CHARS
    legacy_source_certification_hash: str = ""
    legacy_source_bundle_hash: str = ""

    @property
    def run_dir(self) -> Path:
        return _repo_path(self.artifact_root) / self.run_id


@dataclass(frozen=True)
class SourceBundle:
    run_dir: Path
    certification: dict[str, Any]
    normalized: list[dict[str, Any]]
    crosswalk: list[dict[str, Any]]
    cag_candidates: list[dict[str, Any]]
    text_artifacts: dict[str, dict[str, Any]]
    binding: dict[str, Any]


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    name: str
    status: str
    output_paths: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    mutation_performed: bool = False
    blockers: list[str] = field(default_factory=list)


def build_run_id() -> str:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"docling-black-label-{timestamp}-{secrets.token_hex(8)}"


def run_all(config: BlackLabelConfig) -> dict[str, Any]:
    if config.apply:
        raise ValueError("apply_mode_not_implemented_for_black_label_docling")
    generation_blocker = _generation_config_blocker(config)
    if generation_blocker:
        raise ValueError(generation_blocker)
    try:
        config.run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"black_label_run_already_exists:{_public_path(config.run_dir)}") from exc
    source = load_source_bundle(config)
    return _run_all_from_source(config, source)


def _run_all_from_source(config: BlackLabelConfig, source: SourceBundle) -> dict[str, Any]:
    """Build one run from an immutable in-memory source snapshot."""
    phases: list[PhaseResult] = []

    registry, phase = build_asset_registry(config, source)
    phases.append(phase)
    visual_queue, phase = build_visual_enrichment_queue(config, registry)
    phases.append(phase)
    cards, phase = build_black_label_cards(config, source, registry, visual_queue)
    phases.append(phase)
    kh_plan, phase = build_kh_apply_plan(config, registry, cards)
    phases.append(phase)
    lightrag_plan, phase = build_lightrag_apply_plan(config, cards)
    phases.append(phase)
    cag_manifest, phase = build_cag_manifest(config, cards, lightrag_plan)
    phases.append(phase)
    eval_suite, phase = build_eval_suite(config, cards, cag_manifest)
    phases.append(phase)
    certification, phase = certify_run(
        config,
        source,
        phases,
        registry,
        visual_queue,
        cards,
        kh_plan,
        lightrag_plan,
        cag_manifest,
        eval_suite,
    )
    phases.append(phase)

    ledger = {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.run_id,
        "source_run": _public_path(source.run_dir),
        "dry_run": not config.apply,
        "mutation_performed": any(phase.mutation_performed for phase in phases),
        "phases": [asdict(phase) for phase in phases],
    }
    _write_json(config.run_dir / "phase-ledger.json", ledger)
    _write_report(config, certification)
    return {"ledger": ledger, "certification": certification}


def apply_lightrag_sample(config: BlackLabelConfig, *, client: Any | None = None) -> dict[str, Any]:
    """Compatibility wrapper for the first-card LightRAG sample stage."""
    return apply_lightrag_stage(replace(config, lightrag_stage="one_document_sample"), client=client)


def apply_lightrag_stage(config: BlackLabelConfig, *, client: Any | None = None) -> dict[str, Any]:
    """Apply a staged set of curated LightRAG cards and verify query recovery."""
    stage = _normalize_lightrag_stage(config.lightrag_stage)
    run_dir = _resolve_black_label_run(config)
    stage_ledger_path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[stage]
    stage_claim_path = run_dir / f".{LIGHTRAG_STAGE_LEDGER_FILES[stage]}.claim"
    stage_claim_acquired = False
    persist_stage_ledger = True
    replay_blocker = _lightrag_stage_replay_blocker(stage_ledger_path, stage)
    if replay_blocker:
        return _lightrag_stage_ledger(
            config,
            run_dir,
            stage=stage,
            candidates=[],
            batches=[],
            blockers=[replay_blocker],
        )
    try:
        plan_rows = list(_read_jsonl(run_dir / "lightrag-card-apply-plan.jsonl"))
        cards = list(_read_jsonl(run_dir / "black-label-card-manifest.jsonl"))
        (
            input_bindings,
            input_binding_blockers,
            black_label_certification_hash,
        ) = _current_lightrag_input_bindings(
            config,
            run_dir,
            cards=cards,
            lightrag_plan=plan_rows,
        )
    except Exception as exc:  # noqa: BLE001
        ledger = _lightrag_stage_ledger(config, run_dir, stage=stage, candidates=[], batches=[])
        ledger["blockers"] = [f"{exc.__class__.__name__}:{public_error(exc)[:180]}"]
        _write_json(stage_ledger_path, _public_payload(ledger))
        return ledger
    try:
        prereq_blockers = _lightrag_stage_prerequisite_blockers(
            config,
            run_dir,
            stage,
            input_bindings=input_bindings,
            input_binding_blockers=input_binding_blockers,
        )
        card_by_id = _first_by(cards, "card_id")
        prior_card_ids = _lightrag_prior_stage_card_ids(run_dir, stage)
        prior_source_keys = _lightrag_prior_stage_source_keys(run_dir, stage)
        candidates = _select_lightrag_stage_candidates(
            stage,
            plan_rows,
            card_by_id,
            exclude_card_ids=prior_card_ids,
            prior_source_keys=prior_source_keys,
        )
        batches = _lightrag_stage_batches(candidates, config)
        ledger = _lightrag_stage_ledger(
            config,
            run_dir,
            stage=stage,
            candidates=candidates,
            batches=batches,
            input_bindings=input_bindings,
        )
        if prereq_blockers:
            ledger["blockers"] = prereq_blockers
            return ledger
        if stage == "five_document_sample":
            expected_new_sources = max(0, int(LIGHTRAG_STAGE_LIMITS[stage] or 5) - len(prior_source_keys))
            selected_source_keys = {_lightrag_candidate_source_key(candidate) for candidate in candidates}
            cumulative_source_keys = prior_source_keys | selected_source_keys
            if len(candidates) != expected_new_sources or len(cumulative_source_keys) != int(
                LIGHTRAG_STAGE_LIMITS[stage] or 5
            ):
                ledger["blockers"] = [
                    f"five_document_cumulative_source_count_mismatch:"
                    f"{len(cumulative_source_keys)}!=5"
                ]
                return ledger
        if not candidates:
            ledger["blockers"] = [f"no_{stage}_candidate"]
            return ledger
        if stage == "full_corpus_after_certification" and not batches:
            ledger["blockers"] = ["full_corpus_batch_manifest_missing"]
            return ledger

        own_client = client is None
        lightrag = client or LightRAGClient(base_url=config.lightrag_base_url, timeout_s=config.lightrag_timeout_s)
        try:
            fencing_blocker = _lightrag_fencing_capability_blocker(lightrag)
            if fencing_blocker:
                ledger["blockers"] = [fencing_blocker]
                return ledger
            claim_payload = _lightrag_stage_claim_payload(
                run_dir,
                stage,
                input_bindings,
                black_label_certification_hash,
                candidates,
                batches,
            )
            try:
                _write_exclusive_json(stage_claim_path, claim_payload)
            except FileExistsError:
                persist_stage_ledger = False
                ledger["blockers"] = [f"existing_stage_claim_blocks_apply:{stage}"]
                return ledger
            stage_claim_acquired = True
            preflight = _lightrag_preflight(lightrag)
            ledger["preflight"] = preflight
            blockers = list(preflight.get("blockers") or [])
            if blockers:
                ledger["blockers"] = blockers
                return ledger

            candidate_by_card_id = {str(candidate["card_id"]): candidate for candidate in candidates}
            existing_sources, existing_source_error = _lightrag_existing_file_sources(
                lightrag,
                required=stage == "full_corpus_after_certification" or isinstance(lightrag, LightRAGClient),
            )
            if existing_source_error:
                ledger["blockers"] = [existing_source_error]
                return ledger
            duplicate_sources = existing_sources & {str(candidate["file_source"]) for candidate in candidates}
            if duplicate_sources:
                ledger["skipped_sources"] = sorted(duplicate_sources)
            sent_count = 0
            inserted_candidates: list[Mapping[str, Any]] = []
            for batch in batches:
                batch_candidates: list[Mapping[str, Any]] = []
                for card_id in batch.get("card_ids", []):
                    candidate = candidate_by_card_id.get(str(card_id))
                    if candidate is None or str(candidate["file_source"]) in duplicate_sources:
                        continue
                    batch_candidates.append(candidate)
                if not batch_candidates:
                    continue
                fence_request = _lightrag_fence_request(
                    run_dir,
                    stage,
                    input_bindings,
                    black_label_certification_hash,
                    batch,
                    batch_candidates,
                    timeout_s=config.lightrag_poll_timeout_s,
                )
                ledger["mutation_attempted"] = True
                ledger["mutation_state"] = "dispatching"
                ledger["pending_fence"] = {
                    "batch_id": batch.get("batch_id"),
                    "fence_token": fence_request.get("fence_token"),
                    "binding_hash": fence_request.get("binding_hash"),
                }
                _write_json(stage_ledger_path, _public_payload(ledger))
                insert_response = lightrag.insert_texts_once(
                    [str(candidate["payload"]) for candidate in batch_candidates],
                    [str(candidate["file_source"]) for candidate in batch_candidates],
                    fence_request=fence_request,
                )
                safe_response = _public_payload(insert_response)
                safe_response["batch_id"] = batch.get("batch_id")
                ledger.setdefault("insert_responses", []).append(safe_response)
                if str(insert_response.get("status", "")).lower() == "failure":
                    ledger["mutation_state"] = "rejected_or_uncertain"
                    ledger["blockers"] = [f"lightrag_insert_failure:{batch.get('batch_id')}"]
                    return ledger
                ledger["mutation_performed"] = True
                ledger["mutation_state"] = "receipt_pending"
                if not _lightrag_fence_receipt_valid(insert_response, fence_request):
                    ledger["blockers"] = [f"lightrag_fence_receipt_invalid:{batch.get('batch_id')}"]
                    return ledger
                sent_count += len(batch_candidates)
                ledger["mutation_state"] = "confirmed"
                ledger.pop("pending_fence", None)
                inserted_candidates.extend(batch_candidates)
                ledger["sent_count"] = sent_count
                ledger["mutation_performed"] = sent_count > 0
                ledger.setdefault("applied_batch_ids", []).append(batch.get("batch_id"))
                _write_json(run_dir / LIGHTRAG_STAGE_LEDGER_FILES[stage], _public_payload(ledger))
                preflight_all = _all_count(preflight.get("status_counts", {}))
                settled = lightrag.wait_until_settled(
                    interval_s=config.lightrag_poll_interval_s,
                    timeout_s=config.lightrag_poll_timeout_s,
                    min_total_count=preflight_all + sent_count,
                )
                ledger.setdefault("batch_settlements", []).append(_public_payload({"batch_id": batch.get("batch_id"), **settled}))
                final_counts = lightrag.status_counts()
                ledger["final_pipeline_status"] = _public_payload(settled)
                ledger["final_status_counts"] = _public_payload(final_counts)
                blockers = _lightrag_postflight_blockers(preflight, settled, final_counts, expected_increment=sent_count)
                if blockers:
                    ledger["blockers"] = blockers
                    return ledger

            ledger["sent_count"] = sent_count
            ledger["mutation_performed"] = sent_count > 0
            if "final_status_counts" not in ledger:
                final_pipeline = lightrag.pipeline_status()
                final_counts = lightrag.status_counts()
                settled = {
                    **_public_payload(final_pipeline),
                    "settled": not final_pipeline.get("busy") and not final_pipeline.get("request_pending"),
                    "total_count": _all_count(final_counts),
                }
                ledger["final_pipeline_status"] = _public_payload(settled)
                ledger["final_status_counts"] = _public_payload(final_counts)
                blockers = _lightrag_postflight_blockers(preflight, settled, final_counts, expected_increment=sent_count)
                if blockers:
                    ledger["blockers"] = blockers
                    return ledger

            recovery_blockers = _verify_lightrag_stage_recovery(
                lightrag,
                stage,
                _lightrag_recovery_candidates(candidates, inserted_candidates, duplicate_sources),
                duplicate_sources,
                query_timeout_s=config.lightrag_timeout_s,
            )
            ledger["query_recovery"] = recovery_blockers["query_recovery"]
            if recovery_blockers["blockers"]:
                ledger["blockers"] = recovery_blockers["blockers"]
                return ledger

            ledger["ok"] = True
            ledger["blockers"] = []
            return ledger
        finally:
            if own_client:
                close = getattr(lightrag, "close", None)
                if callable(close):
                    close()
    except Exception as exc:  # noqa: BLE001
        ledger = locals().get("ledger") or _lightrag_stage_ledger(
            config,
            run_dir,
            stage=stage,
            candidates=[],
            batches=[],
            input_bindings=input_bindings,
        )
        if ledger.get("mutation_attempted") and not ledger.get("mutation_performed"):
            ledger["mutation_state"] = "uncertain"
        ledger["blockers"] = [f"{exc.__class__.__name__}:{public_error(exc)[:180]}"]
        return ledger
    finally:
        ledger.setdefault("insert_responses", [])
        ledger.setdefault("insert_response", ledger["insert_responses"][0] if ledger["insert_responses"] else None)
        if (
            stage_claim_acquired
            and not ledger.get("mutation_performed")
            and not ledger.get("mutation_attempted")
        ):
            stage_claim_path.unlink(missing_ok=True)
        if persist_stage_ledger:
            _write_json(run_dir / LIGHTRAG_STAGE_LEDGER_FILES[stage], _public_payload(ledger))


def _source_certification_contract_blockers(certification: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if certification.get("schema_version") != p0p8.CERTIFICATION_SCHEMA_VERSION:
        blockers.append("source_p0_p8_certification_schema_invalid")
    if certification.get("ok") is not True:
        blockers.append("black_label_source_not_certified")
    if certification.get("dry_run") is not True:
        blockers.append("source_p0_p8_certification_not_dry_run")
    if certification.get("mutation_performed") is not False:
        blockers.append("black_label_source_mutated")
    recorded_blockers = certification.get("blockers")
    if not isinstance(recorded_blockers, list) or recorded_blockers:
        blockers.append("source_p0_p8_certification_has_blockers")
    return blockers


def _read_json_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"source_bundle_json_not_object:{path.name}")
    return payload


def _read_jsonl_snapshot(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"source_bundle_jsonl_row_not_object:{path.name}:{index}")
        rows.append(row)
    return rows


def _validate_source_bundle_rows(
    certification: Mapping[str, Any],
    normalized: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
) -> None:
    counts = certification.get("counts")
    if not isinstance(counts, Mapping):
        raise ValueError("source_p0_p8_certification_counts_invalid")
    expected_counts = {
        "normalized_records": len(normalized),
        "crosswalk_rows": len(crosswalk),
        "cag_candidates": len(cag_candidates),
    }
    for key, expected in expected_counts.items():
        if _safe_int(counts.get(key)) != expected:
            raise ValueError(f"source_bundle_count_mismatch:{key}")
    schema_contracts = (
        (normalized, p0p8.NORMALIZED_SCHEMA_VERSION, "normalized"),
        (crosswalk, p0p8.CROSSWALK_SCHEMA_VERSION, "crosswalk"),
        (cag_candidates, p0p8.CAG_SCHEMA_VERSION, "cag"),
    )
    for rows, expected_schema, label in schema_contracts:
        if any(row.get("schema_version") != expected_schema for row in rows):
            raise ValueError(f"source_bundle_schema_mismatch:{label}")


def _snapshot_text_artifacts(
    normalized: Sequence[Mapping[str, Any]],
    *,
    text_read_chars: int,
) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for row in normalized:
        file_kind = str(row.get("output_file_kind") or "")
        artifact_layer = str(row.get("artifact_layer") or "")
        if file_kind not in TEXT_FILE_KINDS and artifact_layer != "docling_output_file":
            continue
        package_key = str(row.get("package_key") or "")
        if not package_key or package_key in snapshots:
            raise ValueError("source_text_artifact_package_key_invalid")
        path_text = str(row.get("output_relative_path") or "")
        declared_hash = str(row.get("artifact_sha256") or "")
        path = _repo_path(path_text)
        snapshot: dict[str, Any] = {
            "package_key": package_key,
            "status": "unavailable",
            "artifact_sha256": "",
            "declared_artifact_sha256": declared_hash,
            "byte_count": 0,
            "sample": "",
            "sample_chars": 0,
            "truncated": False,
        }
        if path_text and path.is_file():
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                with os.fdopen(descriptor, "rb") as handle:
                    before_stat = os.fstat(handle.fileno())
                    if not stat.S_ISREG(before_stat.st_mode):
                        raise ValueError("source_text_artifact_not_regular_file")
                    digest = hashlib.sha256()
                    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                    sample_parts: list[str] = []
                    sample_chars_remaining = text_read_chars + 1
                    observed_bytes = 0
                    while chunk := handle.read(1024 * 1024):
                        observed_bytes += len(chunk)
                        digest.update(chunk)
                        if sample_chars_remaining > 0:
                            decoded = decoder.decode(chunk, final=False)
                            sample_parts.append(decoded[:sample_chars_remaining])
                            sample_chars_remaining -= len(sample_parts[-1])
                    if sample_chars_remaining > 0:
                        final_text = decoder.decode(b"", final=True)
                        sample_parts.append(final_text[:sample_chars_remaining])
                    after_stat = os.fstat(handle.fileno())
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            if (
                (before_stat.st_dev, before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns)
                != (after_stat.st_dev, after_stat.st_ino, after_stat.st_size, after_stat.st_mtime_ns)
                or observed_bytes != after_stat.st_size
            ):
                raise ValueError("source_text_artifact_changed_during_snapshot")
            try:
                current_stat = path.stat(follow_symlinks=False)
            except (FileNotFoundError, OSError) as exc:
                raise ValueError("source_text_artifact_path_changed_during_snapshot") from exc
            if stat.S_ISLNK(current_stat.st_mode) or (
                current_stat.st_dev,
                current_stat.st_ino,
            ) != (
                after_stat.st_dev,
                after_stat.st_ino,
            ):
                raise ValueError("source_text_artifact_path_changed_during_snapshot")
            artifact_hash = digest.hexdigest()
            if declared_hash and not secrets.compare_digest(declared_hash, artifact_hash):
                raise ValueError("source_text_artifact_hash_mismatch")
            sample = "".join(sample_parts)
            bounded_sample = sample[:text_read_chars]
            snapshot.update(
                {
                    "status": "available",
                    "artifact_sha256": artifact_hash,
                    "byte_count": observed_bytes,
                    "sample": bounded_sample,
                    "sample_chars": len(bounded_sample),
                    "truncated": len(sample) > text_read_chars or observed_bytes > len(bounded_sample),
                }
            )
        snapshots[package_key] = snapshot
    return snapshots


def _source_bundle_binding(
    certification: Mapping[str, Any],
    normalized: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
    text_artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    text_bindings = [
        {
            key: value
            for key, value in text_artifacts[package_key].items()
            if key not in {"sample", "sample_chars", "truncated"}
        }
        for package_key in sorted(text_artifacts)
    ]
    binding = {
        "schema_version": LEGACY_SOURCE_BUNDLE_BINDING_SCHEMA_VERSION,
        "component_hashes": {
            "p0_p8_certification": stable_hash(certification),
            "docling_normalized_output": stable_hash(list(normalized)),
            "package_crosswalk": stable_hash(list(crosswalk)),
            "cag_pack_candidates": stable_hash(list(cag_candidates)),
            "text_artifacts": stable_hash(text_bindings),
        },
        "component_counts": {
            "normalized_records": len(normalized),
            "crosswalk_rows": len(crosswalk),
            "cag_candidates": len(cag_candidates),
            "text_artifacts": len(text_bindings),
        },
    }
    binding["source_bundle_hash"] = stable_hash(binding)
    return binding


def load_source_bundle(config: BlackLabelConfig) -> SourceBundle:
    run_dir = _repo_path(config.source_run) if config.source_run else _latest_certified_source_run(config.source_root)
    certification_path = run_dir / "p0-p8-certification.json"
    normalized_path = run_dir / "docling-normalized-output.jsonl"
    crosswalk_path = run_dir / "package-crosswalk.jsonl"
    cag_path = run_dir / "cag-pack-candidates.jsonl"
    missing = [path.name for path in (certification_path, normalized_path, crosswalk_path, cag_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"black_label_source_missing:{','.join(missing)}")

    certification = _read_json_snapshot(certification_path)
    contract_blockers = _source_certification_contract_blockers(certification)
    if contract_blockers:
        raise ValueError(contract_blockers[0])
    normalized = _read_jsonl_snapshot(normalized_path)
    crosswalk = _read_jsonl_snapshot(crosswalk_path)
    cag_candidates = _read_jsonl_snapshot(cag_path)
    _validate_source_bundle_rows(certification, normalized, crosswalk, cag_candidates)
    text_artifacts = _snapshot_text_artifacts(normalized, text_read_chars=config.text_read_chars)
    binding = _source_bundle_binding(certification, normalized, crosswalk, cag_candidates, text_artifacts)
    return SourceBundle(
        run_dir=run_dir,
        certification=certification,
        normalized=normalized,
        crosswalk=crosswalk,
        cag_candidates=cag_candidates,
        text_artifacts=text_artifacts,
        binding=binding,
    )


def refresh_black_label_certification(config: BlackLabelConfig) -> dict[str, Any]:
    run_dir = _resolve_black_label_run(config)
    existing_certification = json.loads((run_dir / "black-label-certification.json").read_text(encoding="utf-8"))
    generation_config, recipe_blockers = _config_with_generation_recipe(config, existing_certification)
    if recipe_blockers:
        raise ValueError(recipe_blockers[0])
    source_run = config.source_run or existing_certification.get("source_run")
    if not source_run:
        raise ValueError("black_label_source_run_missing_for_refresh")
    explicit_source_path = _source_certification_file(config.source_run)
    certified_source_path = _source_certification_file(existing_certification.get("source_run"))
    if config.source_run is not None and explicit_source_path is None:
        raise ValueError("explicit_source_run_unavailable")
    if explicit_source_path is not None and certified_source_path is not None:
        if explicit_source_path.resolve() != certified_source_path.resolve():
            raise ValueError("explicit_source_run_mismatch")
    source = load_source_bundle(replace(generation_config, source_run=Path(str(source_run))))
    registry = list(_read_jsonl(run_dir / "black-label-asset-registry.jsonl"))
    visual_queue = list(_read_jsonl(run_dir / "visual-enrichment-queue.jsonl"))
    cards = list(_read_jsonl(run_dir / "black-label-card-manifest.jsonl"))
    kh_plan = list(_read_jsonl(run_dir / "kh-multimodal-apply-plan.jsonl"))
    lightrag_plan = list(_read_jsonl(run_dir / "lightrag-card-apply-plan.jsonl"))
    cag_manifest = list(_read_jsonl(run_dir / "cag-pack-manifest.jsonl"))
    eval_suite = list(_read_jsonl(run_dir / "black-label-eval-suite.jsonl"))
    phase_ledger = json.loads((run_dir / "phase-ledger.json").read_text(encoding="utf-8"))
    phases = [
        PhaseResult(
            phase=str(row.get("phase") or ""),
            name=str(row.get("name") or ""),
            status=str(row.get("status") or ""),
            output_paths=[str(item) for item in row.get("output_paths", [])],
            counts={str(key): int(value) for key, value in row.get("counts", {}).items()},
            mutation_performed=bool(row.get("mutation_performed")),
            blockers=[str(item) for item in row.get("blockers", [])],
        )
        for row in phase_ledger.get("phases", [])
        if isinstance(row, Mapping)
    ]
    current_bindings = _lightrag_input_bindings(
        stable_hash(source.certification),
        str(source.binding.get("source_bundle_hash") or ""),
        cards,
        lightrag_plan,
    )
    canonical_bindings = _regenerated_lightrag_input_bindings(generation_config, source, run_dir)
    for key, expected in canonical_bindings.items():
        if current_bindings.get(key) != expected:
            raise ValueError(f"black_label_source_canonical_mismatch:{key}")
    binding_migration: dict[str, Any] | None = None
    if existing_certification.get("certified_input_bindings") != current_bindings:
        migration, migration_blockers = _validated_binding_migration(run_dir, current_bindings)
        if existing_certification.get("certified_input_bindings") is not None or migration is None:
            detail = migration_blockers[0] if migration_blockers else "certified_input_bindings_mismatch"
            raise ValueError(detail)
        binding_migration = migration
    elif (run_dir / LIGHTRAG_BINDING_MIGRATION_FILE).exists():
        migration, migration_blockers = _validated_binding_migration(run_dir, current_bindings)
        if migration is None:
            detail = migration_blockers[0] if migration_blockers else "legacy_binding_migration_invalid"
            raise ValueError(detail)
        binding_migration = migration
    refresh_config = replace(generation_config, run_id=run_dir.name, artifact_root=run_dir.parent)
    certification, _phase = certify_run(
        refresh_config,
        source,
        phases,
        registry,
        visual_queue,
        cards,
        kh_plan,
        lightrag_plan,
        cag_manifest,
        eval_suite,
    )
    if binding_migration is not None:
        certification["legacy_binding_migration"] = {
            "migration_id": binding_migration.get("migration_id"),
            "sidecar": LIGHTRAG_BINDING_MIGRATION_FILE,
            "sidecar_sha256": p0p8.sha256_file(run_dir / LIGHTRAG_BINDING_MIGRATION_FILE),
        }
        _write_json(run_dir / "black-label-certification.json", _public_payload(certification))
    _write_report(refresh_config, certification)
    return {"certification": certification, "run_dir": _public_path(run_dir)}


def migrate_legacy_lightrag_bindings(config: BlackLabelConfig, *, client: Any | None = None) -> dict[str, Any]:
    """Safely bind a pre-binding certified run without replaying prior writes."""
    run_dir = _resolve_black_label_run(config)
    certification = _load_black_label_certification(run_dir, require_green=False)
    source_run = config.source_run or certification.get("source_run")
    if not source_run:
        return _legacy_binding_migration_result(run_dir, blockers=["black_label_source_run_missing_for_migration"])
    certified_source_run = str(certification.get("source_run") or "")
    if config.source_run and certified_source_run and not certified_source_run.startswith("<redacted:"):
        if _repo_path(config.source_run) != _repo_path(certified_source_run):
            return _legacy_binding_migration_result(run_dir, blockers=["legacy_binding_source_run_mismatch"])
    generation_config, recipe_blockers = _config_with_generation_recipe(config, certification)
    if recipe_blockers:
        return _legacy_binding_migration_result(run_dir, blockers=recipe_blockers)
    try:
        source = load_source_bundle(replace(generation_config, source_run=Path(str(source_run))))
        cards = list(_read_jsonl(run_dir / "black-label-card-manifest.jsonl"))
        lightrag_plan = list(_read_jsonl(run_dir / "lightrag-card-apply-plan.jsonl"))
    except Exception as exc:  # noqa: BLE001
        return _legacy_binding_migration_result(
            run_dir,
            blockers=[f"legacy_binding_migration_input_error:{exc.__class__.__name__}"],
        )

    bindings = _lightrag_input_bindings(
        stable_hash(source.certification),
        str(source.binding.get("source_bundle_hash") or ""),
        cards,
        lightrag_plan,
    )
    blockers: list[str] = []
    if certification.get("schema_version") != CERTIFICATION_SCHEMA_VERSION:
        blockers.append("black_label_certification_schema_invalid")
    if certification.get("ok") is not True or list(certification.get("blockers") or []):
        blockers.append("black_label_certification_not_green")
    if certification.get("dry_run") is not True or certification.get("mutation_performed") is not False:
        blockers.append("black_label_certification_not_safe_for_migration")
    recorded_source_hash = certification.get("source_p0_p8_certification_hash")
    if recorded_source_hash is not None and recorded_source_hash != bindings["source_p0_p8_certification_hash"]:
        blockers.append("source_p0_p8_certification_hash_mismatch")
    (
        source_rollout_schema,
        source_rollout_provenance,
        source_authorization,
        source_legacy_attestation,
    ) = _source_rollout_authorization(
        source.certification,
        source_bundle_binding=source.binding,
        legacy_source_certification_hash=config.legacy_source_certification_hash,
        legacy_source_bundle_hash=config.legacy_source_bundle_hash,
    )
    blockers.extend(_governed_p1_blockers(source_authorization))
    source_fields = {
        "source_rollout_schema_version": source_rollout_schema,
        "source_rollout_provenance": source_rollout_provenance,
        "source_governed_p1_authorization": source_authorization,
        "source_legacy_attestation": source_legacy_attestation,
        "source_bundle_binding": source.binding,
    }
    for key, expected in source_fields.items():
        if key in certification and certification.get(key) != expected:
            blockers.append(f"legacy_binding_source_authorization_mismatch:{key}")
    if any(key in certification for key in ("rollout_schema_version", "rollout_provenance", "governed_p1_authorization")):
        blockers.append("legacy_binding_direct_authorization_not_allowed")
    recorded_bindings = certification.get("certified_input_bindings")
    if "certified_input_bindings" in certification:
        if recorded_bindings == bindings:
            blockers.append("legacy_binding_migration_not_required")
        else:
            blockers.append("certified_input_bindings_mismatch")
    if blockers:
        return _legacy_binding_migration_result(run_dir, blockers=blockers, bindings=bindings)

    try:
        canonical_bindings = _regenerated_lightrag_input_bindings(generation_config, source, run_dir)
    except Exception as exc:  # noqa: BLE001
        return _legacy_binding_migration_result(
            run_dir,
            blockers=[f"legacy_binding_canonical_regeneration_error:{exc.__class__.__name__}"],
            bindings=bindings,
        )
    for key, expected in canonical_bindings.items():
        if bindings.get(key) != expected:
            blockers.append(f"legacy_binding_canonical_mismatch:{key}")
    if blockers:
        return _legacy_binding_migration_result(run_dir, blockers=blockers, bindings=bindings)

    existing_migration, migration_blockers = _validated_binding_migration(run_dir, bindings)
    if existing_migration is not None:
        return _legacy_binding_migration_result(
            run_dir,
            ok=True,
            bindings=bindings,
            migrated_stages=[str(row.get("stage") or "") for row in existing_migration.get("migrated_stage_ledgers", [])],
        )
    if (run_dir / LIGHTRAG_BINDING_MIGRATION_FILE).exists():
        return _legacy_binding_migration_result(run_dir, blockers=migration_blockers, bindings=bindings)

    try:
        stage_records, ledger_blockers = _verified_legacy_stage_ledger_records(
            generation_config,
            run_dir,
            cards,
            lightrag_plan,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001
        return _legacy_binding_migration_result(
            run_dir,
            blockers=[f"legacy_binding_live_recovery_error:{exc.__class__.__name__}"],
            bindings=bindings,
        )
    if ledger_blockers:
        return _legacy_binding_migration_result(run_dir, blockers=ledger_blockers, bindings=bindings)
    migrated_stages = [str(record.get("stage") or "") for record in stage_records]

    migration_record = {
        "schema_version": "black_label_legacy_binding_migration.v1",
        "mode": "canonical_regeneration_and_live_read_only_recovery",
        "migrated_stages": migrated_stages,
        "migrated_stage_ledgers": stage_records,
        "mutation_replayed": False,
        "legacy_certification_sha256": p0p8.sha256_file(run_dir / "black-label-certification.json"),
        "certified_input_bindings": bindings,
        "source_legacy_attestation": source_legacy_attestation,
        "source_bundle_binding": source.binding,
    }
    migration_record["migration_id"] = stable_hash(migration_record)
    try:
        _write_json(run_dir / LIGHTRAG_BINDING_MIGRATION_FILE, _public_payload(migration_record))
    except OSError as exc:
        return _legacy_binding_migration_result(
            run_dir,
            blockers=[f"legacy_binding_sidecar_write_error:{exc.__class__.__name__}"],
            bindings=bindings,
        )
    return _legacy_binding_migration_result(
        run_dir,
        ok=True,
        bindings=bindings,
        migrated_stages=migrated_stages,
    )


def _legacy_binding_migration_result(
    run_dir: Path,
    *,
    ok: bool = False,
    blockers: Sequence[str] = (),
    bindings: Mapping[str, str] | None = None,
    migrated_stages: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "ok": ok,
        "run_dir": _public_path(run_dir),
        "blockers": list(blockers),
        "certified_input_bindings": dict(bindings or {}),
        "migrated_stages": list(migrated_stages),
        "mutation_performed": False,
        "mutation_attempted": False,
        "mutation_state": "not_attempted",
    }


def _validated_binding_migration(
    run_dir: Path,
    current_bindings: Mapping[str, str],
) -> tuple[dict[str, Any] | None, list[str]]:
    path = run_dir / LIGHTRAG_BINDING_MIGRATION_FILE
    if not path.exists():
        return None, ["legacy_binding_migration_missing"]
    try:
        migration = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ["legacy_binding_migration_unreadable"]
    if not isinstance(migration, dict) or migration.get("schema_version") != "black_label_legacy_binding_migration.v1":
        return None, ["legacy_binding_migration_schema_invalid"]
    if migration.get("mutation_replayed") is not False:
        return None, ["legacy_binding_migration_replay_state_invalid"]
    expected_migration_id = stable_hash({key: value for key, value in migration.items() if key != "migration_id"})
    if migration.get("migration_id") != expected_migration_id:
        return None, ["legacy_binding_migration_id_mismatch"]
    if migration.get("certified_input_bindings") != dict(current_bindings):
        return None, ["legacy_binding_migration_input_bindings_mismatch"]
    source_bundle_binding = migration.get("source_bundle_binding")
    if not isinstance(source_bundle_binding, Mapping):
        return None, ["legacy_source_bundle_binding_invalid"]
    expected_bundle_hash = stable_hash(
        {key: value for key, value in source_bundle_binding.items() if key != "source_bundle_hash"}
    )
    if (
        source_bundle_binding.get("schema_version") != LEGACY_SOURCE_BUNDLE_BINDING_SCHEMA_VERSION
        or source_bundle_binding.get("source_bundle_hash") != expected_bundle_hash
        or source_bundle_binding.get("source_bundle_hash") != current_bindings.get("source_bundle_hash")
    ):
        return None, ["legacy_source_bundle_binding_invalid"]
    source_attestation = migration.get("source_legacy_attestation")
    if source_attestation is not None:
        if not isinstance(source_attestation, Mapping):
            return None, ["legacy_source_attestation_invalid"]
        expected_attestation_id = stable_hash(
            {key: value for key, value in source_attestation.items() if key != "attestation_id"}
        )
        if (
            source_attestation.get("schema_version") != LEGACY_SOURCE_ATTESTATION_SCHEMA_VERSION
            or source_attestation.get("source_p0_p8_certification_hash")
            != current_bindings.get("source_p0_p8_certification_hash")
            or source_attestation.get("source_bundle_hash") != current_bindings.get("source_bundle_hash")
            or source_attestation.get("rollout_provenance") != LEGACY_ROLLOUT_PROVENANCE
            or source_attestation.get("operator_explicit") is not True
            or source_attestation.get("attestation_id") != expected_attestation_id
        ):
            return None, ["legacy_source_attestation_invalid"]

    certification_path = run_dir / "black-label-certification.json"
    try:
        certification = json.loads(certification_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ["black_label_certification_unreadable"]
    native_bindings = certification.get("certified_input_bindings")
    if native_bindings is None:
        if migration.get("legacy_certification_sha256") != p0p8.sha256_file(certification_path):
            return None, ["legacy_binding_migration_certification_hash_mismatch"]
    elif native_bindings != dict(current_bindings):
        return None, ["certified_input_bindings_mismatch"]
    else:
        anchor = certification.get("legacy_binding_migration")
        if not isinstance(anchor, Mapping):
            return None, ["legacy_binding_migration_certification_anchor_missing"]
        if (
            anchor.get("migration_id") != migration.get("migration_id")
            or anchor.get("sidecar") != LIGHTRAG_BINDING_MIGRATION_FILE
            or anchor.get("sidecar_sha256") != p0p8.sha256_file(path)
        ):
            return None, ["legacy_binding_migration_certification_anchor_mismatch"]

    stage_rows = migration.get("migrated_stage_ledgers")
    if not isinstance(stage_rows, list):
        return None, ["legacy_binding_migration_stage_records_invalid"]
    seen_stages: set[str] = set()
    for row in stage_rows:
        if not isinstance(row, Mapping):
            return None, ["legacy_binding_migration_stage_records_invalid"]
        stage = str(row.get("stage") or "")
        if stage not in LIGHTRAG_STAGE_LEDGER_FILES or stage in seen_stages:
            return None, ["legacy_binding_migration_stage_records_invalid"]
        if row.get("ledger_file") != LIGHTRAG_STAGE_LEDGER_FILES[stage]:
            return None, [f"legacy_binding_migration_ledger_file_invalid:{stage}"]
        ledger_path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[stage]
        if not ledger_path.is_file() or row.get("ledger_sha256") != p0p8.sha256_file(ledger_path):
            return None, [f"legacy_binding_migration_ledger_hash_mismatch:{stage}"]
        if row.get("live_recovery_verified") is not True or not isinstance(row.get("selected_identities"), list):
            return None, [f"legacy_binding_migration_stage_evidence_invalid:{stage}"]
        seen_stages.add(stage)
    if migration.get("migrated_stages") != [str(row.get("stage") or "") for row in stage_rows]:
        return None, ["legacy_binding_migration_stage_order_mismatch"]
    return migration, []


def _binding_migration_attests_stage(migration: Mapping[str, Any] | None, stage: str) -> bool:
    if not isinstance(migration, Mapping):
        return False
    return any(
        isinstance(row, Mapping) and row.get("stage") == stage
        for row in migration.get("migrated_stage_ledgers", []) or []
    )


def _current_run_input_bindings(run_dir: Path) -> dict[str, str] | None:
    try:
        certification = json.loads((run_dir / "black-label-certification.json").read_text(encoding="utf-8"))
        cards = list(_read_jsonl(run_dir / "black-label-card-manifest.jsonl"))
        lightrag_plan = list(_read_jsonl(run_dir / "lightrag-card-apply-plan.jsonl"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    native_bindings = certification.get("certified_input_bindings")
    if isinstance(native_bindings, Mapping):
        bindings = _lightrag_input_bindings(
            str(native_bindings.get("source_p0_p8_certification_hash") or ""),
            str(native_bindings.get("source_bundle_hash") or ""),
            cards,
            lightrag_plan,
        )
        return bindings if bindings == dict(native_bindings) else None
    source_run_text = str(certification.get("source_run") or "")
    if not source_run_text or source_run_text.startswith("<redacted:"):
        return None
    try:
        source_run = _repo_path(source_run_text)
        source_certification = json.loads((source_run / "p0-p8-certification.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    source_binding = certification.get("source_bundle_binding")
    source_bundle_hash = (
        str(source_binding.get("source_bundle_hash") or "")
        if isinstance(source_binding, Mapping)
        else ""
    )
    return _lightrag_input_bindings(
        stable_hash(source_certification),
        source_bundle_hash,
        cards,
        lightrag_plan,
    )


def _regenerated_lightrag_input_bindings(
    config: BlackLabelConfig,
    source: SourceBundle,
    run_dir: Path,
) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix=".legacy-binding-rebuild-", dir=run_dir.parent) as temporary_root:
        temporary_root_path = Path(temporary_root).resolve()
        rebuild_run_id = "binding-rebuild"
        rebuild_run_dir = (temporary_root_path / rebuild_run_id).resolve()
        if not rebuild_run_dir.is_relative_to(temporary_root_path):
            raise ValueError("legacy_binding_rebuild_path_escape")
        rebuild_config = replace(
            config,
            run_id=rebuild_run_id,
            artifact_root=temporary_root_path,
            source_run=source.run_dir,
            black_label_run=None,
            apply=False,
        )
        rebuild_run_dir.mkdir(parents=True, exist_ok=False)
        registry, _registry_phase = build_asset_registry(rebuild_config, source)
        visual_queue, _visual_phase = build_visual_enrichment_queue(rebuild_config, registry)
        regenerated_cards, _card_phase = build_black_label_cards(
            rebuild_config,
            source,
            registry,
            visual_queue,
        )
        regenerated_plan, _plan_phase = build_lightrag_apply_plan(
            rebuild_config,
            regenerated_cards,
        )
    return _lightrag_input_bindings(
        stable_hash(source.certification),
        str(source.binding.get("source_bundle_hash") or ""),
        regenerated_cards,
        regenerated_plan,
    )


def _verified_legacy_stage_ledger_records(
    config: BlackLabelConfig,
    run_dir: Path,
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
    *,
    client: Any | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    card_by_id = _first_by(cards, "card_id")
    prior_card_ids: set[str] = set()
    prior_source_keys: set[str] = set()
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    applied: list[tuple[LightRAGApplyStage, Path, list[dict[str, Any]]]] = []
    applied_stages: set[str] = set()

    for stage in LIGHTRAG_STAGE_ORDER:
        path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[stage]
        if not path.exists():
            continue
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            blockers.append(f"legacy_stage_ledger_unreadable:{stage}")
            continue
        if not isinstance(ledger, dict):
            blockers.append(f"legacy_stage_ledger_unreadable:{stage}")
            continue
        has_activity = ledger.get("ok") is True or ledger.get("mutation_performed") is True or _safe_int(
            ledger.get("sent_count")
        ) > 0
        if not has_activity:
            continue
        if (
            ledger.get("schema_version") != "black_label_lightrag_stage_apply.v1"
            or ledger.get("stage") != stage
            or ledger.get("stage_ledger") != path.name
        ):
            blockers.append(f"legacy_stage_ledger_contract_invalid:{stage}")
            continue
        if ledger.get("ok") is not True or list(ledger.get("blockers") or []):
            blockers.append(f"legacy_stage_not_successful:{stage}")
            continue
        missing_prerequisites = [
            prerequisite
            for prerequisite in LIGHTRAG_STAGE_PREREQUISITES[stage]
            if prerequisite not in applied_stages
        ]
        if missing_prerequisites:
            blockers.append(f"legacy_stage_prerequisite_missing:{stage}:{','.join(missing_prerequisites)}")
            continue
        if "input_bindings" in ledger:
            blockers.append(f"legacy_stage_already_declares_input_bindings:{stage}")
            continue
        expected = _select_lightrag_stage_candidates(
            stage,
            lightrag_plan,
            card_by_id,
            exclude_card_ids=prior_card_ids,
            prior_source_keys=prior_source_keys,
        )
        expected_ids = [str(candidate.get("card_id") or "") for candidate in expected]
        selected_rows = [row for row in ledger.get("selected_cards", []) or [] if isinstance(row, Mapping)]
        selected_ids = [str(row.get("card_id") or "") for row in selected_rows]
        sent_count = _safe_int(ledger.get("sent_count"))
        if (
            _safe_int(ledger.get("selected_count")) != len(selected_rows)
            or sent_count < 0
            or sent_count > len(selected_rows)
            or bool(ledger.get("mutation_performed")) != (sent_count > 0)
        ):
            blockers.append(f"legacy_stage_counts_invalid:{stage}")
            continue
        if selected_ids != expected_ids or len(selected_rows) != len(expected):
            blockers.append(f"legacy_stage_selected_identities_mismatch:{stage}")
            continue
        expected_projection = _lightrag_stage_ledger(
            config,
            run_dir,
            stage=stage,
            candidates=expected,
            batches=[],
        )["selected_cards"]
        projection_keys = {
            "card_id",
            "card_role",
            "title",
            "source_pdf_id",
            "graph_document_id",
            "file_source",
            "rights_status",
            "raw_source_text_included",
        }
        if any(
            {key: row.get(key) for key in projection_keys}
            != {key: expected_row.get(key) for key in projection_keys}
            for row, expected_row in zip(selected_rows, expected_projection, strict=True)
        ):
            blockers.append(f"legacy_stage_selected_projection_mismatch:{stage}")
            continue
        applied.append((stage, path, expected))
        applied_stages.add(stage)
        prior_card_ids.update(expected_ids)
        prior_source_keys.update(_lightrag_candidate_source_key(candidate) for candidate in expected)

    if blockers or not applied:
        return records, blockers

    own_client = client is None
    lightrag = client or LightRAGClient(base_url=config.lightrag_base_url, timeout_s=config.lightrag_timeout_s)
    try:
        preflight = _lightrag_preflight(lightrag)
        if preflight.get("blockers"):
            return records, [f"legacy_stage_live_preflight_blocked:{preflight['blockers'][0]}"]
        existing_sources, existing_error = _lightrag_existing_file_sources(lightrag, required=True)
        if existing_error:
            return records, [existing_error]
        for stage, path, expected in applied:
            expected_file_sources = {str(candidate.get("file_source") or "") for candidate in expected}
            missing_sources = sorted(expected_file_sources - existing_sources)
            if missing_sources:
                return records, [f"legacy_stage_live_source_missing:{stage}:{len(missing_sources)}"]
            recovery = _verify_lightrag_stage_recovery(
                lightrag,
                stage,
                expected,
                expected_file_sources,
                query_timeout_s=config.lightrag_timeout_s,
            )
            if recovery["blockers"]:
                return records, [f"legacy_stage_live_recovery_failed:{stage}"]
            records.append(
                {
                    "stage": stage,
                    "ledger_file": path.name,
                    "ledger_sha256": p0p8.sha256_file(path),
                    "selected_identities": [
                        {
                            "card_id": candidate.get("card_id", ""),
                            "source_key": _lightrag_candidate_source_key(candidate),
                            "file_source": candidate.get("file_source", ""),
                        }
                        for candidate in expected
                    ],
                    "live_recovery_verified": True,
                }
            )
    finally:
        if own_client:
            close = getattr(lightrag, "close", None)
            if callable(close):
                close()
    return records, []


def _normalize_lightrag_stage(stage: str) -> LightRAGApplyStage:
    if stage not in LIGHTRAG_STAGE_LEDGER_FILES:
        raise ValueError(f"unknown_lightrag_stage:{stage}")
    return stage  # type: ignore[return-value]


def _resolve_black_label_run(config: BlackLabelConfig) -> Path:
    if config.black_label_run:
        return _repo_path(config.black_label_run)
    if config.source_run and (Path(config.source_run).name.startswith("black-label") or (_repo_path(config.source_run) / "black-label-certification.json").exists()):
        return _repo_path(config.source_run)
    return _latest_black_label_run(config.artifact_root)


def _load_black_label_certification(run_dir: Path, *, require_green: bool = True) -> dict[str, Any]:
    path = run_dir / "black-label-certification.json"
    if not path.exists():
        raise FileNotFoundError(f"black_label_certification_missing:{_public_path(run_dir)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if require_green and payload.get("ok") is not True:
        raise ValueError("black_label_run_not_certified")
    return payload


def _source_certification_file(value: Any) -> Path | None:
    text = str(value or "")
    if not text or text.startswith("<redacted:"):
        return None
    source_path = _repo_path(value)
    certification_path = (
        source_path
        if source_path.name == "p0-p8-certification.json"
        else source_path / "p0-p8-certification.json"
    )
    return certification_path if certification_path.is_file() else None


def _generation_recipe(config: BlackLabelConfig) -> dict[str, Any]:
    return {
        "schema_version": BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION,
        "limit_pdfs": config.limit_pdfs,
        "max_card_chars": config.max_card_chars,
        "text_read_chars": config.text_read_chars,
        "visual_provider": config.visual_provider,
        "eval_threshold": config.eval_threshold,
    }


def _generation_config_blocker(config: BlackLabelConfig) -> str | None:
    if config.limit_pdfs is not None and (
        isinstance(config.limit_pdfs, bool)
        or not isinstance(config.limit_pdfs, int)
        or config.limit_pdfs <= 0
    ):
        return "black_label_limit_pdfs_invalid"
    if (
        isinstance(config.max_card_chars, bool)
        or not isinstance(config.max_card_chars, int)
        or config.max_card_chars <= 0
    ):
        return "black_label_max_card_chars_invalid"
    if (
        isinstance(config.text_read_chars, bool)
        or not isinstance(config.text_read_chars, int)
        or config.text_read_chars <= 0
    ):
        return "black_label_text_read_chars_invalid"
    if not isinstance(config.visual_provider, str) or not config.visual_provider:
        return "black_label_visual_provider_invalid"
    if (
        isinstance(config.eval_threshold, bool)
        or not isinstance(config.eval_threshold, (int, float))
        or not 0 < float(config.eval_threshold) <= 1
    ):
        return "black_label_eval_threshold_invalid"
    return None


def _config_with_generation_recipe(
    config: BlackLabelConfig,
    certification: Mapping[str, Any],
) -> tuple[BlackLabelConfig, list[str]]:
    recipe = certification.get("generation_recipe")
    if recipe is None:
        if certification.get("generation_recipe_hash") not in {None, ""}:
            return config, ["black_label_generation_recipe_invalid"]
        quality_bar = certification.get("quality_bar")
        eval_threshold = config.eval_threshold
        if isinstance(quality_bar, Mapping) and "target_eval_threshold" in quality_bar:
            eval_threshold = quality_bar.get("target_eval_threshold")  # type: ignore[assignment]
        candidate_config = replace(config, eval_threshold=eval_threshold)
        if _generation_config_blocker(candidate_config):
            return config, ["black_label_generation_recipe_invalid"]
        return replace(candidate_config, eval_threshold=float(candidate_config.eval_threshold)), []
    if not isinstance(recipe, Mapping):
        return config, ["black_label_generation_recipe_invalid"]
    current_keys = set(_generation_recipe(config))
    schema_version = recipe.get("schema_version")
    if schema_version == BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION:
        expected_keys = current_keys
        eval_threshold = recipe.get("eval_threshold")
    elif schema_version == LEGACY_BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION:
        expected_keys = current_keys - {"eval_threshold"}
        quality_bar = certification.get("quality_bar")
        eval_threshold = config.eval_threshold
        if isinstance(quality_bar, Mapping) and "target_eval_threshold" in quality_bar:
            eval_threshold = quality_bar.get("target_eval_threshold")
    else:
        return config, ["black_label_generation_recipe_invalid"]
    if set(recipe) != expected_keys:
        return config, ["black_label_generation_recipe_invalid"]
    limit_pdfs = recipe.get("limit_pdfs")
    max_card_chars = recipe.get("max_card_chars")
    text_read_chars = recipe.get("text_read_chars")
    visual_provider = recipe.get("visual_provider")
    if certification.get("generation_recipe_hash") != stable_hash(dict(recipe)):
        return config, ["black_label_generation_recipe_invalid"]
    candidate_config = replace(
        config,
        limit_pdfs=limit_pdfs,
        max_card_chars=max_card_chars,
        text_read_chars=text_read_chars,
        visual_provider=visual_provider,
        eval_threshold=eval_threshold,
    )
    if _generation_config_blocker(candidate_config):
        return config, ["black_label_generation_recipe_invalid"]
    return replace(candidate_config, eval_threshold=float(candidate_config.eval_threshold)), []


def _lightrag_input_bindings(
    source_certification_hash: str,
    source_bundle_hash: str,
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    return {
        "source_p0_p8_certification_hash": source_certification_hash,
        "source_bundle_hash": source_bundle_hash,
        "black_label_card_manifest_hash": stable_hash(list(cards)),
        "lightrag_apply_plan_hash": stable_hash(list(lightrag_plan)),
    }


def _source_run_is_black_label_alias(config: BlackLabelConfig, run_dir: Path) -> bool:
    if config.black_label_run is not None or config.source_run is None:
        return False
    candidate = _repo_path(config.source_run)
    return candidate.resolve() == run_dir.resolve() and (candidate / "black-label-certification.json").is_file()


def _source_bundle_by_recorded_binding(
    config: BlackLabelConfig,
    generation_config: BlackLabelConfig,
    *,
    source_certification_hash: str,
    bundle_hash: str,
) -> tuple[SourceBundle | None, list[str]]:
    if not source_certification_hash or not bundle_hash:
        return None, ["certified_source_bundle_binding_missing"]
    root = _repo_path(config.source_root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return None, ["certified_source_bundle_not_found_under_source_root"]
    candidate_paths = [
        root / "p0-p8-certification.json",
        *sorted(root.glob("*/p0-p8-certification.json")),
    ]
    matches: list[SourceBundle] = []
    seen: set[Path] = set()
    for certification_path in candidate_paths:
        try:
            resolved_path = certification_path.resolve(strict=True)
        except OSError:
            continue
        if resolved_path in seen or not resolved_path.is_relative_to(resolved_root):
            continue
        seen.add(resolved_path)
        try:
            source = load_source_bundle(
                replace(generation_config, source_run=certification_path.parent)
            )
        except Exception:  # noqa: BLE001
            continue
        candidate_certification_hash = stable_hash(source.certification)
        source_bundle_hash = str(source.binding.get("source_bundle_hash") or "")
        if secrets.compare_digest(
            candidate_certification_hash,
            source_certification_hash,
        ) and secrets.compare_digest(source_bundle_hash, bundle_hash):
            matches.append(source)
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, ["certified_source_bundle_ambiguous_under_source_root"]
    return None, ["certified_source_bundle_not_found_under_source_root"]


def _current_lightrag_input_bindings(
    config: BlackLabelConfig,
    run_dir: Path,
    *,
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[str], str]:
    certification = _load_black_label_certification(run_dir, require_green=False)
    black_label_certification_hash = stable_hash(certification)
    recorded_source_hash = str(certification.get("source_p0_p8_certification_hash") or "")
    recorded_source_binding = certification.get("source_bundle_binding")
    recorded_bundle_hash = (
        str(recorded_source_binding.get("source_bundle_hash") or "")
        if isinstance(recorded_source_binding, Mapping)
        else ""
    )
    generation_config, blockers = _config_with_generation_recipe(config, certification)
    explicit_source_value = None if _source_run_is_black_label_alias(config, run_dir) else config.source_run
    explicit_source_path = _source_certification_file(explicit_source_value)
    certified_source_path = _source_certification_file(certification.get("source_run"))
    if explicit_source_value is not None and explicit_source_path is None:
        blockers.append("explicit_source_run_unavailable")
    if explicit_source_path is not None and certified_source_path is not None:
        if explicit_source_path.resolve() != certified_source_path.resolve():
            blockers.append("explicit_source_run_mismatch")
    source_certification_path = explicit_source_path or certified_source_path
    source_bundle: SourceBundle | None = None
    if source_certification_path is not None:
        try:
            source_bundle = load_source_bundle(
                replace(generation_config, source_run=source_certification_path.parent)
            )
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"source_p0_p8_bundle_unavailable:{exc.__class__.__name__}")
            try:
                source_payload = _read_json_snapshot(source_certification_path)
            except Exception:  # noqa: BLE001
                current_source_hash = recorded_source_hash
            else:
                blockers.extend(_source_certification_contract_blockers(source_payload))
                current_source_hash = stable_hash(source_payload)
            current_bundle_hash = recorded_bundle_hash
    else:
        current_source_hash = recorded_source_hash
        current_bundle_hash = recorded_bundle_hash
        if explicit_source_value is None:
            source_bundle, lookup_blockers = _source_bundle_by_recorded_binding(
                config,
                generation_config,
                source_certification_hash=recorded_source_hash,
                bundle_hash=recorded_bundle_hash,
            )
            blockers.extend(lookup_blockers)
        else:
            blockers.append("source_p0_p8_certification_unavailable")
    if source_bundle is not None:
        current_source_hash = stable_hash(source_bundle.certification)
        current_bundle_hash = str(source_bundle.binding.get("source_bundle_hash") or "")
        (
            source_schema,
            source_provenance,
            source_authorization,
            source_attestation,
        ) = _source_rollout_authorization(
            source_bundle.certification,
            source_bundle_binding=source_bundle.binding,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        )
        blockers.extend(_governed_p1_blockers(source_authorization))
        expected_source_fields = {
            "source_rollout_schema_version": source_schema,
            "source_rollout_provenance": source_provenance,
            "source_governed_p1_authorization": source_authorization,
            "source_legacy_attestation": source_attestation,
            "source_bundle_binding": source_bundle.binding,
        }
        for key, expected in expected_source_fields.items():
            if certification.get(key) != expected:
                blockers.append(f"black_label_source_authorization_mismatch:{key}")
    bindings = _lightrag_input_bindings(current_source_hash, current_bundle_hash, cards, lightrag_plan)
    if source_bundle is not None:
        try:
            canonical_bindings = _regenerated_lightrag_input_bindings(generation_config, source_bundle, run_dir)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"source_p0_p8_canonical_regeneration_error:{exc.__class__.__name__}")
        else:
            for key, expected in canonical_bindings.items():
                if bindings.get(key) != expected:
                    blockers.append(f"black_label_source_canonical_mismatch:{key}")
    certified_bindings = certification.get("certified_input_bindings")
    if not isinstance(certified_bindings, Mapping):
        migration, migration_blockers = _validated_binding_migration(run_dir, bindings)
        if migration is None:
            blockers.extend(migration_blockers)
    elif dict(certified_bindings) != bindings:
        blockers.append("certified_input_bindings_mismatch")
    if not recorded_source_hash:
        blockers.append("source_p0_p8_certification_hash_missing")
    elif current_source_hash != recorded_source_hash:
        blockers.append("source_p0_p8_certification_hash_mismatch")
    if not recorded_bundle_hash:
        blockers.append("source_bundle_hash_missing")
    elif current_bundle_hash != recorded_bundle_hash:
        blockers.append("source_bundle_hash_mismatch")
    for key, value in bindings.items():
        if not value:
            blockers.append(f"lightrag_input_binding_missing:{key}")
    try:
        current_certification = _load_black_label_certification(run_dir, require_green=False)
    except Exception:  # noqa: BLE001
        blockers.append("black_label_certification_changed_during_validation")
    else:
        if not secrets.compare_digest(
            black_label_certification_hash,
            stable_hash(current_certification),
        ):
            blockers.append("black_label_certification_changed_during_validation")
    return bindings, blockers, black_label_certification_hash


def _lightrag_stage_replay_blocker(ledger_path: Path, stage: LightRAGApplyStage) -> str | None:
    if not ledger_path.exists():
        return None
    try:
        existing = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return f"existing_stage_ledger_unreadable:{stage}"
    if not isinstance(existing, Mapping):
        return f"existing_stage_ledger_unreadable:{stage}"
    if existing.get("ok") is True or existing.get("mutation_performed") is True or _safe_int(existing.get("sent_count")) > 0:
        return f"existing_stage_ledger_blocks_replay:{stage}"
    return None


def _lightrag_fencing_capability_blocker(client: Any) -> str | None:
    capability_reader = getattr(client, "mutation_fencing_capability", None)
    insert_once = getattr(client, "insert_texts_once", None)
    if not callable(capability_reader) or not callable(insert_once):
        return "lightrag_service_enforced_fencing_unavailable"
    try:
        capability = capability_reader()
    except Exception:  # noqa: BLE001
        return "lightrag_service_enforced_fencing_unavailable"
    required_bindings = {
        "black_label_certification_hash",
        "stage",
        "input_bindings_hash",
        "batch_id",
        "ordered_payload_hashes",
        "file_sources",
        "expires_at_epoch",
        "nonce",
    }
    if (
        not isinstance(capability, Mapping)
        or capability.get("available") is not True
        or capability.get("service_enforced") is not True
        or capability.get("single_use") is not True
        or set(capability.get("binding_fields") or []) != required_bindings
    ):
        return "lightrag_service_enforced_fencing_unavailable"
    return None


def _verify_black_label_certification_snapshot(
    run_dir: Path,
    input_bindings: Mapping[str, str],
    expected_black_label_certification_hash: str,
) -> None:
    certification = _load_black_label_certification(run_dir, require_green=False)
    if (
        certification.get("ok") is not True
        or certification.get("certified_input_bindings") != dict(input_bindings)
        or not secrets.compare_digest(
            stable_hash(certification),
            expected_black_label_certification_hash,
        )
    ):
        raise ValueError("black_label_certification_changed_before_fence")


def _lightrag_stage_claim_payload(
    run_dir: Path,
    stage: LightRAGApplyStage,
    input_bindings: Mapping[str, str],
    black_label_certification_hash: str,
    candidates: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _verify_black_label_certification_snapshot(
        run_dir,
        input_bindings,
        black_label_certification_hash,
    )
    payload = {
        "schema_version": LIGHTRAG_STAGE_CLAIM_SCHEMA_VERSION,
        "black_label_certification_hash": black_label_certification_hash,
        "stage": stage,
        "input_bindings_hash": stable_hash(dict(input_bindings)),
        "selected_card_ids": [str(candidate.get("card_id") or "") for candidate in candidates],
        "batch_ids": [str(batch.get("batch_id") or "") for batch in batches],
    }
    payload["claim_id"] = stable_hash(payload)
    return payload


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_public_payload(dict(payload)), handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _lightrag_fence_request(
    run_dir: Path,
    stage: LightRAGApplyStage,
    input_bindings: Mapping[str, str],
    black_label_certification_hash: str,
    batch: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    timeout_s: float,
) -> dict[str, Any]:
    _verify_black_label_certification_snapshot(
        run_dir,
        input_bindings,
        black_label_certification_hash,
    )
    operation_identity = {
        "schema_version": LIGHTRAG_FENCE_SCHEMA_VERSION,
        "stage": stage,
        "input_bindings_hash": stable_hash(dict(input_bindings)),
        "batch_id": str(batch.get("batch_id") or ""),
        "ordered_payload_hashes": [stable_hash(str(candidate.get("payload") or "")) for candidate in candidates],
        "file_sources": [str(candidate.get("file_source") or "") for candidate in candidates],
    }
    operation_hash = stable_hash(operation_identity)
    immutable_binding = {
        **operation_identity,
        "black_label_certification_hash": black_label_certification_hash,
        "nonce": operation_hash[:32],
    }
    request = {
        **immutable_binding,
        "expires_at_epoch": int(time.time()) + max(60, int(timeout_s)),
    }
    request["fence_token"] = operation_hash
    request["binding_hash"] = stable_hash(request)
    return request


def _lightrag_fence_receipt_valid(
    response: Mapping[str, Any],
    request: Mapping[str, Any],
) -> bool:
    receipt = response.get("fence_receipt")
    return bool(
        isinstance(receipt, Mapping)
        and receipt.get("schema_version") == LIGHTRAG_FENCE_RECEIPT_SCHEMA_VERSION
        and receipt.get("accepted") is True
        and receipt.get("single_use_enforced") is True
        and receipt.get("fence_token") == request.get("fence_token")
        and receipt.get("binding_hash") == request.get("binding_hash")
    )


def _normalized_governed_p1_authorization(
    *,
    schema: str,
    provenance: str,
    authorization: Any,
) -> dict[str, bool]:
    values = authorization if isinstance(authorization, Mapping) else {}
    valid_legacy = not schema and provenance == LEGACY_ROLLOUT_PROVENANCE
    valid_governed = schema == GOVERNED_ROLLOUT_SCHEMA_VERSION and provenance == GOVERNED_ROLLOUT_PROVENANCE
    provenance_valid = valid_legacy or valid_governed
    return {
        "provenance_valid": provenance_valid,
        "required": True,
        "authorized": provenance_valid and values.get("authorized") is True,
        "separately_reviewed": provenance_valid and values.get("separately_reviewed") is True,
        "controller_ready": provenance_valid and values.get("controller_ready") is True,
    }


def _legacy_source_hash_attested(expected_hash: str, supplied_hash: str) -> bool:
    return bool(expected_hash and supplied_hash) and secrets.compare_digest(expected_hash, supplied_hash)


def _legacy_source_attestation(
    certification: Mapping[str, Any],
    source_bundle_binding: Mapping[str, Any],
    supplied_certification_hash: str,
    supplied_bundle_hash: str,
) -> dict[str, Any] | None:
    if _source_certification_contract_blockers(certification):
        return None
    schema = str(certification.get("rollout_schema_version") or "")
    provenance = str(certification.get("rollout_provenance") or "")
    certification_hash = stable_hash(certification)
    if schema or provenance not in {"", LEGACY_ROLLOUT_PROVENANCE}:
        return None
    source_bundle_hash = str(source_bundle_binding.get("source_bundle_hash") or "")
    if not _legacy_source_hash_attested(certification_hash, supplied_certification_hash):
        return None
    if not _legacy_source_hash_attested(source_bundle_hash, supplied_bundle_hash):
        return None
    payload = {
        "schema_version": LEGACY_SOURCE_ATTESTATION_SCHEMA_VERSION,
        "source_p0_p8_certification_hash": certification_hash,
        "source_bundle_hash": source_bundle_hash,
        "rollout_provenance": LEGACY_ROLLOUT_PROVENANCE,
        "operator_explicit": True,
    }
    payload["attestation_id"] = stable_hash(payload)
    return payload


def _source_rollout_authorization(
    certification: Mapping[str, Any],
    *,
    source_bundle_binding: Mapping[str, Any] | None = None,
    legacy_source_certification_hash: str = "",
    legacy_source_bundle_hash: str = "",
) -> tuple[str, str, dict[str, bool], dict[str, Any] | None]:
    schema = str(certification.get("rollout_schema_version") or "")
    provenance = str(certification.get("rollout_provenance") or "")
    authorization: Any = certification.get("governed_p1_authorization")
    attestation = _legacy_source_attestation(
        certification,
        source_bundle_binding or {},
        legacy_source_certification_hash,
        legacy_source_bundle_hash,
    )
    if attestation is not None:
        provenance = LEGACY_ROLLOUT_PROVENANCE
        authorization = {
            "authorized": True,
            "separately_reviewed": True,
            "controller_ready": True,
        }
    normalized = _normalized_governed_p1_authorization(
        schema=schema,
        provenance=provenance,
        authorization=authorization,
    )
    return schema, provenance, normalized, attestation


def _governed_p1_controller_authorized(authorization: Mapping[str, Any]) -> bool:
    return authorization.get("provenance_valid") is True and all(
        authorization.get(key) is True
        for key in ("authorized", "separately_reviewed", "controller_ready")
    )


def _governed_p1_blockers(authorization: Mapping[str, Any]) -> list[str]:
    if authorization.get("provenance_valid") is not True:
        return [GOVERNED_P1_PROVENANCE_BLOCKER]
    if not _governed_p1_controller_authorized(authorization):
        return [GOVERNED_P1_AUTHORIZATION_BLOCKER]
    return []


def _black_label_governed_p1_authorization(
    certification: Mapping[str, Any],
    *,
    legacy_source_certification_hash: str = "",
    legacy_source_bundle_hash: str = "",
) -> dict[str, bool]:
    source_schema = str(certification.get("source_rollout_schema_version") or "")
    direct_schema = str(certification.get("rollout_schema_version") or "")
    source_provenance = str(certification.get("source_rollout_provenance") or "")
    direct_provenance = str(certification.get("rollout_provenance") or "")
    source_declared = any(
        key in certification
        for key in (
            "source_rollout_schema_version",
            "source_rollout_provenance",
            "source_governed_p1_authorization",
        )
    )
    use_source = source_schema == GOVERNED_ROLLOUT_SCHEMA_VERSION or (
        source_declared and direct_schema != GOVERNED_ROLLOUT_SCHEMA_VERSION
    )
    schema = source_schema if use_source else direct_schema
    provenance = source_provenance if use_source else direct_provenance
    authorization_key = "source_governed_p1_authorization" if use_source else "governed_p1_authorization"
    authorization: Any = certification.get(authorization_key)
    if provenance == LEGACY_ROLLOUT_PROVENANCE:
        attestation = certification.get("source_legacy_attestation")
        attested_bundle_hash = (
            str(attestation.get("source_bundle_hash") or "")
            if isinstance(attestation, Mapping)
            else ""
        )
        if not (
            _legacy_source_hash_attested(
                str(certification.get("source_p0_p8_certification_hash") or ""),
                legacy_source_certification_hash,
            )
            and _legacy_source_hash_attested(attested_bundle_hash, legacy_source_bundle_hash)
        ):
            authorization = {}
    return _normalized_governed_p1_authorization(
        schema=schema,
        provenance=provenance,
        authorization=authorization,
    )


def _select_lightrag_stage_candidates(
    stage: LightRAGApplyStage,
    plan_rows: Sequence[Mapping[str, Any]],
    card_by_id: Mapping[str, Mapping[str, Any]],
    *,
    exclude_card_ids: set[str] | None = None,
    prior_source_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows_by_card = _first_by(plan_rows, "card_id")
    excluded = exclude_card_ids or set()
    eligible: list[dict[str, Any]] = []
    for card_id, card in card_by_id.items():
        if card_id in excluded:
            continue
        plan = rows_by_card.get(card_id, {})
        if plan.get("apply_status") != "planned" or card.get("rights_status") != "clear":
            continue
        if card.get("raw_source_text_included"):
            continue
        candidate = {
            "card_id": card_id,
            "card": card,
            "plan": plan,
            "source_pdf_id": str(card.get("source_pdf_id") or ""),
            "source_hash": _candidate_source_hash(card, plan),
            "topic": _topic_for_card(card),
            "file_source": f"black-label-docling/{stage}/{card_id}.md",
        }
        candidate["payload"] = _lightrag_stage_payload(candidate)
        candidate["estimated_chars"] = len(str(candidate["payload"]))
        eligible.append(candidate)

    eligible.sort(key=_lightrag_candidate_sort_key)
    limit = LIGHTRAG_STAGE_LIMITS[stage]
    if stage == "one_document_sample":
        return eligible[:1]
    if stage == "five_document_sample":
        prior_sources = prior_source_keys or set()
        remaining = max(0, int(limit or 5) - len(prior_sources))
        new_source_candidates = [
            candidate for candidate in eligible if _lightrag_candidate_source_key(candidate) not in prior_sources
        ]
        return _take_distinct_sources(new_source_candidates, remaining)
    if stage == "topic_cluster_sample":
        return _take_topic_cluster(eligible, int(limit or 100))
    return eligible


def _candidate_source_hash(card: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    for collection in (card.get("source_hashes"), plan.get("source_hashes")):
        if isinstance(collection, list):
            for value in collection:
                text = str(value or "")
                if text:
                    return text
    return ""


def _lightrag_candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[int, str, str, str]:
    card = candidate.get("card") if isinstance(candidate.get("card"), Mapping) else {}
    return (
        LIGHTRAG_ROLE_PRIORITY.get(str(card.get("card_role") or ""), 99),
        str(candidate.get("source_pdf_id") or ""),
        str(candidate.get("source_hash") or ""),
        str(candidate.get("card_id") or ""),
    )


def _take_distinct_sources(candidates: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    selected: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for candidate in candidates:
        source_key = _lightrag_candidate_source_key(candidate)
        if source_key in seen_sources:
            continue
        selected.append(candidate)
        seen_sources.add(source_key)
        if len(selected) >= limit:
            return selected
    return selected


def _lightrag_candidate_source_key(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("source_hash") or candidate.get("source_pdf_id") or candidate.get("card_id") or "")


def _take_topic_cluster(candidates: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not candidates:
        return []
    by_topic = _group_by(candidates, "topic")
    topic = sorted(by_topic, key=lambda key: (-len(by_topic[key]), key))[0]
    return sorted((dict(candidate) for candidate in by_topic[topic]), key=_lightrag_candidate_sort_key)[:limit]


def _lightrag_stage_batches(candidates: Sequence[Mapping[str, Any]], config: BlackLabelConfig) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []
    current_chars = 0
    max_cards = max(1, int(config.lightrag_batch_max_cards))
    max_chars = max(1, int(config.lightrag_batch_max_chars))
    for candidate in candidates:
        estimated_chars = int(candidate.get("estimated_chars") or 0)
        if current and (len(current) >= max_cards or current_chars + estimated_chars > max_chars):
            batches.append(_lightrag_batch_row(len(batches) + 1, current))
            current = []
            current_chars = 0
        current.append(candidate)
        current_chars += estimated_chars
    if current:
        batches.append(_lightrag_batch_row(len(batches) + 1, current))
    return batches


def _lightrag_batch_row(index: int, candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "batch_id": f"batch_{index:04d}",
        "card_ids": [candidate.get("card_id") for candidate in candidates],
        "file_sources": [candidate.get("file_source") for candidate in candidates],
        "estimated_chars": sum(int(candidate.get("estimated_chars") or 0) for candidate in candidates),
    }


def _lightrag_stage_ledger(
    config: BlackLabelConfig,
    run_dir: Path,
    *,
    stage: LightRAGApplyStage,
    candidates: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
    ok: bool = False,
    blockers: Sequence[str] = (),
    input_bindings: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    selected_cards = []
    for candidate in candidates:
        card = candidate.get("card") if isinstance(candidate.get("card"), Mapping) else {}
        plan = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
        selected_cards.append(
            {
                "card_id": card.get("card_id", candidate.get("card_id", "")),
                "card_role": card.get("card_role", ""),
                "title": card.get("title", ""),
                "source_pdf_id": card.get("source_pdf_id", ""),
                "source_hash": candidate.get("source_hash", ""),
                "graph_document_id": plan.get("graph_document_id", ""),
                "file_source": candidate.get("file_source", ""),
                "rights_status": card.get("rights_status", ""),
                "raw_source_text_included": bool(card.get("raw_source_text_included")),
            }
        )
    return {
        "schema_version": "black_label_lightrag_stage_apply.v1",
        "run_id": config.run_id,
        "black_label_run": _public_path(run_dir),
        "base_url": config.lightrag_base_url,
        "stage": stage,
        "stage_ledger": LIGHTRAG_STAGE_LEDGER_FILES[stage],
        "input_bindings": dict(input_bindings or {}),
        "ok": ok,
        "blockers": list(blockers),
        "mutation_performed": False,
        "mutation_attempted": False,
        "mutation_state": "not_attempted",
        "selected_count": len(selected_cards),
        "sent_count": 0,
        "skipped_sources": [],
        "selected_cards": selected_cards,
        "sample": selected_cards[0] if selected_cards else {},
        "batch_manifest": list(batches),
        "insert_response": None,
        "insert_responses": [],
        "query_recovery": [],
    }


def _lightrag_stage_payload(candidate: Mapping[str, Any]) -> str:
    card = candidate.get("card") if isinstance(candidate.get("card"), Mapping) else {}
    plan = candidate.get("plan") if isinstance(candidate.get("plan"), Mapping) else {}
    package_refs = ", ".join(str(item) for item in card.get("package_ids", []) if item)
    source_hashes = ", ".join(str(item) for item in card.get("source_hashes", []) if item)
    return "\n".join(
        [
            "# Black Label Docling Card",
            "",
            f"Card ID: {card.get('card_id')}",
            f"Graph document ID: {plan.get('graph_document_id')}",
            f"Role: {card.get('card_role')}",
            f"Title: {card.get('title')}",
            f"Source PDF ID: {card.get('source_pdf_id')}",
            f"Package refs: {package_refs}",
            f"Source hashes: {source_hashes}",
            f"Rights status: {card.get('rights_status')}",
            f"Model profile: {card.get('model_profile')}",
            "",
            "## Curated Payload",
            "",
            str(card.get("payload_outline") or "Rights-safe curated Black Label Docling source card."),
            "",
            "This staged card is a rights-safe package reference for the post-Docling Black Label pipeline. "
            "It intentionally contains provenance, role, package, and craft-planning metadata only, not raw book text or binary media.",
        ]
    )


def _lightrag_recovery_candidates(
    candidates: Sequence[Mapping[str, Any]],
    inserted_candidates: Sequence[Mapping[str, Any]],
    duplicate_sources: set[str],
) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    inserted_ids = {str(candidate.get("card_id") or "") for candidate in inserted_candidates}
    recovery_candidates: list[Mapping[str, Any]] = []
    for candidate in list(inserted_candidates) + list(candidates):
        card_id = str(candidate.get("card_id") or "")
        if not card_id or card_id in seen:
            continue
        is_inserted = card_id in inserted_ids
        is_duplicate = str(candidate.get("file_source") or "") in duplicate_sources
        if not is_inserted and not is_duplicate:
            continue
        seen.add(card_id)
        recovery_candidates.append(candidate)
    return recovery_candidates


def _lightrag_existing_file_sources(client: Any, *, required: bool = False) -> tuple[set[str], str | None]:
    if not hasattr(client, "paginated_documents"):
        if required:
            return set(), "lightrag_document_index_unavailable"
        return set(), None
    try:
        return set(fetch_existing_document_index(client).file_sources), None
    except Exception as exc:  # noqa: BLE001
        if required:
            return set(), f"lightrag_document_index_error:{public_error(exc)[:180]}"
        return set(), None


def _lightrag_stage_prerequisite_blockers(
    config: BlackLabelConfig,
    run_dir: Path,
    stage: LightRAGApplyStage,
    *,
    input_bindings: Mapping[str, str],
    input_binding_blockers: Sequence[str] = (),
) -> list[str]:
    blockers = list(input_binding_blockers)
    migration, _migration_blockers = _validated_binding_migration(run_dir, input_bindings)
    certification = _load_black_label_certification(run_dir, require_green=False)
    if certification.get("ok") is not True:
        blockers.append("black_label_certification_not_green")
    authorization = _black_label_governed_p1_authorization(
        certification,
        legacy_source_certification_hash=config.legacy_source_certification_hash,
        legacy_source_bundle_hash=config.legacy_source_bundle_hash,
    )
    blockers.extend(_governed_p1_blockers(authorization))
    if stage == "full_corpus_after_certification":
        quality_bar = certification.get("quality_bar") if isinstance(certification.get("quality_bar"), Mapping) else {}
        rollout_gates = certification.get("rollout_gates") if isinstance(certification.get("rollout_gates"), Mapping) else {}
        gate_state = str(rollout_gates.get("gate_6_full_84_pdf_apply") or "")
        if quality_bar.get("full_corpus_apply_allowed") is not True:
            blockers.append("full_corpus_apply_not_certified")
        if gate_state not in {"ready_for_operator_gate", "pass"}:
            blockers.append(f"full_corpus_gate_not_ready:{gate_state or 'missing'}")
    for prerequisite in LIGHTRAG_STAGE_PREREQUISITES[stage]:
        ledger_path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[prerequisite]
        if not ledger_path.exists():
            blockers.append(f"missing_prerequisite_ledger:{prerequisite}")
            continue
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blockers.append(f"invalid_prerequisite_ledger:{prerequisite}")
            continue
        ledger_bindings = ledger.get("input_bindings")
        if (
            not isinstance(ledger_bindings, Mapping)
            or dict(ledger_bindings) != dict(input_bindings)
        ) and not _binding_migration_attests_stage(migration, prerequisite):
            blockers.append(f"prerequisite_input_bindings_mismatch:{prerequisite}")
        if ledger.get("ok") is not True:
            blockers.append(f"blocked_prerequisite_ledger:{prerequisite}")
    return blockers


def _lightrag_prior_stage_card_ids(run_dir: Path, stage: LightRAGApplyStage) -> set[str]:
    prior_ids: set[str] = set()
    for prior_stage in LIGHTRAG_STAGE_ORDER:
        if prior_stage == stage:
            break
        path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[prior_stage]
        if not path.exists():
            continue
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for card in ledger.get("selected_cards", []) or []:
            if isinstance(card, Mapping) and card.get("card_id"):
                prior_ids.add(str(card.get("card_id")))
        sample = ledger.get("sample") if isinstance(ledger.get("sample"), Mapping) else {}
        if sample.get("card_id"):
            prior_ids.add(str(sample.get("card_id")))
    return prior_ids


def _lightrag_prior_stage_source_keys(run_dir: Path, stage: LightRAGApplyStage) -> set[str]:
    prior_sources: set[str] = set()
    bindings = _current_run_input_bindings(run_dir)
    migration = _validated_binding_migration(run_dir, bindings)[0] if bindings is not None else None
    migrated_source_keys = {
        (str(row.get("stage") or ""), str(identity.get("card_id") or "")): str(identity.get("source_key") or "")
        for row in (migration or {}).get("migrated_stage_ledgers", []) or []
        if isinstance(row, Mapping)
        for identity in row.get("selected_identities", []) or []
        if isinstance(identity, Mapping)
    }
    for prior_stage in LIGHTRAG_STAGE_ORDER:
        if prior_stage == stage:
            break
        path = run_dir / LIGHTRAG_STAGE_LEDGER_FILES[prior_stage]
        if not path.exists():
            continue
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for card in ledger.get("selected_cards", []) or []:
            if not isinstance(card, Mapping):
                continue
            card_id = str(card.get("card_id") or "")
            source_key = str(
                card.get("source_hash")
                or migrated_source_keys.get((prior_stage, card_id))
                or card.get("source_pdf_id")
                or card_id
            )
            if source_key:
                prior_sources.add(source_key)
    return prior_sources


def _load_lightrag_stage_ledgers(
    run_dir: Path,
    *,
    input_bindings: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    ledgers: dict[str, dict[str, Any]] = {}
    migration = _validated_binding_migration(run_dir, input_bindings)[0] if input_bindings is not None else None
    for stage, filename in LIGHTRAG_STAGE_LEDGER_FILES.items():
        path = run_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"ok": False, "blockers": ["invalid_stage_ledger_json"], "stage": stage}
        if isinstance(payload, dict):
            if (
                input_bindings is not None
                and payload.get("input_bindings") != dict(input_bindings)
                and not _binding_migration_attests_stage(migration, stage)
            ):
                payload = {
                    **payload,
                    "ok": False,
                    "blockers": [*payload.get("blockers", []), "stage_input_bindings_mismatch"],
                }
            ledgers[stage] = _public_payload(payload)
    return ledgers


def _rollout_gates(
    *,
    registry: Sequence[Mapping[str, Any]],
    leaks: Sequence[str],
    stage_ledgers: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    one = _stage_gate_state(stage_ledgers, "one_document_sample")
    five = _stage_gate_state(stage_ledgers, "five_document_sample", prerequisite_state=one)
    topic = _stage_gate_state(stage_ledgers, "topic_cluster_sample", prerequisite_state=five)
    full_prereq = topic
    full = _stage_gate_state(stage_ledgers, "full_corpus_after_certification", prerequisite_state=full_prereq)
    if full == "pending_live_operator_gate" and full_prereq == "pass":
        full = "ready_for_operator_gate"
    return {
        "gate_0_dry_run_registry": "pass" if registry and not leaks else "blocked",
        "gate_1_lightrag_one_card_sample": one,
        "gate_2_lightrag_five_source_sample": five,
        "gate_3_lightrag_topic_cluster": topic,
        "gate_4_qwen_priority_visuals": "pending_live_operator_gate",
        "gate_5_kh_cag_handoff": "pending_reviewed_apply_client",
        "gate_6_full_84_pdf_apply": full,
    }


def _stage_gate_state(stage_ledgers: Mapping[str, Mapping[str, Any]], stage: str, prerequisite_state: str = "pass") -> str:
    ledger = stage_ledgers.get(stage)
    if prerequisite_state != "pass":
        return "blocked_until_prior_gates_pass"
    if not ledger:
        return "pending_live_operator_gate"
    return "pass" if ledger.get("ok") is True else "blocked"


def _verify_lightrag_stage_recovery(
    client: Any,
    stage: LightRAGApplyStage,
    candidates: Sequence[Mapping[str, Any]],
    duplicate_sources: set[str],
    *,
    query_timeout_s: float,
) -> dict[str, Any]:
    query_recovery: list[dict[str, Any]] = []
    blockers: list[str] = []
    recovery_limit = LIGHTRAG_QUERY_RECOVERY_LIMITS.get(stage, FULL_CORPUS_QUERY_RECOVERY_LIMIT)
    verify_candidates = list(candidates)[:recovery_limit]
    for candidate in verify_candidates:
        card = candidate.get("card") if isinstance(candidate.get("card"), Mapping) else {}
        file_source = str(candidate.get("file_source") or "")
        query_text = f"Recover Black Label Docling card {card.get('card_id')} for {card.get('title')}."
        query_attempt = 0
        try:
            if isinstance(client, LightRAGClient):
                query_response = _query_lightrag_with_wall_guard(
                    base_url=client.base_url,
                    timeout_s=query_timeout_s,
                    query_text=query_text,
                )
            else:
                query_response = client.query(
                    query_text,
                    mode="mix",
                    include_references=True,
                    include_chunk_content=True,
                    only_need_context=True,
                )
        except Exception as exc:  # noqa: BLE001 - ledger must capture public-safe query failure details.
            error = public_error(exc)
            query_recovery.append(
                _public_payload(
                    {
                        "card_id": card.get("card_id"),
                        "file_source": file_source,
                        "query_hash": stable_hash(query_text),
                        "recovered": False,
                        "source_already_present": file_source in duplicate_sources,
                        "error": error,
                    }
                )
            )
            blockers.append(f"lightrag_query_recovery_error:{card.get('card_id')}:{error}")
            continue
        recovery_match = _query_recovery_match(query_response, card, file_source)
        recovered = bool(recovery_match["recovered"])
        query_recovery.append(
            _public_payload(
                {
                    "card_id": card.get("card_id"),
                    "file_source": file_source,
                    "query_hash": stable_hash(query_text),
                    "recovered": recovered,
                    "source_already_present": file_source in duplicate_sources,
                    "attempt": query_attempt,
                    "reference_count": recovery_match["reference_count"],
                    "matched": recovery_match["matched"],
                }
            )
        )
        if not recovered:
            blockers.append(f"lightrag_query_recovery_failed:{card.get('card_id')}")
    return {"query_recovery": query_recovery, "blockers": blockers}


def _query_lightrag_with_wall_guard(*, base_url: str, timeout_s: float, query_text: str) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="black_label_lightrag_query_") as tmpdir:
        output_path = Path(tmpdir) / "result.json"
        process = ctx.Process(target=_query_lightrag_worker, args=(str(output_path), base_url, timeout_s, query_text))
        process.start()
        wall_timeout = max(1.0, timeout_s + 5.0)
        process.join(wall_timeout)
        if process.is_alive():
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            raise TimeoutError(f"LightRAG query exceeded {wall_timeout:.1f}s isolated timeout")
        if not output_path.exists():
            raise RuntimeError(f"LightRAG query process exited without result rc={process.exitcode}")
        result = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(str(result.get("error") if isinstance(result, dict) else "unknown query failure")[:500])
    payload = result.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("LightRAG query process returned malformed payload")
    return payload


def _query_lightrag_worker(output_path: str, base_url: str, timeout_s: float, query_text: str) -> None:
    client = LightRAGClient(base_url=base_url, timeout_s=timeout_s)
    try:
        payload = client.query(
            query_text,
            mode="mix",
            include_references=True,
            include_chunk_content=True,
            only_need_context=True,
        )
        Path(output_path).write_text(json.dumps({"ok": True, "payload": payload}), encoding="utf-8")
    except BaseException as exc:  # subprocess boundary: public-safe errors only
        Path(output_path).write_text(
            json.dumps({"ok": False, "error": public_error(exc), "error_type": exc.__class__.__name__}),
            encoding="utf-8",
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _lightrag_preflight(client: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "health": _public_payload(client.health()),
        "status_counts": _public_payload(client.status_counts()),
        "pipeline_status": _public_payload(client.pipeline_status()),
        "blockers": [],
    }
    blockers: list[str] = []
    pipeline = payload.get("pipeline_status") if isinstance(payload.get("pipeline_status"), Mapping) else {}
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), Mapping) else {}
    if pipeline.get("busy"):
        blockers.append("pipeline_busy")
    if pipeline.get("request_pending"):
        blockers.append("pipeline_request_pending")
    active = _active_count(counts)
    failed = _failed_count(counts)
    if active:
        blockers.append(f"active_documents_present:{active}")
    if failed:
        blockers.append(f"failed_documents_present:{failed}")
    payload["blockers"] = blockers
    return payload


def _lightrag_postflight_blockers(
    preflight: Mapping[str, Any],
    settled: Mapping[str, Any],
    final_counts: Mapping[str, Any],
    *,
    expected_increment: int,
) -> list[str]:
    blockers: list[str] = []
    if settled.get("timed_out") or settled.get("settled") is False:
        blockers.append("pipeline_settle_timeout")
    if settled.get("busy") or settled.get("request_pending"):
        blockers.append("pipeline_not_idle")
    active = _active_count(final_counts)
    if active:
        blockers.append(f"documents_still_active:{active}")
    preflight_failed = _failed_count(preflight.get("status_counts", {}))
    final_failed = _failed_count(final_counts)
    if final_failed > preflight_failed:
        blockers.append(f"new_failed_documents:{final_failed - preflight_failed}")
    expected_total = _all_count(preflight.get("status_counts", {})) + expected_increment
    final_total = _all_count(final_counts)
    if final_total < expected_total:
        blockers.append(f"document_count_not_incremented:{final_total}<{expected_total}")
    return blockers


def _compact_query_response(response: Mapping[str, Any]) -> dict[str, Any]:
    references = response.get("references") if isinstance(response.get("references"), list) else []
    return {
        "reference_count": len(references),
        "references": [
            {
                "file_path": ref.get("file_path", ""),
            }
            for ref in references[:5]
            if isinstance(ref, Mapping)
        ],
    }


def _query_recovered_sample(response: Mapping[str, Any], card: Mapping[str, Any], file_source: str) -> bool:
    return bool(_query_recovery_match(response, card, file_source)["recovered"])


def _query_recovery_match(response: Mapping[str, Any], card: Mapping[str, Any], file_source: str) -> dict[str, Any]:
    haystack = json.dumps(response, sort_keys=True, ensure_ascii=True).lower()
    card_id = str(card.get("card_id") or "").lower()
    source_hashes = [str(item).lower() for item in card.get("source_hashes", []) if item]
    matched = {
        "card_id": bool(card_id and card_id in haystack),
        "file_source": bool(file_source and file_source.lower() in haystack),
        "source_hash": any(source_hash in haystack for source_hash in source_hashes),
    }
    references = response.get("references") if isinstance(response.get("references"), list) else []
    return {
        "recovered": any(matched.values()),
        "reference_count": len(references),
        "matched": matched,
    }


def _latest_black_label_run(artifact_root: Path) -> Path:
    root = _repo_path(artifact_root)
    candidates = sorted(root.glob("*/black-label-certification.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            certification = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if certification.get("ok") is True:
            return path.parent
    raise FileNotFoundError(f"no_certified_black_label_run_under:{_public_path(root)}")


def build_asset_registry(config: BlackLabelConfig, source: SourceBundle) -> tuple[list[dict[str, Any]], PhaseResult]:
    crosswalk_by_key = _first_by(source.crosswalk, "package_key")
    cag_by_package = _cag_by_package(source.cag_candidates)
    limited_sources = _limited_source_hashes(source.normalized, config.limit_pdfs)
    rows: list[dict[str, Any]] = []
    for record in source.normalized:
        if limited_sources is not None and record.get("source_sha256") and record.get("source_sha256") not in limited_sources:
            continue
        row = _asset_registry_row(record, crosswalk_by_key.get(str(record.get("package_key") or ""), {}), cag_by_package)
        rows.append(row)

    blockers: list[str] = []
    if not rows:
        blockers.append("no_asset_registry_rows")
    image_rows = [row for row in rows if row.get("artifact_kind") == "image"]
    if any(not row.get("image_package_id") for row in image_rows):
        blockers.append("image_rows_missing_image_package_id")
    if find_public_leaks(rows):
        blockers.append("asset_registry_public_leak")

    _write_jsonl(config.run_dir / "black-label-asset-registry.jsonl", rows)
    _write_jsonl(config.run_dir / "docling-pdf-page-image-crosswalk.jsonl", rows)
    return rows, PhaseResult(
        phase="U1",
        name="asset-registry",
        status="complete" if not blockers else "blocked",
        output_paths=["black-label-asset-registry.jsonl", "docling-pdf-page-image-crosswalk.jsonl"],
        counts={
            "assets": len(rows),
            "pdfs": sum(1 for row in rows if row.get("artifact_kind") == "pdf"),
            "images": len(image_rows),
            "tables": sum(1 for row in rows if row.get("artifact_kind") == "table"),
            "pages": sum(1 for row in rows if row.get("artifact_kind") == "page"),
        },
        blockers=blockers,
    )


def build_visual_enrichment_queue(config: BlackLabelConfig, registry: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], PhaseResult]:
    rows: list[dict[str, Any]] = []
    for asset in registry:
        if not _needs_visual_queue(asset):
            continue
        priority = _visual_priority(asset)
        request = {
            "schema_version": VISUAL_QUEUE_SCHEMA_VERSION,
            "request_id": f"visual_{stable_hash({'asset': asset.get('asset_id'), 'profile': 'qwen-cinema-v1'})[:20]}",
            "asset_id": asset.get("asset_id"),
            "pdf_package_id": asset.get("pdf_package_id"),
            "page_package_id": asset.get("page_package_id"),
            "image_package_id": asset.get("image_package_id"),
            "package_key": asset.get("package_key"),
            "source_sha256": asset.get("source_sha256", ""),
            "artifact_kind": asset.get("artifact_kind"),
            "provider": config.visual_provider,
            "model": config.qwen_vision_model,
            "ocr_model": config.qwen_ocr_model,
            "endpoint_region": config.qwen_endpoint_region,
            "fallback_provider": config.visual_fallback_provider,
            "base_url_configured": bool(config.qwen_base_url),
            "api_key_configured": config.qwen_api_key_configured,
            "analysis_profile": "black_label_cinema_visual_grounding.v1",
            "requested_tasks": _visual_tasks(asset),
            "priority": priority,
            "priority_batch": _visual_priority_batch(priority),
            "status": "planned" if config.visual_provider == "qwen" else "blocked",
            "readiness_status": "provider_configured" if config.qwen_api_key_configured and config.qwen_base_url else "credentials_pending",
            "mutation_performed": False,
            "provider_call_performed": False,
        }
        request["provenance_hash"] = stable_hash(request)
        rows.append(_public_payload(request))
    rows.sort(key=lambda row: (-int(row.get("priority") or 0), str(row.get("asset_id") or "")))

    blockers = _provider_blockers(config)
    if not rows:
        blockers.append("no_visual_enrichment_requests")
    _write_jsonl(config.run_dir / "visual-enrichment-queue.jsonl", rows)
    return rows, PhaseResult(
        phase="U3",
        name="qwen-visual-queue",
        status="complete" if not blockers else "blocked",
        output_paths=["visual-enrichment-queue.jsonl"],
        counts={"visual_requests": len(rows), "provider_calls": 0},
        blockers=blockers,
    )


def build_black_label_cards(
    config: BlackLabelConfig,
    source: SourceBundle,
    registry: Sequence[Mapping[str, Any]],
    visual_queue: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], PhaseResult]:
    cards: list[dict[str, Any]] = []
    assets_by_package = _group_by(registry, "package_key")
    source_record_by_package = _first_by(source.normalized, "package_key")
    visual_by_asset = _first_by(visual_queue, "asset_id")
    for asset in registry:
        kind = str(asset.get("artifact_kind") or "")
        if kind == "pdf":
            cards.extend(_pdf_cards(config, asset))
        elif kind == "text":
            package_key = str(asset.get("package_key") or "")
            cards.extend(
                _text_cards(
                    config,
                    asset,
                    source_record_by_package.get(package_key, {}),
                    source.text_artifacts.get(package_key),
                )
            )
        elif kind in {"image", "table", "page"}:
            cards.append(_visual_evidence_card(config, asset, visual_by_asset.get(str(asset.get("asset_id") or ""), {})))

    for card in cards:
        package_ids = [str(item) for item in card.get("package_ids", []) if item]
        card["linked_asset_count"] = sum(len(assets_by_package.get(package_id, [])) for package_id in package_ids)
        card["provenance_hash"] = stable_hash({k: v for k, v in card.items() if k != "provenance_hash"})

    blockers: list[str] = []
    roles = {str(card.get("card_role") or "") for card in cards}
    missing_roles = sorted(CARD_ROLES - roles)
    if missing_roles:
        blockers.append(f"missing_card_roles:{','.join(missing_roles)}")
    if any(not card.get("package_ids") for card in cards):
        blockers.append("cards_missing_package_refs")
    if any(card.get("raw_source_text_included") for card in cards):
        blockers.append("raw_source_text_included")
    if find_public_leaks(cards):
        blockers.append("card_manifest_public_leak")

    _write_jsonl(config.run_dir / "black-label-card-manifest.jsonl", cards)
    return cards, PhaseResult(
        phase="U2-U4",
        name="black-label-cards",
        status="complete" if cards and not blockers else "blocked",
        output_paths=["black-label-card-manifest.jsonl"],
        counts={
            "cards": len(cards),
            **{f"role_{key}": value for key, value in Counter(str(card.get("card_role") or "unknown") for card in cards).items()},
        },
        blockers=blockers if cards else ["no_black_label_cards"],
    )


def build_kh_apply_plan(
    config: BlackLabelConfig,
    registry: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], PhaseResult]:
    rows: list[dict[str, Any]] = []
    for asset in registry:
        rows.append(
            _public_payload(
                {
                    "schema_version": KH_PLAN_SCHEMA_VERSION,
                    "kh_plan_id": f"kh_asset_{stable_hash(asset)[:20]}",
                    "target": "knowledge_hub_multimodal_package",
                    "asset_id": asset.get("asset_id"),
                    "package_key": asset.get("package_key"),
                    "pdf_package_id": asset.get("pdf_package_id"),
                    "image_package_id": asset.get("image_package_id"),
                    "modality": _kh_modality(asset),
                    "artifact_kind": asset.get("artifact_kind"),
                    "source_sha256": asset.get("source_sha256", ""),
                    "preview_reference": "",
                    "apply_status": "planned",
                    "handoff_status": "reviewed_apply_required",
                    "direct_datastore_write": False,
                    "mutation_performed": False,
                }
            )
        )
    for card in cards:
        rows.append(
            _public_payload(
                {
                    "schema_version": KH_PLAN_SCHEMA_VERSION,
                    "kh_plan_id": f"kh_card_{stable_hash(card)[:20]}",
                    "target": "knowledge_hub_text_layer",
                    "card_id": card.get("card_id"),
                    "card_role": card.get("card_role"),
                    "package_ids": card.get("package_ids", []),
                    "modality": "text",
                    "apply_status": "planned" if card.get("rights_status") == "clear" else "blocked",
                    "blocked_reason": "" if card.get("rights_status") == "clear" else "rights_status_not_clear",
                    "handoff_status": "reviewed_apply_required",
                    "direct_datastore_write": False,
                    "mutation_performed": False,
                }
            )
        )
    _write_jsonl(config.run_dir / "kh-multimodal-apply-plan.jsonl", rows)
    return rows, PhaseResult(
        phase="U6",
        name="kh-multimodal-apply-plan",
        status="complete" if rows and not find_public_leaks(rows) else "blocked",
        output_paths=["kh-multimodal-apply-plan.jsonl"],
        counts={"kh_plan_rows": len(rows), "mutations": 0},
        blockers=[] if rows and not find_public_leaks(rows) else ["kh_plan_invalid_or_leaky"],
    )


def build_lightrag_apply_plan(config: BlackLabelConfig, cards: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], PhaseResult]:
    rows: list[dict[str, Any]] = []
    for index, card in enumerate(cards, 1):
        blocked_reason = _lightrag_blocked_reason(config, card)
        row = {
            "schema_version": LIGHTRAG_PLAN_SCHEMA_VERSION,
            "graph_document_id": f"lightrag_black_label_{stable_hash(card)[:20]}",
            "card_id": card.get("card_id"),
            "card_role": card.get("card_role"),
            "source_package_refs": card.get("package_ids", []),
            "source_hashes": card.get("source_hashes", []),
            "estimated_chars": int(card.get("estimated_chars") or 0),
            "rights_status": card.get("rights_status"),
            "apply_stage": _apply_stage(index),
            "apply_status": "planned" if not blocked_reason else "blocked",
            "blocked_reason": blocked_reason,
            "mutation_performed": False,
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(_public_payload(row))
    blockers = []
    if not rows:
        blockers.append("no_lightrag_plan_rows")
    if all(row.get("apply_status") == "blocked" for row in rows):
        blockers.append("all_lightrag_rows_blocked")
    if find_public_leaks(rows):
        blockers.append("lightrag_plan_public_leak")
    _write_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl", rows)
    return rows, PhaseResult(
        phase="U5",
        name="lightrag-card-apply-plan",
        status="complete" if not blockers else "blocked",
        output_paths=["lightrag-card-apply-plan.jsonl"],
        counts={
            "lightrag_plan_rows": len(rows),
            "planned": sum(1 for row in rows if row.get("apply_status") == "planned"),
            "blocked": sum(1 for row in rows if row.get("apply_status") == "blocked"),
        },
        blockers=blockers,
    )


def build_cag_manifest(
    config: BlackLabelConfig,
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], PhaseResult]:
    graph_by_card = _first_by(lightrag_plan, "card_id")
    cards_by_topic: dict[str, list[Mapping[str, Any]]] = {}
    for card in cards:
        cards_by_topic.setdefault(_topic_for_card(card), []).append(card)

    rows: list[dict[str, Any]] = []
    for topic, topic_cards in sorted(cards_by_topic.items()):
        evidence_card_ids = [str(card.get("card_id") or "") for card in topic_cards if card.get("rights_status") == "clear"]
        graph_refs = [
            str(graph_by_card.get(card_id, {}).get("graph_document_id") or "")
            for card_id in evidence_card_ids
            if graph_by_card.get(card_id, {}).get("apply_status") == "planned"
        ]
        visual_refs = [
            str(card.get("visual_request_id") or "")
            for card in topic_cards
            if card.get("card_role") == "visual_evidence_card" and card.get("visual_request_id")
        ]
        row = {
            "schema_version": CAG_MANIFEST_SCHEMA_VERSION,
            "cag_pack_id": f"cag_black_label_{slugify(topic)}_{stable_hash(evidence_card_ids)[:12]}",
            "topic": topic,
            "evidence_card_ids": evidence_card_ids,
            "graph_refs": graph_refs,
            "visual_refs": visual_refs,
            "refresh_hash": stable_hash({"cards": evidence_card_ids, "graphs": graph_refs, "visual": visual_refs}),
            "raw_source_text_included": False,
            "status": "available" if evidence_card_ids and graph_refs else "blocked",
            "blocked_reason": "" if evidence_card_ids and graph_refs else "missing_evidence_or_graph_refs",
            "graph_readiness_status": "pending_lightrag_stage_evidence",
            "visual_readiness_status": "pending_qwen_visual_apply",
            "mutation_performed": False,
        }
        rows.append(_public_payload(row))
    blockers: list[str] = []
    if not rows:
        blockers.append("no_cag_manifest_rows")
    if any(row.get("raw_source_text_included") for row in rows):
        blockers.append("cag_raw_source_text_included")
    if not any(row.get("status") == "available" for row in rows):
        blockers.append("no_available_cag_packs")
    if find_public_leaks(rows):
        blockers.append("cag_manifest_public_leak")
    _write_jsonl(config.run_dir / "cag-pack-manifest.jsonl", rows)
    return rows, PhaseResult(
        phase="U7",
        name="cag-pack-manifest",
        status="complete" if not blockers else "blocked",
        output_paths=["cag-pack-manifest.jsonl"],
        counts={
            "cag_packs": len(rows),
            "available": sum(1 for row in rows if row.get("status") == "available"),
            "blocked": sum(1 for row in rows if row.get("status") == "blocked"),
        },
        blockers=blockers,
    )


def build_eval_suite(
    config: BlackLabelConfig,
    cards: Sequence[Mapping[str, Any]],
    cag_manifest: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], PhaseResult]:
    rows: list[dict[str, Any]] = []
    source_cards = [card for card in cards if card.get("card_role") == "source_card"]
    for card in source_cards[:24]:
        source_label = str(card.get("title") or card.get("card_id") or "source")
        rows.append(
            _public_payload(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "eval_id": f"eval_{stable_hash(card)[:20]}",
                    "query": f"What craft mechanisms are recoverable from {source_label}?",
                    "expected_card_ids": [card.get("card_id")],
                    "expected_package_refs": card.get("package_ids", []),
                    "expected_rights_safe": True,
                    "gate": "black_label_source_recall",
                }
            )
        )
    for pack in cag_manifest[:12]:
        rows.append(
            _public_payload(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "eval_id": f"eval_cag_{stable_hash(pack)[:20]}",
                    "query": f"Use the {pack.get('topic')} CAG pack to propose a rights-safe film craft move.",
                    "expected_cag_pack_id": pack.get("cag_pack_id"),
                    "expected_card_ids": pack.get("evidence_card_ids", [])[:5],
                    "expected_rights_safe": True,
                    "gate": "black_label_cag_recall",
                }
            )
        )
    blockers = [] if rows else ["no_eval_queries"]
    _write_jsonl(config.run_dir / "black-label-eval-suite.jsonl", rows)
    return rows, PhaseResult(
        phase="U8-eval",
        name="black-label-eval-suite",
        status="complete" if not blockers else "blocked",
        output_paths=["black-label-eval-suite.jsonl"],
        counts={"eval_queries": len(rows), "threshold_bps": int(config.eval_threshold * 10000)},
        blockers=blockers,
    )


def certify_run(
    config: BlackLabelConfig,
    source: SourceBundle,
    phases: Sequence[PhaseResult],
    registry: Sequence[Mapping[str, Any]],
    visual_queue: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    kh_plan: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
    cag_manifest: Sequence[Mapping[str, Any]],
    eval_suite: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], PhaseResult]:
    blockers: list[str] = []
    blockers.extend(f"{phase.phase}:{blocker}" for phase in phases for blocker in phase.blockers)
    if any(phase.mutation_performed for phase in phases):
        blockers.append("dry_run_mutation_detected")
    if source.certification.get("ok") is not True:
        blockers.append("source_p0p8_not_certified")
    if source.certification.get("mutation_performed"):
        blockers.append("source_p0p8_mutated")
    (
        source_rollout_schema,
        source_rollout_provenance,
        source_authorization,
        source_legacy_attestation,
    ) = _source_rollout_authorization(
        source.certification,
        source_bundle_binding=source.binding,
        legacy_source_certification_hash=config.legacy_source_certification_hash,
        legacy_source_bundle_hash=config.legacy_source_bundle_hash,
    )
    blockers.extend(_governed_p1_blockers(source_authorization))
    if not registry:
        blockers.append("missing_asset_registry")
    if not cards:
        blockers.append("missing_black_label_cards")
    if not kh_plan:
        blockers.append("missing_kh_apply_plan")
    if not lightrag_plan:
        blockers.append("missing_lightrag_apply_plan")
    if not cag_manifest:
        blockers.append("missing_cag_manifest")
    if not eval_suite:
        blockers.append("missing_eval_suite")
    image_rows = [row for row in registry if row.get("artifact_kind") == "image"]
    if any(not row.get("image_package_id") for row in image_rows):
        blockers.append("image_package_link_failure")
    if any(card.get("raw_source_text_included") for card in cards):
        blockers.append("card_raw_source_text_included")
    rights_blocked_cards = sum(1 for card in cards if card.get("rights_status") == "blocked")
    if any(pack.get("raw_source_text_included") for pack in cag_manifest):
        blockers.append("cag_raw_source_text_included")
    if any(card.get("card_role") not in CARD_ROLES for card in cards):
        blockers.append("unknown_card_role")
    if config.visual_provider != "qwen":
        blockers.append(f"visual_provider_not_qwen:{config.visual_provider}")

    public_payload = {
        "registry": list(registry),
        "visual_queue": list(visual_queue),
        "cards": list(cards),
        "kh_plan": list(kh_plan),
        "lightrag_plan": list(lightrag_plan),
        "cag_manifest": list(cag_manifest),
        "eval_suite": list(eval_suite),
    }
    leaks = find_public_leaks(public_payload)
    if leaks:
        blockers.append("public_leak_detected")
    source_certification_hash = stable_hash(source.certification)
    source_bundle_hash = str(source.binding.get("source_bundle_hash") or "")
    input_bindings = _lightrag_input_bindings(
        source_certification_hash,
        source_bundle_hash,
        cards,
        lightrag_plan,
    )
    stage_ledgers = _load_lightrag_stage_ledgers(config.run_dir, input_bindings=input_bindings)
    rollout_gates = _rollout_gates(registry=registry, leaks=leaks, stage_ledgers=stage_ledgers)
    full_corpus_apply_allowed = (
        not blockers
        and rollout_gates["gate_1_lightrag_one_card_sample"] == "pass"
        and rollout_gates["gate_2_lightrag_five_source_sample"] == "pass"
        and rollout_gates["gate_3_lightrag_topic_cluster"] == "pass"
    )

    generation_recipe = _generation_recipe(config)
    certification = {
        "schema_version": CERTIFICATION_SCHEMA_VERSION,
        "run_id": config.run_id,
        "source_run": _public_path(source.run_dir),
        "source_p0_p8_certification_hash": source_certification_hash,
        "source_bundle_binding": source.binding,
        "source_rollout_schema_version": source_rollout_schema,
        "source_rollout_provenance": source_rollout_provenance,
        "source_governed_p1_authorization": source_authorization,
        "source_legacy_attestation": source_legacy_attestation,
        "generation_recipe": generation_recipe,
        "generation_recipe_hash": stable_hash(generation_recipe),
        "certified_input_bindings": input_bindings,
        "ok": not blockers,
        "dry_run": not config.apply,
        "mutation_performed": False,
        "quality_bar": {
            "target_eval_threshold": config.eval_threshold,
            "judged_eval_required_before_scale": True,
            "full_corpus_apply_allowed": full_corpus_apply_allowed,
        },
        "rollout_gates": rollout_gates,
        "lightrag_stage_ledgers": {
            stage: {
                "ok": ledger.get("ok"),
                "blockers": ledger.get("blockers", []),
                "selected_count": ledger.get("selected_count", 0),
                "sent_count": ledger.get("sent_count", 0),
                "mutation_performed": ledger.get("mutation_performed", False),
                "stage_ledger": LIGHTRAG_STAGE_LEDGER_FILES[stage],
            }
            for stage, ledger in stage_ledgers.items()
        },
        "counts": {
            "registry_assets": len(registry),
            "pdf_assets": sum(1 for row in registry if row.get("artifact_kind") == "pdf"),
            "image_assets": len(image_rows),
            "visual_requests": len(visual_queue),
            "cards": len(cards),
            "rights_blocked_cards": rights_blocked_cards,
            "kh_plan_rows": len(kh_plan),
            "lightrag_plan_rows": len(lightrag_plan),
            "cag_packs": len(cag_manifest),
            "eval_queries": len(eval_suite),
            "lightrag_stage_ledgers": len(stage_ledgers),
            "leaks": len(leaks),
        },
        "blockers": blockers,
        "leak_samples": leaks[:10],
    }
    _write_json(config.run_dir / "black-label-certification.json", certification)
    return certification, PhaseResult(
        phase="U8-certify",
        name="black-label-certification",
        status="complete" if certification["ok"] else "blocked",
        output_paths=["black-label-certification.json", "report.md"],
        counts={key: int(value) for key, value in certification["counts"].items()},
        blockers=blockers,
    )


def _asset_registry_row(record: Mapping[str, Any], crosswalk: Mapping[str, Any], cag_by_package: Mapping[str, str]) -> dict[str, Any]:
    artifact_layer = str(record.get("artifact_layer") or "")
    artifact_kind = _artifact_kind(record)
    source_sha = str(record.get("source_sha256") or "")
    source_pdf_id = str(record.get("source_pdf_id") or "unknown")
    artifact_sha = str(record.get("artifact_sha256") or "")
    package_key = str(record.get("package_key") or stable_hash(record))
    page_number = _safe_int(record.get("page"))
    pdf_package_id = f"pdf_{source_sha[:20]}" if source_sha else f"pdf_{slugify(source_pdf_id)}"
    page_package_id = f"{pdf_package_id}:page:{page_number:04d}" if page_number else ""
    image_package_id = f"img_{artifact_sha[:20]}" if artifact_kind == "image" and artifact_sha else ""
    row = {
        "schema_version": ASSET_REGISTRY_SCHEMA_VERSION,
        "asset_id": f"asset_{stable_hash({'package': package_key, 'layer': artifact_layer, 'record': record.get('record_id')})[:20]}",
        "package_key": package_key,
        "pdf_package_id": pdf_package_id,
        "page_package_id": page_package_id,
        "image_package_id": image_package_id,
        "source_pdf_id": source_pdf_id,
        "source_sha256": source_sha,
        "artifact_sha256": artifact_sha,
        "source_relative_path": record.get("source_relative_path", ""),
        "output_relative_path": record.get("output_relative_path", ""),
        "artifact_layer": artifact_layer,
        "artifact_kind": artifact_kind,
        "output_file_kind": record.get("output_file_kind", ""),
        "page": page_number,
        "quality_status": record.get("quality_status", "unknown"),
        "status": _asset_status(record),
        "kh_candidate_id": crosswalk.get("kh_candidate_id", ""),
        "graph_document_id": crosswalk.get("graph_document_id", ""),
        "cag_pack_id": crosswalk.get("cag_pack_id") or cag_by_package.get(package_key, ""),
        "public_label": record.get("public_label") or source_pdf_id,
        "provenance_hash": record.get("provenance_hash") or stable_hash(record),
    }
    return _public_payload(row)


def _pdf_cards(config: BlackLabelConfig, asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    title = str(asset.get("public_label") or asset.get("source_pdf_id") or "source")
    package_ids = [str(asset.get("package_key") or "")]
    source_hashes = [str(asset.get("source_sha256") or "")] if asset.get("source_sha256") else []
    return [
        _card_row(config, "source_card", title, package_ids, source_hashes, "PDF source package and provenance card.", 1200, asset),
        _card_row(config, "relation_card", title, package_ids, source_hashes, "Relations between this source, its topic, and derived evidence layers.", 1600, asset),
        _card_row(config, "craft_application_card", title, package_ids, source_hashes, "Director-facing craft translation with rights-safe source grounding.", 2200, asset),
        _card_row(config, "retrieval_eval_card", title, package_ids, source_hashes, "Eval prompts for source recall, graph recovery, and rights-safe answer checks.", 900, asset),
    ]


def _text_cards(
    config: BlackLabelConfig,
    asset: Mapping[str, Any],
    source_record: Mapping[str, Any],
    text_snapshot: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    text_stats = _text_stats(asset, source_record, config, text_snapshot)
    title = str(asset.get("public_label") or asset.get("source_pdf_id") or "text")
    rights_status = "blocked" if text_stats["rights_warnings"] else "clear"
    card = _card_row(
        config,
        "concept_card",
        title,
        [str(asset.get("package_key") or "")],
        [str(asset.get("source_sha256") or "")] if asset.get("source_sha256") else [],
        "Concept extraction plan from bounded Docling text/DocTags evidence.",
        min(config.max_card_chars, max(900, int(text_stats["bounded_chars"]))),
        asset,
        rights_status=rights_status,
        rights_warnings=text_stats["rights_warnings"],
    )
    card["source_text_chars_observed"] = text_stats["observed_chars"]
    card["source_text_chars_read"] = text_stats["read_chars"]
    card["source_text_truncated_for_planning"] = text_stats["truncated"]
    card["heading_seeds"] = text_stats["heading_seeds"]
    card["raw_source_text_included"] = False
    card["payload_hash"] = stable_hash({"role": card["card_role"], "asset": asset.get("asset_id"), "headings": text_stats["heading_seeds"]})
    return [card]


def _visual_evidence_card(config: BlackLabelConfig, asset: Mapping[str, Any], visual_request: Mapping[str, Any]) -> dict[str, Any]:
    title = str(asset.get("public_label") or asset.get("source_pdf_id") or "visual")
    card = _card_row(
        config,
        "visual_evidence_card",
        title,
        [str(asset.get("package_key") or "")],
        [str(asset.get("source_sha256") or "")] if asset.get("source_sha256") else [],
        "Visual evidence package linking image/page/table assets to future Qwen analysis.",
        1400,
        asset,
    )
    card["visual_request_id"] = visual_request.get("request_id", "")
    card["visual_provider"] = visual_request.get("provider", config.visual_provider)
    card["visual_analysis_pending"] = True
    return card


def _card_row(
    config: BlackLabelConfig,
    role: str,
    title: str,
    package_ids: list[str],
    source_hashes: list[str],
    outline: str,
    estimated_chars: int,
    asset: Mapping[str, Any],
    *,
    rights_status: str = "clear",
    rights_warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "role": role,
        "title": title,
        "outline": outline,
        "package_ids": package_ids,
        "source_hashes": source_hashes,
        "asset_id": asset.get("asset_id"),
    }
    card = {
        "schema_version": CARD_SCHEMA_VERSION,
        "card_id": f"card_{role}_{stable_hash(payload)[:20]}",
        "card_role": role,
        "title": title,
        "package_ids": package_ids,
        "source_hashes": [item for item in source_hashes if item],
        "source_pdf_id": asset.get("source_pdf_id", ""),
        "model_profile": "black_label_docling_cards.v1",
        "rights_status": rights_status,
        "rights_warnings": list(rights_warnings or []),
        "raw_source_text_included": False,
        "payload_outline": outline,
        "payload_hash": stable_hash(payload),
        "estimated_chars": min(config.max_card_chars, int(estimated_chars)),
        "status": "candidate" if rights_status == "clear" else "blocked",
        "blocked_reason": "" if rights_status == "clear" else "rights_status_not_clear",
    }
    return _public_payload(card)


def _text_stats(
    asset: Mapping[str, Any],
    source_record: Mapping[str, Any],
    config: BlackLabelConfig,
    text_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    del asset, source_record
    warnings: list[str] = []
    heading_seeds: list[str] = []
    snapshot = text_snapshot if isinstance(text_snapshot, Mapping) else {}
    observed_chars = _safe_int(snapshot.get("byte_count"))
    text = str(snapshot.get("sample") or "")[: config.text_read_chars]
    read_chars = len(text)
    truncated = bool(snapshot.get("truncated"))
    if snapshot.get("status") == "available":
        lowered = text.lower()
        warnings.extend(pattern for pattern in RIGHTS_BLOCK_PATTERNS if pattern in lowered)
        heading_seeds = _heading_seeds(text)
    else:
        warnings.append("source_text_file_unavailable")
    return {
        "observed_chars": observed_chars,
        "read_chars": read_chars,
        "bounded_chars": min(config.max_card_chars, max(read_chars // 8, 800)),
        "truncated": truncated,
        "heading_seeds": heading_seeds,
        "rights_warnings": warnings,
    }


def _latest_certified_source_run(source_root: Path) -> Path:
    root = _repo_path(source_root)
    candidates = sorted(root.glob("*/p0-p8-certification.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            certification = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if certification.get("ok") is True and not certification.get("mutation_performed"):
            return path.parent
    raise FileNotFoundError(f"no_certified_p0p8_run_under:{_public_path(root)}")


def _artifact_kind(record: Mapping[str, Any]) -> str:
    layer = str(record.get("artifact_layer") or "")
    file_kind = str(record.get("output_file_kind") or "")
    if layer == "docling_document":
        return "pdf"
    if layer == "docling_overlay_page":
        return "page"
    if layer == "docling_extracted_image" or file_kind in MEDIA_FILE_KINDS:
        return "image"
    if layer == "docling_table" or file_kind in TABLE_FILE_KINDS:
        return "table"
    if file_kind in TEXT_FILE_KINDS or layer == "docling_output_file":
        return "text"
    return "artifact"


def _asset_status(record: Mapping[str, Any]) -> str:
    layer = str(record.get("artifact_layer") or "")
    if layer not in {"docling_document", "docling_overlay_page"} and not record.get("source_sha256"):
        return "blocked"
    if record.get("quality_status") == "blocked" or record.get("status") in {"failed", "blocked"}:
        return "blocked"
    if record.get("quality_status") in {"partial", "needs_review", "unknown"}:
        return "partial"
    return "available"


def _needs_visual_queue(asset: Mapping[str, Any]) -> bool:
    kind = asset.get("artifact_kind")
    if kind in {"image", "table"}:
        return True
    if kind == "page" and asset.get("quality_status") in {"enriched", "partial", "unknown"}:
        return True
    return False


def _visual_priority(asset: Mapping[str, Any]) -> int:
    kind = str(asset.get("artifact_kind") or "")
    text = f"{asset.get('source_relative_path', '')} {asset.get('public_label', '')}".lower()
    score = 60
    if kind == "page":
        score += 20
    if kind == "table":
        score += 15
    if asset.get("quality_status") == "enriched":
        score += 15
    if asset.get("quality_status") == "partial":
        score += 10
    for keywords in TOPIC_KEYWORDS.values():
        if any(keyword in text for keyword in keywords):
            score += 5
            break
    return min(score, 100)


def _visual_tasks(asset: Mapping[str, Any]) -> list[str]:
    tasks = ["cinematic_description", "composition", "color", "light", "decoupage", "grounding"]
    if asset.get("artifact_kind") in {"table", "page"}:
        tasks.extend(["ocr", "table_chart_formula_code_classification"])
    return tasks


def _visual_priority_batch(priority: int) -> str:
    if priority >= 90:
        return "p0_priority_visuals"
    if priority >= 75:
        return "p1_sample_visuals"
    return "p2_backlog_visuals"


def _provider_blockers(config: BlackLabelConfig) -> list[str]:
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


def _kh_modality(asset: Mapping[str, Any]) -> str:
    if asset.get("artifact_kind") == "image":
        return "image"
    return "text"


def _lightrag_blocked_reason(config: BlackLabelConfig, card: Mapping[str, Any]) -> str:
    if card.get("rights_status") != "clear":
        return "rights_status_not_clear"
    if card.get("raw_source_text_included"):
        return "raw_source_text_included"
    if int(card.get("estimated_chars") or 0) > config.max_card_chars:
        return "card_too_large"
    if not card.get("package_ids"):
        return "missing_package_refs"
    return ""


def _apply_stage(index: int) -> str:
    if index == 1:
        return "one_document_sample"
    if index <= 5:
        return "five_document_sample"
    if index <= 100:
        return "topic_cluster_sample"
    return "full_corpus_after_certification"


def _topic_for_card(card: Mapping[str, Any]) -> str:
    text = f"{card.get('title', '')} {card.get('source_pdf_id', '')} {card.get('payload_outline', '')}".lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return topic
    return "general-cinema-craft"


def _heading_seeds(text: str, limit: int = 8) -> list[str]:
    seeds: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        elif len(stripped) > 96 or stripped.endswith("."):
            continue
        if 3 <= len(stripped) <= 96:
            seeds.append(stripped)
        if len(seeds) >= limit:
            break
    return seeds


def _limited_source_hashes(records: Sequence[Mapping[str, Any]], limit_pdfs: int | None) -> set[str] | None:
    if limit_pdfs is None:
        return None
    hashes: list[str] = []
    for row in records:
        if row.get("artifact_layer") != "docling_document":
            continue
        source_sha = str(row.get("source_sha256") or "")
        if source_sha:
            hashes.append(source_sha)
        if len(hashes) >= limit_pdfs:
            break
    return set(hashes)


def _cag_by_package(cag_candidates: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for candidate in cag_candidates:
        cag_pack_id = str(candidate.get("cag_pack_id") or "")
        for package_key in candidate.get("evidence_package_keys", []):
            if package_key and cag_pack_id:
                result.setdefault(str(package_key), cag_pack_id)
    return result


def _group_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(row)
    return grouped


def _first_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in result:
            result[value] = row
    return result


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
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


def _write_report(config: BlackLabelConfig, certification: Mapping[str, Any]) -> None:
    counts = certification.get("counts") if isinstance(certification.get("counts"), Mapping) else {}
    blockers = certification.get("blockers") if isinstance(certification.get("blockers"), list) else []
    rollout_gates = certification.get("rollout_gates") if isinstance(certification.get("rollout_gates"), Mapping) else {}
    lines = [
        "# Black Label Docling Package Report",
        "",
        f"- Run id: `{config.run_id}`",
        f"- Certification ok: `{str(bool(certification.get('ok'))).lower()}`",
        f"- Dry run: `{str(not config.apply).lower()}`",
        f"- Registry assets: `{counts.get('registry_assets', 0)}`",
        f"- Image assets: `{counts.get('image_assets', 0)}`",
        f"- Cards: `{counts.get('cards', 0)}`",
        f"- LightRAG plan rows: `{counts.get('lightrag_plan_rows', 0)}`",
        f"- CAG packs: `{counts.get('cag_packs', 0)}`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- `{blocker}`" for blocker in blockers) if blockers else lines.append("- None")
    lines.extend(["", "## Rollout Gates", ""])
    if rollout_gates:
        lines.extend(f"- `{gate}`: `{state}`" for gate, state in rollout_gates.items())
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Next Apply Boundary",
            "",
            _next_apply_boundary(rollout_gates),
            "",
        ]
    )
    _write_text_atomic(config.run_dir / "report.md", "\n".join(lines))


def _next_apply_boundary(rollout_gates: Mapping[str, Any]) -> str:
    if rollout_gates.get("gate_1_lightrag_one_card_sample") != "pass":
        return "Run the reviewed first-card LightRAG sample before any broader LightRAG, KH, visual, or CAG mutation."
    if rollout_gates.get("gate_2_lightrag_five_source_sample") != "pass":
        return "Run the five-source LightRAG sample, then refresh certification before topic-cluster apply."
    if rollout_gates.get("gate_3_lightrag_topic_cluster") != "pass":
        return "Run the topic-cluster LightRAG sample, then refresh certification before full-corpus consideration."
    if rollout_gates.get("gate_6_full_84_pdf_apply") == "ready_for_operator_gate":
        return "Full-corpus LightRAG apply is technically unlocked, but KH, visual, and CAG remain reviewed handoff surfaces."
    return "Review blocked rollout gates before any additional apply."


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
    try:
        with tmp_path.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _repo_path(value: Any) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    return (p0p8.DEFAULT_PUBLIC_ROOT / path).resolve()


def _public_payload(value: Any) -> Any:
    return p0p8._public_payload(value)


def _public_path(value: Any) -> str:
    return p0p8._public_path(value)


def find_public_leaks(value: Any) -> list[str]:
    return p0p8.find_public_leaks(value)


def stable_hash(value: Any) -> str:
    return p0p8.stable_hash(value)


def slugify(value: str) -> str:
    return p0p8.slugify(value)


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


def _any_env(*names: str) -> bool:
    return bool(_first_env(*names))


def _status_counts_dict(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), Mapping) else payload
    return counts if isinstance(counts, Mapping) else {}


def _active_count(payload: Mapping[str, Any]) -> int:
    counts = _status_counts_dict(payload)
    return sum(_safe_int(counts.get(key)) for key in ("pending", "preprocessed", "processing"))


def _failed_count(payload: Mapping[str, Any]) -> int:
    return _safe_int(_status_counts_dict(payload).get("failed"))


def _all_count(payload: Mapping[str, Any]) -> int:
    return _safe_int(_status_counts_dict(payload).get("all"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Black Label post-Docling multimodal package plans.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=[
            "run-all",
            "refresh-certification",
            "migrate-legacy-bindings",
            "apply-lightrag-sample",
            "apply-lightrag-stage",
        ],
        default="run-all",
    )
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--source-run", type=Path, help="Certified P0-P8 source run for dry-run generation. Legacy sample apply also accepts a Black Label run here.")
    parser.add_argument("--black-label-run", type=Path, help="Generated Black Label run directory for staged apply or certification refresh.")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help=(
            "Root containing certified P0-P8 runs. Also used to recover an exact source "
            "bundle by its certified hashes when a Black Label artifact redacts source_run."
        ),
    )
    parser.add_argument("--limit-pdfs", type=int)
    parser.add_argument("--max-card-chars", type=int, default=DEFAULT_CARD_MAX_CHARS)
    parser.add_argument("--text-read-chars", type=int, default=DEFAULT_TEXT_READ_CHARS)
    parser.add_argument("--visual-provider", default="qwen")
    parser.add_argument("--visual-fallback-provider", default="gemini")
    parser.add_argument("--qwen-vision-model", default=os.getenv("QWEN_VISION_MODEL", DEFAULT_QWEN_VISION_MODEL))
    parser.add_argument("--qwen-ocr-model", default=os.getenv("QWEN_OCR_MODEL", DEFAULT_QWEN_OCR_MODEL))
    parser.add_argument("--qwen-endpoint-region", default=os.getenv("QWEN_ENDPOINT_REGION", DEFAULT_QWEN_ENDPOINT_REGION))
    parser.add_argument("--qwen-base-url", default=_first_env("QWEN_BASE_URL", "DASHSCOPE_BASE_URL", "ALIBABA_QWEN_BASE_URL"))
    parser.add_argument("--eval-threshold", type=float, default=DEFAULT_EVAL_THRESHOLD)
    parser.add_argument("--lightrag-base-url", default=os.getenv("LIGHTRAG_BASE_URL", DEFAULT_LIGHTRAG_BASE_URL))
    parser.add_argument("--lightrag-timeout-s", type=float, default=90.0)
    parser.add_argument("--lightrag-poll-interval-s", type=float, default=5.0)
    parser.add_argument("--lightrag-poll-timeout-s", type=float, default=1800.0)
    parser.add_argument("--lightrag-stage", choices=list(LIGHTRAG_STAGE_LEDGER_FILES), default="one_document_sample")
    parser.add_argument("--lightrag-batch-max-cards", type=int, default=DEFAULT_LIGHTRAG_BATCH_MAX_CARDS)
    parser.add_argument("--lightrag-batch-max-chars", type=int, default=DEFAULT_LIGHTRAG_BATCH_MAX_CHARS)
    parser.add_argument(
        "--legacy-source-certification-hash",
        default="",
        help=(
            "Explicitly attest one canonical P0-P8 certification hash as legacy_p0p8_v1. "
            "Required for every legacy certification, refresh, migration, and apply operation."
        ),
    )
    parser.add_argument(
        "--legacy-source-bundle-hash",
        default="",
        help=(
            "Explicitly attest the composite hash of the certification, normalized output, "
            "crosswalk, CAG candidates, and referenced text artifacts. Required with the "
            "legacy certification hash for every legacy operation."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Reserved for future apply paths; currently fails closed.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> BlackLabelConfig:
    return BlackLabelConfig(
        run_id=args.run_id,
        artifact_root=args.artifact_root,
        source_run=args.source_run,
        black_label_run=args.black_label_run,
        source_root=args.source_root,
        apply=args.apply,
        max_card_chars=args.max_card_chars,
        text_read_chars=args.text_read_chars,
        limit_pdfs=args.limit_pdfs,
        visual_provider=args.visual_provider,
        visual_fallback_provider=args.visual_fallback_provider,
        qwen_vision_model=args.qwen_vision_model,
        qwen_ocr_model=args.qwen_ocr_model,
        qwen_endpoint_region=args.qwen_endpoint_region,
        qwen_base_url=args.qwen_base_url,
        qwen_api_key_configured=_any_env("QWEN_API_KEY", "DASHSCOPE_API_KEY", "ALIBABA_QWEN_API_KEY", "ALIBABA_API_KEY"),
        eval_threshold=args.eval_threshold,
        lightrag_base_url=args.lightrag_base_url,
        lightrag_timeout_s=args.lightrag_timeout_s,
        lightrag_poll_interval_s=args.lightrag_poll_interval_s,
        lightrag_poll_timeout_s=args.lightrag_poll_timeout_s,
        lightrag_stage=args.lightrag_stage,
        lightrag_batch_max_cards=args.lightrag_batch_max_cards,
        lightrag_batch_max_chars=args.lightrag_batch_max_chars,
        legacy_source_certification_hash=args.legacy_source_certification_hash,
        legacy_source_bundle_hash=args.legacy_source_bundle_hash,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = config_from_args(args)
    if args.command == "run-all":
        generation_blocker = _generation_config_blocker(config)
        if generation_blocker:
            print(json.dumps({"ok": False, "blockers": [generation_blocker]}, indent=2, sort_keys=True))
            return 2
    if args.command == "apply-lightrag-sample":
        ledger = apply_lightrag_sample(config)
        print(
            json.dumps(
                {
                    "run_id": config.run_id,
                    "black_label_run": ledger.get("black_label_run"),
                    "ok": ledger.get("ok"),
                    "mutation_performed": ledger.get("mutation_performed"),
                    "blockers": ledger.get("blockers", []),
                    "sample": ledger.get("sample", {}),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if ledger.get("ok") else 2
    if args.command == "apply-lightrag-stage":
        if not args.black_label_run:
            print(json.dumps({"ok": False, "blockers": ["use_black_label_run_for_staged_apply"]}, indent=2, sort_keys=True))
            return 2
        ledger = apply_lightrag_stage(config)
        print(
            json.dumps(
                {
                    "run_id": config.run_id,
                    "black_label_run": ledger.get("black_label_run"),
                    "stage": ledger.get("stage"),
                    "ok": ledger.get("ok"),
                    "mutation_performed": ledger.get("mutation_performed"),
                    "selected_count": ledger.get("selected_count"),
                    "sent_count": ledger.get("sent_count"),
                    "blockers": ledger.get("blockers", []),
                    "stage_ledger": ledger.get("stage_ledger"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if ledger.get("ok") else 2
    if args.command == "refresh-certification":
        if args.source_run and not args.black_label_run:
            print(json.dumps({"ok": False, "blockers": ["use_black_label_run_for_certification_refresh"]}, indent=2, sort_keys=True))
            return 2
        result = refresh_black_label_certification(config)
        certification = result["certification"]
        print(
            json.dumps(
                {
                    "run_id": certification.get("run_id"),
                    "run_dir": result.get("run_dir"),
                    "ok": certification.get("ok"),
                    "rollout_gates": certification.get("rollout_gates", {}),
                    "quality_bar": certification.get("quality_bar", {}),
                    "blockers": certification.get("blockers", []),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if certification.get("ok") else 2
    if args.command == "migrate-legacy-bindings":
        if not args.black_label_run:
            print(json.dumps({"ok": False, "blockers": ["use_black_label_run_for_binding_migration"]}, indent=2, sort_keys=True))
            return 2
        result = migrate_legacy_lightrag_bindings(config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 2

    result = run_all(config)
    print(
        json.dumps(
            {
                "run_id": config.run_id,
                "run_dir": _public_path(config.run_dir),
                "ok": result["certification"]["ok"],
                "counts": result["certification"]["counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["certification"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
