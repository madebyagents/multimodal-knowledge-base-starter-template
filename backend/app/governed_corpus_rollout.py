"""Fail-closed, provider-free P0 adapter for governed local corpora.

The adapter reads an explicitly supplied source root and versioned policy,
production-profile, and runtime-capability manifests.  It only produces
public-safe planning artifacts.  It never calls a provider or datastore and it
does not implement the later LightRAG or Knowledge Hub mutation stages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from . import docling_black_label_package as black_label
from . import docling_kh_lightrag_cag_harness as p0p8
from . import governed_authority_evidence as authority_evidence
from . import runtime_capability_evidence as runtime_evidence

SCHEMA_VERSION = "dantedash.governed_corpus_rollout.v1"
POLICY_SCHEMA_VERSION = "dantedash.governed_corpus_policy.v1"
POLICY_SCHEMA_VERSION_V2 = "dantedash.governed_corpus_policy.v2"
PRODUCTION_PROFILE_SCHEMA_VERSION = (
    "dantedash.lightrag_multimodal_production_profile.v1"
)
RUNTIME_CAPABILITY_SCHEMA_VERSION = "dantedash.seedance_i2v_runtime_capabilities.v1"
RUNTIME_CAPABILITY_SCHEMA_VERSION_V2 = runtime_evidence.SCHEMA_VERSION
SOURCE_INVENTORY_SCHEMA_VERSION = "governed_source_inventory.v1"
RIGHTS_REGISTRY_SCHEMA_VERSION = "governed_rights_registry.v1"
RIGHTS_EVIDENCE_SCHEMA_VERSION = "dantedash.governed_rights_evidence.v1"
RIGHTS_EVIDENCE_SCHEMA_VERSION_V2 = authority_evidence.AUTHORITY_DECISION_SCHEMA_VERSION
VALUE_EVIDENCE_SCHEMA_VERSION = "dantedash.governed_corpus_value_evidence.v1"
VALUE_ARTIFACT_MANIFEST_SCHEMA_VERSION = "dantedash.governed_corpus_value_artifacts.v1"
AUTHORITY_BUNDLE_SCHEMA_VERSION = "dantedash.governed_authority_bundle.v1"

DEFAULT_ARTIFACT_ROOT = Path("logs/governed-corpus-rollout")
DEFAULT_PRODUCTION_PROFILE = Path(
    "backend/app/dante_visual/manifests/lightrag_multimodal_production_profile_20260807.v1.json"
)
DEFAULT_RUNTIME_CAPABILITIES = Path(
    "backend/app/dante_visual/manifests/seedance_i2v_runtime_capabilities_20260808.v1.json"
)

POLICY_TOP_LEVEL_KEYS = {
    "schema_version",
    "corpus_id",
    "policy_version",
    "policy_status",
    "source_root_contract",
    "inventory_contract",
    "source_classes",
    "topics",
    "stage_contract",
    "sources",
    "value_contract",
    "holdout_contract",
    "budget_contract",
    "capability_contract",
    "audit_contract",
}
POLICY_TOP_LEVEL_KEYS_V2 = POLICY_TOP_LEVEL_KEYS | {"evidence_generation"}
SOURCE_REQUIRED_KEYS = {
    "relative_path",
    "media_type",
    "size_bytes",
    "source_sha256",
    "source_id",
    "package_id",
    "source_class_id",
    "topic_id",
    "card_role",
    "risk_rank",
    "inventory_disposition",
    "rights_status",
    "rights_basis",
    "permitted_local_uses",
    "external_processing",
    "allowed_providers",
    "allowed_regions",
    "allowed_source_derived_fields",
    "evidence_refs",
    "evidence_predicates",
    "rights_evidence_sha256",
    "review_date",
    "reviewer_id",
    "apply_eligible",
    "blocking_reasons",
}
# Curated metadata is optional and tightly bounded. Raw text/media is never a
# valid policy field.
SOURCE_OPTIONAL_KEYS = {"title", "declared_summary", "heading_seeds", "relationships"}
EVIDENCE_PREDICATE_KEYS = {
    "provenance_present",
    "hash_bound_rights_record_present",
    "rightsholder_authority_proven",
    "local_embedding_permission_explicit",
    "derived_summary_permission_explicit",
    "external_provider_disclosure_permission_explicit",
    "generated_output_use_terms_preserved",
    "registered_asset_or_likeness_attestation_present",
}
UNIVERSAL_EVIDENCE_PREDICATES = {
    "provenance_present",
    "hash_bound_rights_record_present",
    "rightsholder_authority_proven",
    "local_embedding_permission_explicit",
    "derived_summary_permission_explicit",
}
PROVIDER_EVIDENCE_PREDICATES = {"external_provider_disclosure_permission_explicit"}
VISUAL_EVIDENCE_PREDICATES = {
    "generated_output_use_terms_preserved",
    "registered_asset_or_likeness_attestation_present",
}
ALLOWED_MEDIA = {"text/markdown": ".md", "image/png": ".png"}
ALLOWED_RIGHTS_STATUSES = {"verified_clear", "internal_use_only", "unknown", "blocked"}
ALLOWED_INVENTORY_DISPOSITIONS = {
    "selected",
    "skipped",
    "blocked",
    "duplicate",
    "review_required",
}
CARD_ROLES = set(black_label.CARD_ROLES)
REQUIRED_LOCAL_USES = {"local_embedding", "derived_summary"}
REQUIRED_SOURCE_DERIVED_FIELDS = {"title", "summary", "heading_seeds", "relationships"}
REQUIRED_LIGHTRAG_CAPABILITIES = {
    "lightrag.legacy_identity_reconciliation",
    "lightrag.authoritative_payload_hash_lookup",
    "lightrag.service_enforced_fencing",
}
REQUIRED_LIGHTRAG_CAPABILITY_PROOFS = {
    "lightrag.legacy_identity_reconciliation": {
        "status": "observed",
        "legacy_identity_reconciliation": True,
        "historical_ids_preserved": True,
    },
    "lightrag.authoritative_payload_hash_lookup": {
        "status": "observed",
        "authoritative_file_source_to_payload_hash_lookup": True,
        "immutable_payload_hash_persistence": True,
    },
    "lightrag.service_enforced_fencing": {
        "status": "observed",
        "service_enforced_single_use_mutation_fencing": True,
        "idle_and_settlement_status": True,
    },
}
POLICY_REQUIRED_LIGHTRAG_CAPABILITIES = {
    "authoritative_file_source_to_payload_hash_lookup",
    "immutable_payload_hash_persistence",
    "service_enforced_single_use_mutation_fencing",
    "idle_and_settlement_status",
}
POLICY_REQUIRED_LIGHTRAG_CAPABILITIES_V2 = {
    capability_id
    for capability_id, spec in runtime_evidence.CAPABILITY_SPECS.items()
    if spec.service_id == "lightrag"
}
POLICY_REQUIRED_KH_CAPABILITIES_V2 = {
    capability_id
    for capability_id, spec in runtime_evidence.CAPABILITY_SPECS.items()
    if spec.service_id == "knowledge_hub"
}
EVIDENCE_GENERATION_KEYS = {
    "generation_id",
    "subject_revision",
    "executable_tree_sha256",
    "trust_registry_ref",
    "trust_registry_sha256",
    "origin_observation_ref",
    "origin_observation_sha256",
    "authority_ref",
    "authority_sha256",
    "license_ref",
    "license_sha256",
    "value_baseline_ref",
    "value_baseline_sha256",
    "holdout_ref",
    "holdout_sha256",
    "runtime_capabilities_ref",
    "runtime_capabilities_sha256",
    "rights_records",
}
EVIDENCE_GENERATION_HASH_BINDINGS = (
    ("trust_registry_ref", "trust_registry_sha256"),
    ("origin_observation_ref", "origin_observation_sha256"),
    ("authority_ref", "authority_sha256"),
    ("license_ref", "license_sha256"),
    ("value_baseline_ref", "value_baseline_sha256"),
    ("holdout_ref", "holdout_sha256"),
    ("runtime_capabilities_ref", "runtime_capabilities_sha256"),
)
SUBJECT_STATIC_PATHS = {
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/app/dante_visual/manifests/lightrag_multimodal_production_profile_20260807.v1.json",
    "backend/app/dante_visual/manifests/governed_rights_trust_roots.v1.json",
}
ROLLOUT_STAGES = [
    "one_document_sample",
    "five_document_sample",
    "topic_cluster_sample",
    "full_corpus_after_certification",
]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,191}$")
GIT_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_CAPABILITY_AGE = timedelta(hours=24)
MAX_CAPABILITY_FUTURE_SKEW = timedelta(minutes=5)
MAX_CURATED_TEXT_CHARS = 2_048
MAX_CURATED_LIST_ITEMS = 32
MAX_CURATED_LIST_ITEM_CHARS = 256
MIN_BODY_REUSE_CHARS = 32
REDACTED_HOLDOUT_QUERY = "[REDACTED: source-body reuse detected]"
REDACTED_INVALID_HOLDOUT_QUERY = "[REDACTED: invalid holdout query]"
VALUE_CANDIDATE_METRIC_KEYS = {
    "routing_pass_count",
    "answer_criteria_pass_count",
    "negative_control_pass_count",
    "irrelevant_hit_rate_at_5",
    "estimated_cost_usd",
    "unsupported_current_claims",
    "raw_source_body_leaks",
    "invented_evidence_claims",
}
HOLDOUT_THRESHOLD_KEYS = {
    "topic_routing_pass_count_min",
    "answer_criteria_pass_count_min",
    "negative_control_pass_count_min",
    "unsupported_current_claims_max",
    "raw_source_body_leaks_max",
    "invented_evidence_claims_max",
}
HYPERFRAMES_VALUE_PREFLIGHT_SCHEMA_VERSION = "dantedash.hyperframes_value_preflight.v1"
HYPERFRAMES_VALUE_PREFLIGHT_QUERY_HASHES = {
    "dark-premium-gap": "6b50d5aa9a091ec366309e9b50ffd308b5a1489187d043cabecc9a5a8c22c0d3",
    "clean-corporate-gap": "61e2dd4c1daf6fe21c9ebb3654b97d15fe17f4e7bcb7178355cb63ce8fabc9ca",
    "neon-electric-gap": "27a71889b087e312ce3d9031aeea4e7ce04a9016fbf02b45aec249e0a7e94315",
    "nature-earth-gap": "29fe09bfda6ee4880cc15bdbc54d05e5218ee1c8dc629433a6ba2c9a2618f6f0",
}
HYPERFRAMES_VALUE_PREFLIGHT_EMPTY_RESPONSE_SHA256 = (
    "5021e624e752b001ce3e3846e8f158ed4aeb93a4c9a72fdb35a0c5b14a0eea84"
)
HYPERFRAMES_VALUE_PREFLIGHT_STATS = {
    "response_sha256": "6655adc9acf78375f297c18210df5f8492e7faf1439280006b5f0fc92183c89c",
    "total": 8497,
    "by_modality": {"image": 2423, "text": 4393, "video": 1681},
}
_MISSING = object()


@dataclass(frozen=True)
class GovernedCorpusConfig:
    run_id: str
    source_root: Path
    policy_manifest: Path
    production_profile: Path = DEFAULT_PRODUCTION_PROFILE
    runtime_capabilities: Path = DEFAULT_RUNTIME_CAPABILITIES
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT
    apply: bool = False

    @property
    def run_dir(self) -> Path:
        return _repo_path(self.artifact_root) / self.run_id


PhaseResult = black_label.PhaseResult


@dataclass(frozen=True)
class LoadedContracts:
    policy: dict[str, Any]
    profile: dict[str, Any]
    capabilities: dict[str, Any]
    holdout: dict[str, Any]
    policy_hash: str
    profile_hash: str
    capabilities_hash: str
    holdout_hash: str


def build_run_id() -> str:
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    return f"governed-corpus-{timestamp}-{secrets.token_hex(8)}"


stable_hash = p0p8.stable_hash
sha256_file = p0p8.sha256_file
slugify = p0p8.slugify
find_public_leaks = p0p8.find_public_leaks


def inventory_audit_digest(sources: Sequence[Mapping[str, Any]]) -> str:
    """Hash the immutable inventory fields in deterministic path order."""
    rows = sorted(sources, key=lambda source: str(source.get("relative_path") or ""))
    payload = "".join(
        f"{source.get('relative_path', '')}\t{_safe_int(source.get('size_bytes'))}\t{source.get('source_sha256', '')}\n"
        for source in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def subject_executable_tree_digest(
    repository_root: Path,
    *,
    revision: str | None = None,
) -> tuple[str, list[str]]:
    """Hash the exact governed executable subject from Git or the working tree."""

    root = repository_root.resolve(strict=False)
    if revision is not None:
        return _git_subject_executable_tree_digest(root, revision)

    paths = sorted(
        {
            *(
                path.relative_to(root).as_posix()
                for path in (root / "backend/app").rglob("*.py")
                if path.is_file() and not path.is_symlink()
            ),
            *SUBJECT_STATIC_PATHS,
        }
    )
    rows: dict[str, str] = {}
    blockers: list[str] = []
    for relative_path in paths:
        snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
            root,
            relative_path,
            blocker_prefix="subject_working_tree",
            max_bytes=64 * 1024 * 1024,
        )
        blockers.extend(snapshot_blockers)
        if snapshot is not None:
            rows[relative_path] = snapshot.sha256
    if blockers or set(SUBJECT_STATIC_PATHS) - set(rows):
        if set(SUBJECT_STATIC_PATHS) - set(rows):
            blockers.append("subject_working_tree_static_path_missing")
        return "", _dedupe(blockers)
    return stable_hash(dict(sorted(rows.items()))), []


def _git_subject_executable_tree_digest(
    repository_root: Path,
    revision: str,
) -> tuple[str, list[str]]:
    if not GIT_REVISION_RE.fullmatch(revision):
        return "", ["subject_revision_invalid"]
    try:
        ancestry = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "merge-base",
                "--is-ancestor",
                revision,
                "HEAD",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
        tree = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "ls-tree",
                "-r",
                "-z",
                revision,
                "--",
                "backend/app",
                *sorted(
                    SUBJECT_STATIC_PATHS
                    - {
                        "backend/app/dante_visual/manifests/governed_rights_trust_roots.v1.json"
                    }
                ),
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ["subject_git_inspection_failed"]
    blockers: list[str] = []
    if ancestry.returncode != 0:
        blockers.append("subject_revision_not_carrier_ancestor")
    if tree.returncode != 0:
        blockers.append("subject_git_tree_unavailable")
        return "", blockers

    object_ids: dict[str, str] = {}
    for entry in tree.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            _mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative_path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            blockers.append("subject_git_tree_entry_invalid")
            continue
        if object_type != "blob":
            continue
        if (
            relative_path.startswith("backend/app/") and relative_path.endswith(".py")
        ) or relative_path in SUBJECT_STATIC_PATHS:
            object_ids[relative_path] = object_id
    missing_static = SUBJECT_STATIC_PATHS - set(object_ids)
    if missing_static:
        blockers.append("subject_git_static_path_missing")
    if not any(
        path.startswith("backend/app/") and path.endswith(".py") for path in object_ids
    ):
        blockers.append("subject_git_python_set_empty")
    if blockers:
        return "", _dedupe(blockers)

    rows: dict[str, str] = {}
    for relative_path, object_id in sorted(object_ids.items()):
        try:
            blob = subprocess.run(
                ["git", "-C", str(repository_root), "cat-file", "blob", object_id],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "", ["subject_git_blob_read_failed"]
        if blob.returncode != 0:
            return "", ["subject_git_blob_read_failed"]
        rows[relative_path] = hashlib.sha256(blob.stdout).hexdigest()
    return stable_hash(dict(sorted(rows.items()))), []


def _repo_path(value: Any) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    return (p0p8.DEFAULT_PUBLIC_ROOT / path).resolve()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    lexical_root = Path(os.path.abspath(root))
    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("artifact_root_outside_repository_logs") from exc
    current = lexical_root
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("artifact_root_symlink_not_allowed")


def _validated_artifact_root(config: GovernedCorpusConfig) -> Path:
    if not isinstance(config.run_id, str) or not SAFE_ID_RE.fullmatch(config.run_id):
        raise ValueError("run_id_must_be_one_safe_component")
    repository_root = p0p8.DEFAULT_PUBLIC_ROOT.resolve(strict=True)
    repository_logs = repository_root / "logs"
    raw_artifact_root = Path(config.artifact_root)
    if not raw_artifact_root.is_absolute():
        raw_artifact_root = repository_root / raw_artifact_root
    artifact_root = raw_artifact_root.resolve(strict=False)
    resolved_logs = repository_logs.resolve(strict=False)
    try:
        artifact_root.relative_to(resolved_logs)
    except ValueError as exc:
        raise ValueError("artifact_root_outside_repository_logs") from exc
    if repository_logs.is_symlink():
        raise ValueError("repository_logs_symlink_not_allowed")
    _reject_symlink_components(repository_logs, raw_artifact_root)

    source_root = _repo_path(config.source_root).resolve(strict=False)
    if _paths_overlap(source_root, artifact_root):
        raise ValueError("source_artifact_overlap_not_allowed")
    return artifact_root


def _prepare_run_directory(config: GovernedCorpusConfig) -> Path:
    artifact_root = _validated_artifact_root(config)
    repository_logs = p0p8.DEFAULT_PUBLIC_ROOT.resolve(strict=True) / "logs"
    repository_logs.mkdir(mode=0o700, parents=False, exist_ok=True)
    artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _reject_symlink_components(
        repository_logs,
        Path(config.artifact_root)
        if Path(config.artifact_root).is_absolute()
        else p0p8.DEFAULT_PUBLIC_ROOT / config.artifact_root,
    )
    if artifact_root.resolve(strict=True) != artifact_root:
        raise ValueError("artifact_root_resolution_changed")

    run_dir = artifact_root / config.run_id
    try:
        existing_mode = os.lstat(run_dir).st_mode
    except FileNotFoundError:
        existing_mode = None
    if existing_mode is not None:
        if stat.S_ISLNK(existing_mode):
            raise ValueError("run_directory_symlink_not_allowed")
        raise FileExistsError(f"run_id_already_exists:{config.run_id}")
    try:
        os.mkdir(run_dir, 0o700)
    except FileExistsError as exc:
        raise FileExistsError(f"run_id_already_exists:{config.run_id}") from exc
    os.chmod(run_dir, 0o700)
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError("run_directory_not_private_regular_directory")
    return run_dir


def _read_json_snapshot(
    path: Path,
    *,
    blocker: str,
    blockers: list[str],
) -> tuple[dict[str, Any], authority_evidence.FileSnapshot | None]:
    snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
        path.parent,
        path.name,
        blocker_prefix=blocker,
        max_bytes=4 * 1024 * 1024,
    )
    blockers.extend(snapshot_blockers)
    if snapshot is None:
        return {}, None
    try:
        payload = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        blockers.append(f"{blocker}_invalid:{type(exc).__name__}")
        return {}, snapshot
    if not isinstance(payload, dict):
        blockers.append(f"{blocker}_not_object")
        return {}, snapshot
    return payload, snapshot


def _load_contracts(
    config: GovernedCorpusConfig,
) -> tuple[LoadedContracts | None, list[str], list[str]]:
    blockers: list[str] = []
    policy_path = _repo_path(config.policy_manifest)
    profile_path = _repo_path(config.production_profile)
    capabilities_path = _repo_path(config.runtime_capabilities)
    policy, policy_snapshot = _read_json_snapshot(
        policy_path,
        blocker="policy_manifest",
        blockers=blockers,
    )
    profile, profile_snapshot = _read_json_snapshot(
        profile_path,
        blocker="production_profile",
        blockers=blockers,
    )
    capabilities, capabilities_snapshot = _read_json_snapshot(
        capabilities_path,
        blocker="runtime_capabilities",
        blockers=blockers,
    )
    if blockers:
        return None, blockers, []
    assert policy_snapshot is not None
    assert profile_snapshot is not None
    assert capabilities_snapshot is not None

    profile_hash = profile_snapshot.sha256
    capabilities_hash = capabilities_snapshot.sha256
    leaks: list[str] = []
    try:
        blockers.extend(_validate_policy(policy))
        blockers.extend(_validate_production_profile(profile))
        blockers.extend(
            _validate_runtime_capabilities(capabilities, profile_snapshot.sha256)
        )
        holdout_contract = (
            policy.get("holdout_contract")
            if isinstance(policy.get("holdout_contract"), Mapping)
            else {}
        )
        holdout = dict(holdout_contract)
        holdout_hash = _holdout_digest(holdout_contract) if holdout_contract else ""
        blockers.extend(_validate_holdout(holdout_contract))
        if holdout_hash != str(holdout_contract.get("contract_sha256") or ""):
            blockers.append("holdout_hash_mismatch")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        blockers.append("contract_validation_failed_closed")
        return None, _dedupe(blockers), []

    if policy.get("schema_version") == POLICY_SCHEMA_VERSION_V2:
        try:
            blockers.extend(
                _validate_evidence_generation_files(
                    policy,
                    policy_path=policy_path,
                    capabilities=capabilities,
                    capabilities_path=capabilities_path,
                    capabilities_sha256=capabilities_snapshot.sha256,
                )
            )
        except (TypeError, ValueError, OverflowError, UnicodeError):
            blockers.append("evidence_generation_validation_failed_closed")

    try:
        blockers.extend(
            _validate_value_evidence(
                policy,
                capabilities,
                policy_manifest_parent=policy_path.parent,
                profile_hash=profile_hash,
                capabilities_hash=capabilities_hash,
                holdout_hash=holdout_hash,
            )
        )
    except (TypeError, ValueError, OverflowError, UnicodeError):
        blockers.append("value_evidence_validation_failed_closed")

    try:
        leaks = find_public_leaks(
            {
                "policy": policy,
                "profile": profile,
                "capabilities": capabilities,
                "holdout": holdout,
            }
        )
        if leaks:
            blockers.append("input_manifest_public_leak")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        blockers.append("input_manifest_leak_scan_failed_closed")

    if blockers:
        # Structurally valid contracts may still be returned so a blocked run can
        # freeze inventory. Missing/unparseable contracts cannot.
        fatal_tokens = {
            "policy_manifest_missing",
            "policy_manifest_not_object",
            "production_profile_missing",
            "production_profile_not_object",
            "runtime_capabilities_missing",
            "runtime_capabilities_not_object",
            "policy_schema_mismatch",
            "policy_top_level_keys_mismatch",
            "production_profile_schema_mismatch",
            "runtime_capabilities_schema_mismatch",
        }
        fatal = any(
            item.split(":", 1)[0] in fatal_tokens
            or item.startswith(
                (
                    "policy_manifest_invalid:",
                    "production_profile_invalid:",
                    "runtime_capabilities_invalid:",
                    "source_",
                    "source_class_",
                    "topic_",
                )
            )
            or item
            in {
                "policy_sources_invalid",
                "policy_source_classes_invalid",
                "policy_topics_invalid",
                "source_classes_invalid",
                "topics_invalid",
                "holdout_queries_missing",
            }
            or (
                not item.startswith(
                    (
                        "runtime_capabilit",
                        "authority_",
                        "evidence_generation_",
                        "rights_",
                        "value_evidence_",
                        "value_artifact_",
                        "value_preflight_",
                        "holdout_",
                    )
                )
                and any(
                    marker in item.split(":", 1)[0]
                    for marker in (
                        "_invalid",
                        "_keys_mismatch",
                        "_schema_mismatch",
                    )
                )
            )
            for item in blockers
        )
        if fatal:
            return None, _dedupe(blockers), leaks
    return (
        LoadedContracts(
            policy=policy,
            profile=profile,
            capabilities=capabilities,
            holdout=holdout,
            policy_hash=policy_snapshot.sha256,
            profile_hash=profile_hash,
            capabilities_hash=capabilities_hash,
            holdout_hash=holdout_hash,
        ),
        _dedupe(blockers),
        leaks,
    )


def _validate_policy(policy: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    schema_version = policy.get("schema_version")
    if not isinstance(schema_version, str) or schema_version not in {
        POLICY_SCHEMA_VERSION,
        POLICY_SCHEMA_VERSION_V2,
    }:
        blockers.append("policy_schema_mismatch")
    expected_top_level = (
        POLICY_TOP_LEVEL_KEYS_V2
        if schema_version == POLICY_SCHEMA_VERSION_V2
        else POLICY_TOP_LEVEL_KEYS
    )
    if set(policy) != expected_top_level:
        blockers.append("policy_top_level_keys_mismatch")
    for key in ("corpus_id", "policy_version", "policy_status"):
        if not isinstance(policy.get(key), str) or not str(policy.get(key)).strip():
            blockers.append(f"policy_{key}_invalid")
    if policy.get("policy_status") != "frozen":
        blockers.append("policy_not_frozen")
    for key in (
        "source_root_contract",
        "inventory_contract",
        "stage_contract",
        "value_contract",
        "holdout_contract",
        "budget_contract",
        "capability_contract",
        "audit_contract",
    ):
        if not isinstance(policy.get(key), Mapping):
            blockers.append(f"policy_{key}_invalid")
    for key in ("source_classes", "topics", "sources"):
        if not isinstance(policy.get(key), list):
            blockers.append(f"policy_{key}_invalid")

    sources = policy.get("sources") if isinstance(policy.get("sources"), list) else []
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            blockers.append(f"source_entry_not_object:{index}")
            continue
        keys = set(source)
        if (
            not SOURCE_REQUIRED_KEYS <= keys
            or keys - SOURCE_REQUIRED_KEYS - SOURCE_OPTIONAL_KEYS
        ):
            blockers.append(f"source_keys_mismatch:{index}")
        blockers.extend(_validate_source_schema(source, index))

    blockers.extend(_validate_source_contract_refs(policy))
    blockers.extend(_validate_source_root_contract(policy.get("source_root_contract")))
    blockers.extend(_validate_inventory_contract(policy))
    blockers.extend(
        _validate_stage_contract(
            policy.get("stage_contract"),
            schema_version=schema_version,
            declared_source_paths={
                str(source.get("relative_path") or "")
                for source in sources
                if isinstance(source, Mapping)
            },
            source_topics={
                str(source.get("relative_path") or ""): str(
                    source.get("topic_id") or ""
                )
                for source in sources
                if isinstance(source, Mapping)
            },
        )
    )
    blockers.extend(
        _validate_value_contract(
            policy.get("value_contract"),
            strict_v2=schema_version == POLICY_SCHEMA_VERSION_V2,
        )
    )
    blockers.extend(
        _validate_holdout(
            policy.get("holdout_contract")
            if isinstance(policy.get("holdout_contract"), Mapping)
            else {}
        )
    )
    blockers.extend(_validate_budget_contract(policy.get("budget_contract")))
    blockers.extend(
        _validate_policy_capabilities(
            policy.get("capability_contract"),
            schema_version=schema_version,
        )
    )
    blockers.extend(_validate_audit_contract(policy.get("audit_contract")))
    if schema_version == POLICY_SCHEMA_VERSION_V2:
        blockers.extend(
            _validate_evidence_generation_shape(
                policy.get("evidence_generation"), policy
            )
        )
    return _dedupe(blockers)


def _validate_evidence_generation_shape(
    value: Any, policy: Mapping[str, Any]
) -> list[str]:
    if not isinstance(value, Mapping):
        return ["evidence_generation_invalid"]
    blockers: list[str] = []
    if set(value) != EVIDENCE_GENERATION_KEYS:
        blockers.append("evidence_generation_keys_mismatch")
    if not SAFE_ID_RE.fullmatch(str(value.get("generation_id") or "")):
        blockers.append("evidence_generation_id_invalid")
    if not GIT_REVISION_RE.fullmatch(str(value.get("subject_revision") or "")):
        blockers.append("evidence_generation_subject_revision_invalid")
    if not SHA256_RE.fullmatch(str(value.get("executable_tree_sha256") or "")):
        blockers.append("evidence_generation_executable_tree_invalid")
    seen_refs: set[str] = set()
    for ref_key, hash_key in EVIDENCE_GENERATION_HASH_BINDINGS:
        ref = value.get(ref_key)
        digest = value.get(hash_key)
        if not _is_safe_relative_path(ref):
            blockers.append(f"evidence_generation_{ref_key}_invalid")
        elif str(ref) in seen_refs:
            blockers.append("evidence_generation_duplicate_ref")
        else:
            seen_refs.add(str(ref))
        if not SHA256_RE.fullmatch(str(digest or "")):
            blockers.append(f"evidence_generation_{hash_key}_invalid")

    records = value.get("rights_records")
    if not isinstance(records, list):
        blockers.append("evidence_generation_rights_records_invalid")
        records = []
    policy_sources = (
        policy.get("sources") if isinstance(policy.get("sources"), list) else []
    )
    expected_source_ids = {
        str(source.get("source_id") or "")
        for source in policy_sources
        if isinstance(source, Mapping) and source.get("apply_eligible") is True
    }
    source_by_id = {
        str(source.get("source_id") or ""): source
        for source in policy_sources
        if isinstance(source, Mapping)
    }
    actual_source_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {
            "source_id",
            "artifact_ref",
            "sha256",
        }:
            blockers.append(f"evidence_generation_rights_record_invalid:{index}")
            continue
        source_id = str(record.get("source_id") or "")
        artifact_ref = record.get("artifact_ref")
        digest = record.get("sha256")
        if not SAFE_ID_RE.fullmatch(source_id) or source_id in actual_source_ids:
            blockers.append(f"evidence_generation_rights_source_invalid:{index}")
        actual_source_ids.add(source_id)
        if not _is_safe_relative_path(artifact_ref) or str(artifact_ref) in seen_refs:
            blockers.append(f"evidence_generation_rights_ref_invalid:{index}")
        else:
            seen_refs.add(str(artifact_ref))
        if not SHA256_RE.fullmatch(str(digest or "")):
            blockers.append(f"evidence_generation_rights_hash_invalid:{index}")
        bound_source = source_by_id.get(source_id)
        if bound_source is not None and (
            bound_source.get("evidence_refs") != [artifact_ref]
            or bound_source.get("rights_evidence_sha256") != digest
        ):
            blockers.append("evidence_generation_source_rights_binding_mismatch")
    if actual_source_ids != expected_source_ids:
        blockers.append("evidence_generation_rights_membership_mismatch")
    return _dedupe(blockers)


def _validate_evidence_generation_files(
    policy: Mapping[str, Any],
    *,
    policy_path: Path,
    capabilities: Mapping[str, Any],
    capabilities_path: Path,
    capabilities_sha256: str,
) -> list[str]:
    generation = policy.get("evidence_generation")
    if not isinstance(generation, Mapping):
        return ["evidence_generation_invalid"]
    base = policy_path.parent
    blockers: list[str] = []

    for ref_key, hash_key in EVIDENCE_GENERATION_HASH_BINDINGS:
        snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
            base,
            str(generation.get(ref_key) or ""),
            blocker_prefix=f"evidence_generation_{ref_key}",
            max_bytes=2 * 1024 * 1024,
        )
        blockers.extend(snapshot_blockers)
        if snapshot is not None and snapshot.sha256 != generation.get(hash_key):
            blockers.append(f"evidence_generation_{ref_key}_hash_mismatch")
    rights_records = (
        generation.get("rights_records")
        if isinstance(generation.get("rights_records"), list)
        else []
    )
    for index, record in enumerate(rights_records):
        if not isinstance(record, Mapping):
            continue
        snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
            base,
            str(record.get("artifact_ref") or ""),
            blocker_prefix=f"evidence_generation_rights_record:{index}",
            max_bytes=2 * 1024 * 1024,
        )
        blockers.extend(snapshot_blockers)
        if snapshot is not None and snapshot.sha256 != record.get("sha256"):
            blockers.append(f"evidence_generation_rights_record_hash_mismatch:{index}")

    registry_ref = str(generation.get("trust_registry_ref") or "")
    if registry_ref != "governed_rights_trust_roots.v1.json":
        blockers.append("evidence_generation_trust_registry_ref_untrusted")
    registry_path = base / PurePosixPath(registry_ref)
    registry, registry_blockers = authority_evidence.load_trust_registry(registry_path)
    blockers.extend(registry_blockers)
    if registry is not None and registry.sha256 != generation.get(
        "trust_registry_sha256"
    ):
        blockers.append("evidence_generation_trust_registry_hash_mismatch")

    observation, observation_blockers = _load_hash_bound_json_snapshot(
        base,
        generation.get("origin_observation_ref"),
        generation.get("origin_observation_sha256"),
        blocker_prefix="evidence_generation_origin_observation",
    )
    blockers.extend(observation_blockers)
    if registry is not None and observation is not None:
        blockers.extend(
            authority_evidence.validate_origin_observation(registry, observation)
        )

    license_snapshot, license_blockers = authority_evidence.snapshot_anchored_file(
        base,
        str(generation.get("license_ref") or ""),
        blocker_prefix="evidence_generation_license",
        max_bytes=2 * 1024 * 1024,
    )
    blockers.extend(license_blockers)
    if registry is not None and license_snapshot is not None:
        license_policy = registry.payload.get("license_policy", {})
        if license_snapshot.sha256 != license_policy.get(
            "license_sha256"
        ) or license_snapshot.git_blob_sha1 != license_policy.get("license_blob_sha1"):
            blockers.append("evidence_generation_license_registry_mismatch")

    capability_ref = str(generation.get("runtime_capabilities_ref") or "")
    expected_capability_path = os.path.abspath(base / PurePosixPath(capability_ref))
    if expected_capability_path != os.path.abspath(capabilities_path):
        blockers.append("evidence_generation_runtime_capabilities_ref_mismatch")
    if generation.get("runtime_capabilities_sha256") != capabilities_sha256:
        blockers.append("evidence_generation_runtime_capabilities_hash_mismatch")
    subject = (
        capabilities.get("subject")
        if isinstance(capabilities.get("subject"), Mapping)
        else {}
    )
    for key, subject_key in (
        ("subject_revision", "revision"),
        ("executable_tree_sha256", "executable_tree_sha256"),
    ):
        if generation.get(key) != subject.get(subject_key):
            blockers.append(f"evidence_generation_subject_binding_mismatch:{key}")
    subject_revision = str(generation.get("subject_revision") or "")
    expected_subject_digest = str(generation.get("executable_tree_sha256") or "")
    git_subject_digest, git_subject_blockers = subject_executable_tree_digest(
        p0p8.DEFAULT_PUBLIC_ROOT,
        revision=subject_revision,
    )
    blockers.extend(git_subject_blockers)
    if git_subject_digest and git_subject_digest != expected_subject_digest:
        blockers.append("evidence_generation_subject_git_digest_mismatch")
    working_subject_digest, working_subject_blockers = subject_executable_tree_digest(
        p0p8.DEFAULT_PUBLIC_ROOT,
    )
    blockers.extend(working_subject_blockers)
    if working_subject_digest and working_subject_digest != expected_subject_digest:
        blockers.append("evidence_generation_subject_working_tree_digest_mismatch")

    holdout, holdout_blockers = _load_hash_bound_json_snapshot(
        base,
        generation.get("holdout_ref"),
        generation.get("holdout_sha256"),
        blocker_prefix="evidence_generation_holdout",
    )
    blockers.extend(holdout_blockers)
    if holdout is not None and not _json_values_exact(
        holdout, policy.get("holdout_contract")
    ):
        blockers.append("evidence_generation_holdout_binding_mismatch")

    value = (
        policy.get("value_contract")
        if isinstance(policy.get("value_contract"), Mapping)
        else {}
    )
    if generation.get("value_baseline_ref") != value.get(
        "candidate_evidence_ref"
    ) or generation.get("value_baseline_sha256") != value.get(
        "candidate_evidence_sha256"
    ):
        blockers.append("evidence_generation_value_binding_mismatch")

    policy_sources = (
        policy.get("sources") if isinstance(policy.get("sources"), list) else []
    )
    source_by_id = {
        str(source.get("source_id") or ""): source
        for source in policy_sources
        if isinstance(source, Mapping)
    }
    expected_decisions: list[dict[str, Any]] = []
    for record in rights_records:
        if not isinstance(record, Mapping):
            continue
        source = source_by_id.get(str(record.get("source_id") or ""), {})
        if source.get("evidence_refs") != [record.get("artifact_ref")] or source.get(
            "rights_evidence_sha256"
        ) != record.get("sha256"):
            blockers.append("evidence_generation_source_rights_binding_mismatch")
        expected_decisions.append(
            {
                "source_id": record.get("source_id"),
                "relative_path": source.get("relative_path"),
                "rights_evidence_sha256": record.get("sha256"),
                "decision": "eligible",
            }
        )

    authority_bundle, authority_blockers = _load_hash_bound_json_snapshot(
        base,
        generation.get("authority_ref"),
        generation.get("authority_sha256"),
        blocker_prefix="evidence_generation_authority",
    )
    blockers.extend(authority_blockers)
    expected_bundle = {
        "schema_version": AUTHORITY_BUNDLE_SCHEMA_VERSION,
        "generation_id": generation.get("generation_id"),
        "decision": "eligible",
        "trust_registry_sha256": generation.get("trust_registry_sha256"),
        "origin_observation_sha256": generation.get("origin_observation_sha256"),
        "license_sha256": generation.get("license_sha256"),
        "policy_engine_id": authority_evidence.POLICY_ENGINE_ID,
        "source_decisions": sorted(
            expected_decisions,
            key=lambda row: str(row.get("relative_path") or ""),
        ),
    }
    if authority_bundle is not None and not _json_values_exact(
        authority_bundle, expected_bundle
    ):
        blockers.append("evidence_generation_authority_bundle_mismatch")

    blockers.extend(_validate_generation_directory_membership(base, generation, value))
    return _dedupe(blockers)


def _validate_generation_directory_membership(
    base: Path,
    generation: Mapping[str, Any],
    value: Mapping[str, Any],
) -> list[str]:
    authority_ref = generation.get("authority_ref")
    if not _is_safe_relative_path(authority_ref):
        return ["evidence_generation_directory_invalid"]
    generation_dir = PurePosixPath(str(authority_ref)).parent
    if generation_dir == PurePosixPath("."):
        return ["evidence_generation_directory_invalid"]
    expected_refs = {
        str(generation.get(key) or "")
        for key in (
            "origin_observation_ref",
            "authority_ref",
            "license_ref",
            "value_baseline_ref",
            "holdout_ref",
        )
    }
    rights_records = (
        generation.get("rights_records")
        if isinstance(generation.get("rights_records"), list)
        else []
    )
    expected_refs.update(
        str(record.get("artifact_ref") or "")
        for record in rights_records
        if isinstance(record, Mapping)
    )
    value_certificate, _blockers = _load_hash_bound_json_snapshot(
        base,
        value.get("candidate_evidence_ref"),
        value.get("candidate_evidence_sha256"),
        blocker_prefix="evidence_generation_value_certificate",
    )
    if value_certificate is not None:
        artifact_manifest_ref = value_certificate.get("artifact_manifest_ref")
        if isinstance(artifact_manifest_ref, str):
            expected_refs.add(artifact_manifest_ref)
            artifact_manifest, _manifest_blockers = _load_hash_bound_json_snapshot(
                base,
                artifact_manifest_ref,
                value_certificate.get("artifact_manifest_sha256"),
                blocker_prefix="evidence_generation_value_artifact_manifest",
            )
            artifact_rows = (
                artifact_manifest.get("artifacts")
                if isinstance(artifact_manifest, Mapping)
                and isinstance(artifact_manifest.get("artifacts"), list)
                else []
            )
            if artifact_manifest is not None:
                expected_refs.update(
                    str(row.get("artifact_ref") or "")
                    for row in artifact_rows
                    if isinstance(row, Mapping)
                )
    directory_path = base / generation_dir
    try:
        actual_refs = {
            path.relative_to(base).as_posix()
            for path in directory_path.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if any(path.is_symlink() for path in directory_path.rglob("*")):
            return ["evidence_generation_directory_symlink_not_allowed"]
    except OSError:
        return ["evidence_generation_directory_unreadable"]
    if any(
        not _is_safe_relative_path(ref)
        or not PurePosixPath(ref).is_relative_to(generation_dir)
        for ref in expected_refs
    ):
        return ["evidence_generation_ref_outside_directory"]
    if actual_refs != expected_refs:
        return ["evidence_generation_directory_membership_mismatch"]
    return []


def _validate_source_schema(source: Mapping[str, Any], index: int) -> list[str]:
    blockers: list[str] = []
    string_fields = (
        "relative_path",
        "media_type",
        "source_sha256",
        "source_id",
        "package_id",
        "source_class_id",
        "topic_id",
        "card_role",
        "inventory_disposition",
        "rights_status",
        "rights_basis",
        "review_date",
        "reviewer_id",
    )
    for key in string_fields:
        if not isinstance(source.get(key), str):
            blockers.append(f"source_{key}_invalid:{index}")
    if (
        not isinstance(source.get("size_bytes"), int)
        or _safe_int(source.get("size_bytes")) < 0
    ):
        blockers.append(f"source_size_bytes_invalid:{index}")
    if not isinstance(source.get("risk_rank"), int):
        blockers.append(f"source_risk_rank_invalid:{index}")
    for key in (
        "permitted_local_uses",
        "allowed_providers",
        "allowed_regions",
        "allowed_source_derived_fields",
        "evidence_refs",
        "blocking_reasons",
    ):
        if not _is_bounded_string_list(
            source.get(key), max_items=MAX_CURATED_LIST_ITEMS
        ):
            blockers.append(f"source_{key}_invalid:{index}")
    for key in ("external_processing", "apply_eligible"):
        if not isinstance(source.get(key), bool):
            blockers.append(f"source_{key}_invalid:{index}")
    predicates = source.get("evidence_predicates")
    if (
        not isinstance(predicates, Mapping)
        or not set(predicates) <= EVIDENCE_PREDICATE_KEYS
        or any(not isinstance(value, bool) for value in predicates.values())
    ):
        blockers.append(f"source_evidence_predicates_invalid:{index}")
    evidence_sha = source.get("rights_evidence_sha256")
    if evidence_sha is not None and (
        not isinstance(evidence_sha, str) or not SHA256_RE.fullmatch(evidence_sha)
    ):
        blockers.append(f"source_rights_evidence_sha256_invalid:{index}")
    if source.get("media_type") not in ALLOWED_MEDIA:
        blockers.append(f"source_media_type_unallowlisted:{index}")
    if source.get("rights_status") not in ALLOWED_RIGHTS_STATUSES:
        blockers.append(f"source_rights_status_invalid:{index}")
    if source.get("inventory_disposition") not in ALLOWED_INVENTORY_DISPOSITIONS:
        blockers.append(f"source_inventory_disposition_invalid:{index}")
    if source.get("card_role") not in CARD_ROLES:
        blockers.append(f"source_card_role_invalid:{index}")
    if not SHA256_RE.fullmatch(str(source.get("source_sha256") or "")):
        blockers.append(f"source_sha256_invalid:{index}")
    for key in ("source_id", "package_id", "source_class_id", "topic_id"):
        if not SAFE_ID_RE.fullmatch(str(source.get(key) or "")):
            blockers.append(f"source_{key}_unsafe:{index}")
    if not _is_bounded_text(
        source.get("rights_basis"), max_chars=MAX_CURATED_TEXT_CHARS, allow_empty=True
    ):
        blockers.append(f"source_rights_basis_invalid:{index}")
    if source.get("reviewer_id") and not SAFE_ID_RE.fullmatch(
        str(source.get("reviewer_id") or "")
    ):
        blockers.append(f"source_reviewer_id_unsafe:{index}")
    if source.get("review_date"):
        try:
            date.fromisoformat(str(source.get("review_date")))
        except ValueError:
            blockers.append(f"source_review_date_invalid:{index}")
    optional_text_bounds = {"title": 160, "declared_summary": 1_024}
    for key, max_chars in optional_text_bounds.items():
        if key in source and not _is_bounded_text(source.get(key), max_chars=max_chars):
            blockers.append(f"source_{key}_invalid:{index}")
    if "heading_seeds" in source and not _is_bounded_string_list(
        source.get("heading_seeds"), max_items=8, max_chars=160
    ):
        blockers.append(f"source_heading_seeds_invalid:{index}")
    if "relationships" in source and not _is_bounded_string_list(
        source.get("relationships"), max_items=16
    ):
        blockers.append(f"source_relationships_invalid:{index}")
    if not _is_safe_relative_path(str(source.get("relative_path") or "")):
        blockers.append(f"source_relative_path_invalid:{index}")
    expected_extension = ALLOWED_MEDIA.get(str(source.get("media_type") or ""))
    if (
        expected_extension
        and PurePosixPath(str(source.get("relative_path") or "")).suffix.lower()
        != expected_extension
    ):
        blockers.append(f"source_extension_mismatch:{index}")
    for ref in (
        source.get("evidence_refs", [])
        if isinstance(source.get("evidence_refs"), list)
        else []
    ):
        if not _is_safe_relative_path(ref):
            blockers.append(f"source_evidence_ref_invalid:{index}")
    return blockers


def _validate_source_contract_refs(policy: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    classes = (
        policy.get("source_classes")
        if isinstance(policy.get("source_classes"), list)
        else []
    )
    topics = policy.get("topics") if isinstance(policy.get("topics"), list) else []
    sources = policy.get("sources") if isinstance(policy.get("sources"), list) else []
    class_keys = {
        "source_class_id",
        "description",
        "expected_member_count",
        "evidence_available",
        "required_true_predicates",
        "current_rights_status",
        "permitted_local_uses",
        "external_processing",
        "adjudication_reason",
    }
    topic_keys = {"topic_id", "description", "expected_member_count", "membership_rule"}
    class_ids = {
        str(row.get("source_class_id") or "")
        for row in classes
        if isinstance(row, Mapping)
    }
    topic_ids = {
        str(row.get("topic_id") or "") for row in topics if isinstance(row, Mapping)
    }
    if not class_ids or "" in class_ids:
        blockers.append("source_classes_invalid")
    if not topic_ids or "" in topic_ids:
        blockers.append("topics_invalid")
    if any(not isinstance(row, Mapping) or set(row) != class_keys for row in classes):
        blockers.append("source_class_keys_mismatch")
    if any(not isinstance(row, Mapping) or set(row) != topic_keys for row in topics):
        blockers.append("topic_keys_mismatch")
    media_by_class: dict[str, set[str]] = {}
    for source in sources:
        if isinstance(source, Mapping):
            media_by_class.setdefault(
                str(source.get("source_class_id") or ""), set()
            ).add(str(source.get("media_type") or ""))
    for index, row in enumerate(classes):
        if not isinstance(row, Mapping):
            continue
        class_id = str(row.get("source_class_id") or "")
        if not SAFE_ID_RE.fullmatch(class_id):
            blockers.append(f"source_class_id_unsafe:{index}")
        for key in ("description", "evidence_available", "adjudication_reason"):
            if not _is_bounded_text(row.get(key), max_chars=MAX_CURATED_TEXT_CHARS):
                blockers.append(f"source_class_{key}_invalid:{index}")
        required_predicates = row.get("required_true_predicates")
        if not _is_bounded_string_list(
            required_predicates, max_items=len(EVIDENCE_PREDICATE_KEYS)
        ):
            blockers.append(f"source_class_required_predicates_invalid:{index}")
        else:
            unknown = set(required_predicates) - EVIDENCE_PREDICATE_KEYS
            if unknown:
                blockers.append(f"source_class_unknown_predicate:{class_id}")
            if (
                "text/markdown" in media_by_class.get(class_id, set())
                and set(required_predicates) & VISUAL_EVIDENCE_PREDICATES
            ):
                blockers.append(f"source_class_visual_predicate_on_text:{class_id}")
        if not _is_bounded_string_list(
            row.get("permitted_local_uses"), max_items=MAX_CURATED_LIST_ITEMS
        ):
            blockers.append(f"source_class_permissions_invalid:{index}")
        if not isinstance(row.get("external_processing"), bool):
            blockers.append(f"source_class_external_processing_invalid:{index}")
        if row.get("current_rights_status") not in ALLOWED_RIGHTS_STATUSES:
            blockers.append(f"source_class_rights_status_invalid:{index}")
    for index, row in enumerate(topics):
        if not isinstance(row, Mapping):
            continue
        if not SAFE_ID_RE.fullmatch(str(row.get("topic_id") or "")):
            blockers.append(f"topic_id_unsafe:{index}")
        for key in ("description", "membership_rule"):
            if not _is_bounded_text(row.get(key), max_chars=MAX_CURATED_TEXT_CHARS):
                blockers.append(f"topic_{key}_invalid:{index}")
    seen_paths: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        relative_path = str(source.get("relative_path") or "")
        if relative_path in seen_paths:
            blockers.append(f"duplicate_policy_path:{stable_hash(relative_path)[:12]}")
        seen_paths.add(relative_path)
        if source.get("source_class_id") not in class_ids:
            blockers.append(f"unknown_source_class:{stable_hash(relative_path)[:12]}")
        if source.get("topic_id") not in topic_ids:
            blockers.append(f"unknown_topic:{stable_hash(relative_path)[:12]}")
    for row in classes:
        if not isinstance(row, Mapping):
            continue
        observed = sum(
            isinstance(source, Mapping)
            and source.get("source_class_id") == row.get("source_class_id")
            for source in sources
        )
        if observed != _safe_int(row.get("expected_member_count")):
            blockers.append(
                f"source_class_member_count_mismatch:{row.get('source_class_id')}"
            )
    for row in topics:
        if not isinstance(row, Mapping):
            continue
        observed = sum(
            isinstance(source, Mapping)
            and source.get("topic_id") == row.get("topic_id")
            for source in sources
        )
        if observed != _safe_int(row.get("expected_member_count")):
            blockers.append(f"topic_member_count_mismatch:{row.get('topic_id')}")
    return blockers


def _validate_source_root_contract(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["source_root_contract_invalid"]
    expected_keys = {
        "runtime_argument_required",
        "relative_path_base",
        "read_only",
        "persist_source_root",
        "allow_symlinks",
        "allow_unlisted_files",
        "allowed_extensions",
    }
    blockers: list[str] = []
    if set(value) != expected_keys:
        blockers.append("source_root_contract_keys_mismatch")
    expected_values = {
        "runtime_argument_required": True,
        "relative_path_base": "runtime_source_root",
        "read_only": True,
        "persist_source_root": False,
        "allow_symlinks": False,
        "allow_unlisted_files": False,
    }
    for key, expected in expected_values.items():
        if value.get(key) != expected:
            blockers.append(f"source_root_contract_{key}_mismatch")
    if value.get("allowed_extensions") != [".md", ".png"]:
        blockers.append("source_root_contract_extensions_mismatch")
    return blockers


def _validate_inventory_contract(policy: Mapping[str, Any]) -> list[str]:
    contract = (
        policy.get("inventory_contract")
        if isinstance(policy.get("inventory_contract"), Mapping)
        else {}
    )
    sources = policy.get("sources") if isinstance(policy.get("sources"), list) else []
    blockers: list[str] = []
    expected_keys = {
        "sort_key",
        "digest_input_format",
        "hash_algorithm",
        "expected_markdown_count",
        "expected_png_count",
        "expected_file_count",
        "expected_total_size_bytes",
        "audit_digest_sha256",
    }
    if set(contract) != expected_keys:
        blockers.append("inventory_contract_keys_mismatch")
    if contract.get("sort_key") != "relative_path":
        blockers.append("inventory_sort_key_invalid")
    if (
        contract.get("digest_input_format")
        != "relative_path<TAB>size_bytes<TAB>source_sha256<LF>"
    ):
        blockers.append("inventory_digest_input_format_invalid")
    if contract.get("hash_algorithm") != "sha256":
        blockers.append("inventory_hash_algorithm_invalid")
    expected_counts = {
        "expected_markdown_count": sum(
            isinstance(row, Mapping) and row.get("media_type") == "text/markdown"
            for row in sources
        ),
        "expected_png_count": sum(
            isinstance(row, Mapping) and row.get("media_type") == "image/png"
            for row in sources
        ),
        "expected_file_count": len(sources),
        "expected_total_size_bytes": sum(
            _safe_int(row.get("size_bytes"))
            for row in sources
            if isinstance(row, Mapping)
        ),
    }
    for key, value in expected_counts.items():
        if contract.get(key) != value:
            blockers.append(f"inventory_contract_{key}_mismatch")
    audit_digest = str(contract.get("audit_digest_sha256") or "")
    if not SHA256_RE.fullmatch(audit_digest):
        blockers.append("inventory_audit_digest_invalid")
    elif audit_digest != inventory_audit_digest(
        [row for row in sources if isinstance(row, Mapping)]
    ):
        blockers.append("inventory_audit_digest_mismatch")
    return blockers


def _validate_production_profile(profile: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if profile.get("schema_version") != PRODUCTION_PROFILE_SCHEMA_VERSION:
        blockers.append("production_profile_schema_mismatch")
    if profile.get("status") != "active":
        blockers.append("production_profile_not_active")
    ingestion = (
        profile.get("ingestion_policy")
        if isinstance(profile.get("ingestion_policy"), Mapping)
        else {}
    )
    expected = {
        "accepted_unit": "rights_safe_curated_card",
        "raw_book_markdown_allowed": False,
        "binary_media_in_lightrag_allowed": False,
        "direct_datastore_writes_allowed": False,
        "credentials_may_be_persisted_in_manifests": False,
    }
    for key, value in expected.items():
        if ingestion.get(key) != value:
            blockers.append(f"production_profile_ingestion_policy_mismatch:{key}")
    rollout = profile.get("rollout") if isinstance(profile.get("rollout"), list) else []
    stages = [
        row.get("stage")
        for row in sorted(
            (row for row in rollout if isinstance(row, Mapping)),
            key=lambda row: _safe_int(row.get("order")),
        )
    ]
    if stages != ROLLOUT_STAGES:
        blockers.append("production_profile_rollout_order_mismatch")
    if not _required_providers(profile):
        blockers.append("production_profile_provider_roles_missing")
    return blockers


def _validate_runtime_capabilities(
    capabilities: Mapping[str, Any],
    profile_sha256: str,
) -> list[str]:
    schema_version = capabilities.get("schema_version")
    if schema_version == RUNTIME_CAPABILITY_SCHEMA_VERSION:
        return _validate_runtime_capabilities_v1(capabilities, profile_sha256)
    if schema_version == RUNTIME_CAPABILITY_SCHEMA_VERSION_V2:
        blockers = list(
            runtime_evidence.validate_runtime_capability_evidence(capabilities)
        )
        observed_at = _parse_utc_timestamp(capabilities.get("observed_at"))
        if observed_at is not None:
            age = _utc_now() - observed_at
            if age > MAX_CAPABILITY_AGE or age < -MAX_CAPABILITY_FUTURE_SKEW:
                blockers.append("runtime_capabilities_observation_not_fresh")
        return _dedupe(blockers)
    return ["runtime_capabilities_schema_mismatch"]


def _validate_runtime_capabilities_v1(
    capabilities: Mapping[str, Any],
    profile_sha256: str,
) -> list[str]:
    blockers: list[str] = []
    if capabilities.get("schema_version") != RUNTIME_CAPABILITY_SCHEMA_VERSION:
        blockers.append("runtime_capabilities_schema_mismatch")
    if capabilities.get("evidence_mode") != "redacted_read_only":
        blockers.append("runtime_capabilities_evidence_mode_invalid")
    policy = (
        capabilities.get("policy")
        if isinstance(capabilities.get("policy"), Mapping)
        else {}
    )
    if (
        policy.get("live_mutation_attempted") is not False
        or policy.get("promotion_attempted") is not False
    ):
        blockers.append("runtime_capabilities_mutation_evidence_invalid")
    redaction = (
        capabilities.get("redaction_contract")
        if isinstance(capabilities.get("redaction_contract"), Mapping)
        else {}
    )
    if not redaction or any(value is not False for value in redaction.values()):
        blockers.append("runtime_capabilities_redaction_invalid")
    dependency = (
        capabilities.get("dependency_provenance")
        if isinstance(capabilities.get("dependency_provenance"), Mapping)
        else {}
    )
    repository_head = (
        dependency.get("repository_head")
        if isinstance(dependency.get("repository_head"), Mapping)
        else {}
    )
    if set(repository_head) != {"revision", "state"}:
        blockers.append("runtime_capabilities_repository_head_shape_invalid")
    if not GIT_REVISION_RE.fullmatch(str(repository_head.get("revision") or "")):
        blockers.append("runtime_capabilities_repository_revision_invalid")
    if repository_head.get("state") != "committed_head":
        blockers.append("runtime_capabilities_repository_state_invalid")
    profile_evidence = (
        dependency.get("production_profile")
        if isinstance(dependency.get("production_profile"), Mapping)
        else {}
    )
    if profile_evidence.get("sha256") != profile_sha256:
        blockers.append("runtime_capabilities_profile_hash_mismatch")
    if profile_evidence.get("verification") != "hash_match":
        blockers.append("runtime_capabilities_profile_unverified")
    decisions = (
        capabilities.get("gate_decisions")
        if isinstance(capabilities.get("gate_decisions"), Mapping)
        else {}
    )
    p0 = (
        decisions.get("p0_read_only")
        if isinstance(decisions.get("p0_read_only"), Mapping)
        else {}
    )
    if p0.get("decision") != "allowed" or p0.get("mutation_allowed") is not False:
        blockers.append("runtime_capabilities_p0_read_only_invalid")
    observed_at = _parse_utc_timestamp(capabilities.get("observed_at"))
    if observed_at is None:
        blockers.append("runtime_capabilities_observed_at_invalid")
    else:
        age = _utc_now() - observed_at
        if age > MAX_CAPABILITY_AGE or age < -MAX_CAPABILITY_FUTURE_SKEW:
            blockers.append("runtime_capabilities_observation_not_fresh")

    observations = capabilities.get("live_read_only_observations")
    if not isinstance(observations, Mapping):
        blockers.append("runtime_capabilities_observations_invalid")
        observations = {}
    capability_rows = (
        capabilities.get("capabilities")
        if isinstance(capabilities.get("capabilities"), list)
        else []
    )
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(capability_rows):
        if not isinstance(row, Mapping):
            blockers.append(f"runtime_capability_row_invalid:{index}")
            continue
        capability_id = str(row.get("capability_id") or "")
        if not SAFE_ID_RE.fullmatch(capability_id):
            blockers.append(f"runtime_capability_id_invalid:{index}")
            continue
        if capability_id in by_id:
            blockers.append(f"runtime_capability_duplicate_id:{capability_id}")
        else:
            by_id[capability_id] = row
        evidence_refs = row.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            blockers.append(f"runtime_capability_evidence_missing:{capability_id}")
            continue
        resolved_evidence: list[Mapping[str, Any]] = []
        for ref in evidence_refs:
            if not isinstance(ref, str) or not ref.startswith(
                "/live_read_only_observations/"
            ):
                blockers.append(
                    f"runtime_capability_evidence_ref_invalid:{capability_id}"
                )
                continue
            evidence = _resolve_json_pointer(capabilities, ref)
            if evidence is _MISSING:
                blockers.append(
                    f"runtime_capability_evidence_unresolved:{capability_id}"
                )
            elif isinstance(evidence, Mapping):
                resolved_evidence.append(evidence)
        expected_proof = REQUIRED_LIGHTRAG_CAPABILITY_PROOFS.get(capability_id)
        if row.get("status") == "available" and expected_proof is not None:
            if not any(
                all(
                    _json_values_exact(evidence.get(key), expected)
                    for key, expected in expected_proof.items()
                )
                for evidence in resolved_evidence
            ):
                blockers.append(
                    f"runtime_capability_evidence_shape_invalid:{capability_id}"
                )

    missing_or_unavailable = {
        capability_id
        for capability_id in REQUIRED_LIGHTRAG_CAPABILITIES
        if by_id.get(capability_id, {}).get("status") != "available"
    }
    for capability_id in REQUIRED_LIGHTRAG_CAPABILITIES - missing_or_unavailable:
        row = by_id[capability_id]
        if row.get("blocking") is not False or row.get("scope") != "lightrag_mutation":
            blockers.append(
                f"runtime_capability_available_row_inconsistent:{capability_id}"
            )
    lightrag_decision = (
        decisions.get("lightrag_mutation")
        if isinstance(decisions.get("lightrag_mutation"), Mapping)
        else {}
    )
    decision = lightrag_decision.get("decision")
    decision_blockers = (
        set(lightrag_decision.get("blockers", []))
        if isinstance(lightrag_decision.get("blockers"), list)
        else set()
    )
    if decision == "allowed":
        if missing_or_unavailable or decision_blockers:
            blockers.append("runtime_capabilities_lightrag_decision_inconsistent")
    elif decision == "blocked":
        if (
            not missing_or_unavailable
            or not missing_or_unavailable <= decision_blockers
        ):
            blockers.append("runtime_capabilities_lightrag_decision_inconsistent")
    else:
        blockers.append("runtime_capabilities_lightrag_decision_invalid")
    return blockers


def _validate_value_contract(value: Any, *, strict_v2: bool = False) -> list[str]:
    if not isinstance(value, Mapping):
        return ["value_contract_invalid"]
    blockers: list[str] = []
    expected_keys = {
        "contract_id",
        "status",
        "authored_from",
        "hypothesis",
        "operator_workflows",
        "baseline",
        "candidate",
        "candidate_evidence_ref",
        "candidate_evidence_sha256",
        "minimum_absolute_answer_pass_gain",
        "maximum_irrelevant_hit_rate_at_5",
        "maximum_incremental_eval_cost_usd",
        "mutation_gate_open",
    }
    if set(value) != expected_keys:
        blockers.append("value_contract_keys_mismatch")
    if not isinstance(value.get("operator_workflows"), list) or not value.get(
        "operator_workflows"
    ):
        blockers.append("value_contract_operator_workflows_missing")
    for key in ("baseline", "candidate"):
        if not isinstance(value.get(key), Mapping):
            blockers.append(f"value_contract_{key}_invalid")
    for key in (
        "minimum_absolute_answer_pass_gain",
        "maximum_irrelevant_hit_rate_at_5",
        "maximum_incremental_eval_cost_usd",
    ):
        if not _is_number(value.get(key)):
            blockers.append(f"value_contract_{key}_invalid")
    minimum_gain = value.get("minimum_absolute_answer_pass_gain")
    maximum_noise = value.get("maximum_irrelevant_hit_rate_at_5")
    maximum_cost = value.get("maximum_incremental_eval_cost_usd")
    if _is_number(minimum_gain) and not 0 <= float(minimum_gain) <= 1:
        blockers.append("value_contract_minimum_absolute_answer_pass_gain_invalid")
    if _is_number(maximum_noise) and not 0 <= float(maximum_noise) <= 1:
        blockers.append("value_contract_maximum_irrelevant_hit_rate_at_5_invalid")
    if _is_number(maximum_cost) and float(maximum_cost) < 0:
        blockers.append("value_contract_maximum_incremental_eval_cost_usd_invalid")
    if strict_v2 and (
        not _is_number(minimum_gain)
        or float(minimum_gain) < 0.8
        or maximum_noise != 0
        or maximum_cost != 0
    ):
        blockers.append("value_contract_v2_thresholds_weakened")
    if not isinstance(value.get("mutation_gate_open"), bool):
        blockers.append("value_contract_mutation_gate_invalid")
    baseline = (
        value.get("baseline") if isinstance(value.get("baseline"), Mapping) else {}
    )
    candidate = (
        value.get("candidate") if isinstance(value.get("candidate"), Mapping) else {}
    )
    metric_keys = {
        "routing_pass_count",
        "answer_criteria_pass_count",
        "negative_control_pass_count",
        "irrelevant_hit_rate_at_5",
        "estimated_cost_usd",
    }
    baseline_keys = {"snapshot_id", "captured_at", *metric_keys}
    candidate_base_keys = {"certificate_id", "evaluated_at", *metric_keys}
    safety_metric_keys = {
        "unsupported_current_claims",
        "raw_source_body_leaks",
        "invented_evidence_claims",
    }
    if set(baseline) != baseline_keys:
        blockers.append("value_contract_baseline_keys_mismatch")
    if (
        not candidate_base_keys <= set(candidate)
        or set(candidate) - candidate_base_keys - safety_metric_keys
    ):
        blockers.append("value_contract_candidate_keys_mismatch")
    evidence_ref = value.get("candidate_evidence_ref")
    evidence_sha256 = value.get("candidate_evidence_sha256")
    if (evidence_ref is None) != (evidence_sha256 is None):
        blockers.append("value_contract_candidate_evidence_pair_incomplete")
    if evidence_ref is not None and not _is_safe_relative_path(evidence_ref):
        blockers.append("value_contract_candidate_evidence_ref_invalid")
    if evidence_sha256 is not None and not SHA256_RE.fullmatch(str(evidence_sha256)):
        blockers.append("value_contract_candidate_evidence_sha256_invalid")
    if value.get("status") == "frozen_green":
        if evidence_ref is None or evidence_sha256 is None:
            blockers.append("value_contract_green_candidate_evidence_missing")
        if set(candidate) != candidate_base_keys | safety_metric_keys:
            blockers.append("value_contract_green_candidate_evidence_incomplete")
        if (
            not baseline.get("snapshot_id")
            or _parse_utc_timestamp(baseline.get("captured_at")) is None
        ):
            blockers.append("value_contract_green_baseline_identity_invalid")
        if (
            not candidate.get("certificate_id")
            or _parse_utc_timestamp(candidate.get("evaluated_at")) is None
        ):
            blockers.append("value_contract_green_candidate_identity_invalid")
        for key in metric_keys:
            if not _is_number(baseline.get(key)) or not _is_number(candidate.get(key)):
                blockers.append(f"value_contract_green_metric_invalid:{key}")
        for key in safety_metric_keys:
            if (
                not isinstance(candidate.get(key), int)
                or isinstance(candidate.get(key), bool)
                or candidate.get(key) < 0
            ):
                blockers.append(f"value_contract_green_safety_metric_invalid:{key}")
    return blockers


def _validate_value_evidence(
    policy: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    *,
    policy_manifest_parent: Path,
    profile_hash: str,
    capabilities_hash: str,
    holdout_hash: str,
) -> list[str]:
    value = (
        policy.get("value_contract")
        if isinstance(policy.get("value_contract"), Mapping)
        else {}
    )
    evidence_ref = value.get("candidate_evidence_ref")
    evidence_sha256 = value.get("candidate_evidence_sha256")
    if (
        value.get("status") != "frozen_green"
        and evidence_ref is None
        and evidence_sha256 is None
    ):
        return []

    certificate, blockers = _load_hash_bound_json_snapshot(
        policy_manifest_parent,
        evidence_ref,
        evidence_sha256,
        blocker_prefix="value_evidence",
    )
    if certificate is None:
        return _dedupe(blockers)

    certificate_keys = {
        "schema_version",
        "certificate_id",
        "evaluated_at",
        "evaluated_repository_revision",
        "corpus_digest_sha256",
        "holdout_sha256",
        "production_profile_sha256",
        "runtime_capabilities_sha256",
        "candidate_metrics",
        "artifact_manifest_ref",
        "artifact_manifest_sha256",
    }
    if (
        set(certificate) != certificate_keys
        or certificate.get("schema_version") != VALUE_EVIDENCE_SCHEMA_VERSION
    ):
        blockers.append("value_evidence_schema_mismatch")
        return _dedupe(blockers)

    candidate = (
        value.get("candidate") if isinstance(value.get("candidate"), Mapping) else {}
    )
    candidate_metrics = certificate.get("candidate_metrics")
    expected_metrics = {key: candidate.get(key) for key in VALUE_CANDIDATE_METRIC_KEYS}
    if (
        not isinstance(candidate_metrics, Mapping)
        or set(candidate_metrics) != VALUE_CANDIDATE_METRIC_KEYS
    ):
        blockers.append("value_evidence_candidate_metrics_schema_mismatch")
    elif not _json_values_exact(candidate_metrics, expected_metrics):
        blockers.append("value_evidence_candidate_metrics_mismatch")

    if capabilities.get("schema_version") == RUNTIME_CAPABILITY_SCHEMA_VERSION_V2:
        subject = (
            capabilities.get("subject")
            if isinstance(capabilities.get("subject"), Mapping)
            else {}
        )
        repository_revision = str(subject.get("revision") or "")
    else:
        dependency = (
            capabilities.get("dependency_provenance")
            if isinstance(capabilities.get("dependency_provenance"), Mapping)
            else {}
        )
        repository_head = (
            dependency.get("repository_head")
            if isinstance(dependency.get("repository_head"), Mapping)
            else {}
        )
        repository_revision = str(repository_head.get("revision") or "")
    inventory_contract = (
        policy.get("inventory_contract")
        if isinstance(policy.get("inventory_contract"), Mapping)
        else {}
    )
    expected_bindings = {
        "certificate_id": candidate.get("certificate_id"),
        "evaluated_at": candidate.get("evaluated_at"),
        "evaluated_repository_revision": repository_revision,
        "corpus_digest_sha256": inventory_contract.get("audit_digest_sha256"),
        "holdout_sha256": holdout_hash,
        "production_profile_sha256": profile_hash,
        "runtime_capabilities_sha256": capabilities_hash,
    }
    for key, expected in expected_bindings.items():
        if certificate.get(key) != expected:
            blockers.append(f"value_evidence_binding_mismatch:{key}")

    artifact_manifest, manifest_path_blockers = _load_hash_bound_json_snapshot(
        policy_manifest_parent,
        certificate.get("artifact_manifest_ref"),
        certificate.get("artifact_manifest_sha256"),
        blocker_prefix="value_artifact_manifest",
    )
    blockers.extend(manifest_path_blockers)
    if artifact_manifest is None:
        return _dedupe(blockers)
    if (
        set(artifact_manifest) != {"schema_version", "artifacts"}
        or artifact_manifest.get("schema_version")
        != VALUE_ARTIFACT_MANIFEST_SCHEMA_VERSION
    ):
        blockers.append("value_artifact_manifest_schema_mismatch")
        return _dedupe(blockers)

    artifacts = artifact_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        blockers.append("value_artifact_manifest_artifacts_invalid")
        return _dedupe(blockers)
    strict_v2 = policy.get("schema_version") == POLICY_SCHEMA_VERSION_V2
    if strict_v2 and len(artifacts) != 1:
        blockers.append("value_artifact_manifest_v2_membership_mismatch")
    seen_refs: set[str] = set()
    preflight: Mapping[str, Any] | None = None
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "artifact_ref",
            "sha256",
        }:
            blockers.append(f"value_artifact_manifest_row_invalid:{index}")
            continue
        artifact_ref = artifact.get("artifact_ref")
        if isinstance(artifact_ref, str) and artifact_ref in seen_refs:
            blockers.append("value_artifact_manifest_duplicate_ref")
            continue
        if isinstance(artifact_ref, str):
            seen_refs.add(artifact_ref)
        if strict_v2:
            artifact_payload, artifact_blockers = _load_hash_bound_json_snapshot(
                policy_manifest_parent,
                artifact_ref,
                artifact.get("sha256"),
                blocker_prefix="value_artifact",
            )
            if (
                not isinstance(artifact_ref, str)
                or PurePosixPath(artifact_ref).name != "value-preflight.json"
            ):
                blockers.append("value_artifact_v2_ref_mismatch")
            if preflight is None and artifact_payload is not None:
                preflight = artifact_payload
        else:
            _artifact_path, artifact_blockers = _hash_bound_snapshot_path(
                policy_manifest_parent,
                artifact_ref,
                artifact.get("sha256"),
                blocker_prefix="value_artifact",
            )
        blockers.extend(artifact_blockers)
    if strict_v2 and preflight is not None:
        blockers.extend(
            _validate_v2_value_preflight(
                preflight,
                policy=policy,
                certificate=certificate,
            )
        )
    return _dedupe(blockers)


def _validate_v2_value_preflight(
    preflight: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    certificate: Mapping[str, Any],
) -> list[str]:
    """Validate the fixed, read-only HyperFrames Phase-0 value observation."""

    blockers: list[str] = []
    expected_keys = {
        "schema_version",
        "captured_at",
        "collection_mode",
        "dashboard_stats",
        "frontend_head_status",
        "baseline_queries",
        "candidate_evaluation",
        "provider_calls",
        "source_bodies_persisted",
    }
    if set(preflight) != expected_keys:
        blockers.append("value_preflight_keys_mismatch")
    if preflight.get("schema_version") != HYPERFRAMES_VALUE_PREFLIGHT_SCHEMA_VERSION:
        blockers.append("value_preflight_schema_mismatch")
    if (
        preflight.get("collection_mode")
        != "read_only_local_search_and_curated_metadata_coverage"
    ):
        blockers.append("value_preflight_collection_mode_mismatch")
    if not _json_values_exact(
        preflight.get("dashboard_stats"), HYPERFRAMES_VALUE_PREFLIGHT_STATS
    ):
        blockers.append("value_preflight_dashboard_stats_mismatch")
    if not _json_values_exact(preflight.get("frontend_head_status"), 200):
        blockers.append("value_preflight_frontend_status_mismatch")
    if not _json_values_exact(preflight.get("provider_calls"), 0):
        blockers.append("value_preflight_provider_calls_nonzero")
    if preflight.get("source_bodies_persisted") is not False:
        blockers.append("value_preflight_source_bodies_persisted")

    value = (
        policy.get("value_contract")
        if isinstance(policy.get("value_contract"), Mapping)
        else {}
    )
    baseline = (
        value.get("baseline") if isinstance(value.get("baseline"), Mapping) else {}
    )
    candidate = (
        value.get("candidate") if isinstance(value.get("candidate"), Mapping) else {}
    )
    captured_at = preflight.get("captured_at")
    if (
        _parse_utc_timestamp(captured_at) is None
        or captured_at != baseline.get("captured_at")
        or captured_at != candidate.get("evaluated_at")
        or captured_at != certificate.get("evaluated_at")
    ):
        blockers.append("value_preflight_timestamp_binding_mismatch")
    expected_baseline_metrics = {
        "routing_pass_count": 0,
        "answer_criteria_pass_count": 0,
        "negative_control_pass_count": 0,
        "irrelevant_hit_rate_at_5": 0.0,
        "estimated_cost_usd": 0.0,
    }
    if not all(
        _json_values_exact(baseline.get(key), expected)
        for key, expected in expected_baseline_metrics.items()
    ):
        blockers.append("value_preflight_policy_baseline_mismatch")

    baseline_queries = preflight.get("baseline_queries")
    query_rows: dict[str, Mapping[str, Any]] = {}
    expected_query_keys = {
        "query_id",
        "request_sha256",
        "response_sha256",
        "result_count",
        "local_metadata_covers_need",
    }
    if not isinstance(baseline_queries, list) or len(baseline_queries) != len(
        HYPERFRAMES_VALUE_PREFLIGHT_QUERY_HASHES
    ):
        blockers.append("value_preflight_baseline_queries_membership_mismatch")
    else:
        for index, row in enumerate(baseline_queries):
            if not isinstance(row, Mapping) or set(row) != expected_query_keys:
                blockers.append(f"value_preflight_baseline_query_invalid:{index}")
                continue
            query_id = row.get("query_id")
            if not isinstance(query_id, str) or query_id in query_rows:
                blockers.append("value_preflight_baseline_query_id_invalid")
                continue
            query_rows[query_id] = row
        if set(query_rows) != set(HYPERFRAMES_VALUE_PREFLIGHT_QUERY_HASHES):
            blockers.append("value_preflight_baseline_queries_membership_mismatch")
        for query_id, request_sha256 in HYPERFRAMES_VALUE_PREFLIGHT_QUERY_HASHES.items():
            row = query_rows.get(query_id)
            if row is None:
                continue
            expected_row = {
                "query_id": query_id,
                "request_sha256": request_sha256,
                "response_sha256": HYPERFRAMES_VALUE_PREFLIGHT_EMPTY_RESPONSE_SHA256,
                "result_count": 0,
                "local_metadata_covers_need": True,
            }
            if not _json_values_exact(row, expected_row):
                blockers.append(f"value_preflight_baseline_query_mismatch:{query_id}")

    evaluation = (
        preflight.get("candidate_evaluation")
        if isinstance(preflight.get("candidate_evaluation"), Mapping)
        else {}
    )
    evaluation_metric_keys = {
        "routing_pass_count",
        "answer_criteria_pass_count",
        "negative_control_pass_count",
        "unsupported_current_claims",
        "raw_source_body_leaks",
        "invented_evidence_claims",
    }
    expected_evaluation_keys = {"method", "holdout_ids", *evaluation_metric_keys}
    if set(evaluation) != expected_evaluation_keys:
        blockers.append("value_preflight_candidate_evaluation_schema_mismatch")
    if evaluation.get("method") != "deterministic_curated_metadata_routing":
        blockers.append("value_preflight_candidate_method_mismatch")

    holdout = (
        policy.get("holdout_contract")
        if isinstance(policy.get("holdout_contract"), Mapping)
        else {}
    )
    queries = holdout.get("queries") if isinstance(holdout.get("queries"), list) else []
    holdout_ids = [
        str(query.get("holdout_id") or "")
        for query in queries
        if isinstance(query, Mapping)
    ]
    if not _json_values_exact(evaluation.get("holdout_ids"), holdout_ids):
        blockers.append("value_preflight_holdout_membership_mismatch")

    certificate_metrics = (
        certificate.get("candidate_metrics")
        if isinstance(certificate.get("candidate_metrics"), Mapping)
        else {}
    )
    for key in evaluation_metric_keys:
        if (
            not _json_values_exact(evaluation.get(key), candidate.get(key))
            or not _json_values_exact(evaluation.get(key), certificate_metrics.get(key))
        ):
            blockers.append(f"value_preflight_candidate_metric_mismatch:{key}")
    if (
        not _json_values_exact(certificate_metrics.get("irrelevant_hit_rate_at_5"), 0.0)
        or not _json_values_exact(certificate_metrics.get("estimated_cost_usd"), 0.0)
    ):
        blockers.append("value_preflight_candidate_cost_or_noise_nonzero")

    thresholds = (
        holdout.get("thresholds")
        if isinstance(holdout.get("thresholds"), Mapping)
        else {}
    )
    threshold_bindings = {
        "topic_routing_pass_count_min": "routing_pass_count",
        "answer_criteria_pass_count_min": "answer_criteria_pass_count",
        "negative_control_pass_count_min": "negative_control_pass_count",
        "unsupported_current_claims_max": "unsupported_current_claims",
        "raw_source_body_leaks_max": "raw_source_body_leaks",
        "invented_evidence_claims_max": "invented_evidence_claims",
    }
    if not all(
        _json_values_exact(thresholds.get(threshold_key), evaluation.get(metric_key))
        for threshold_key, metric_key in threshold_bindings.items()
    ):
        blockers.append("value_preflight_holdout_threshold_binding_mismatch")
    return _dedupe(blockers)


def _hash_bound_snapshot_path(
    base_dir: Path,
    relative_ref: Any,
    expected_sha256: Any,
    *,
    blocker_prefix: str,
) -> tuple[Path | None, list[str]]:
    if not _is_safe_relative_path(relative_ref):
        return None, [f"{blocker_prefix}_ref_invalid"]
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
        return None, [f"{blocker_prefix}_sha256_invalid"]
    snapshot, blockers = authority_evidence.snapshot_anchored_file(
        base_dir,
        str(relative_ref),
        blocker_prefix=blocker_prefix,
        max_bytes=2 * 1024 * 1024,
    )
    if snapshot is None:
        return None, blockers
    if snapshot.sha256 != expected_sha256:
        return None, [f"{blocker_prefix}_hash_mismatch"]
    return base_dir / PurePosixPath(str(relative_ref)), []


def _load_hash_bound_json_snapshot(
    base_dir: Path,
    relative_ref: Any,
    expected_sha256: Any,
    *,
    blocker_prefix: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not _is_safe_relative_path(relative_ref):
        return None, [f"{blocker_prefix}_ref_invalid"]
    if PurePosixPath(str(relative_ref)).suffix != ".json":
        return None, [f"{blocker_prefix}_json_ref_required"]
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
        return None, [f"{blocker_prefix}_sha256_invalid"]
    snapshot, blockers = authority_evidence.snapshot_anchored_file(
        base_dir,
        str(relative_ref),
        blocker_prefix=blocker_prefix,
        max_bytes=2 * 1024 * 1024,
    )
    if snapshot is None:
        return None, blockers
    if snapshot.sha256 != expected_sha256:
        return None, [f"{blocker_prefix}_hash_mismatch"]
    try:
        payload = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [f"{blocker_prefix}_json_invalid"]
    if not isinstance(payload, dict):
        return None, [f"{blocker_prefix}_not_object"]
    return payload, []


def _json_values_exact(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(
            _json_values_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_values_exact(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _validate_budget_contract(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["budget_contract_invalid"]
    blockers: list[str] = []
    expected_keys = {
        "contract_id",
        "status",
        "activation_allowed",
        "blocked_by",
        "currency",
        "corpus_digest_sha256",
        "operator_instruction_hash",
        "issued_at",
        "expires_at",
        "provider_roles",
        "total_ceiling",
        "reservation_status",
        "source_derived_fields",
        "external_processing",
        "reactivation_requirements",
    }
    if set(value) != expected_keys:
        blockers.append("budget_contract_keys_mismatch")
    if not value.get("currency") or not SHA256_RE.fullmatch(
        str(value.get("corpus_digest_sha256") or "")
    ):
        blockers.append("budget_contract_identity_invalid")
    if not isinstance(value.get("activation_allowed"), bool) or not isinstance(
        value.get("external_processing"), bool
    ):
        blockers.append("budget_contract_activation_invalid")
    if (
        not _is_number(value.get("total_ceiling"))
        or float(value.get("total_ceiling") or 0) < 0
    ):
        blockers.append("budget_contract_total_ceiling_invalid")
    provider_roles = (
        value.get("provider_roles")
        if isinstance(value.get("provider_roles"), list)
        else []
    )
    provider_role_keys = {
        "role",
        "provider",
        "model",
        "rate_basis_status",
        "rate_unit",
        "rate_amount",
        "max_calls",
        "max_input_tokens",
        "max_output_tokens",
    }
    if not provider_roles or any(
        not isinstance(row, Mapping) or set(row) != provider_role_keys
        for row in provider_roles
    ):
        blockers.append("budget_contract_provider_roles_invalid")
    if not _is_bounded_string_list(
        value.get("blocked_by"), max_items=MAX_CURATED_LIST_ITEMS
    ):
        blockers.append("budget_contract_blocked_by_invalid")
    if not _is_bounded_string_list(
        value.get("source_derived_fields"), max_items=MAX_CURATED_LIST_ITEMS
    ):
        blockers.append("budget_contract_source_derived_fields_invalid")
    if not _is_bounded_string_list(
        value.get("reactivation_requirements"), max_items=MAX_CURATED_LIST_ITEMS
    ):
        blockers.append("budget_contract_reactivation_requirements_invalid")
    for key in ("issued_at", "expires_at"):
        if value.get(key) is not None and _parse_utc_timestamp(value.get(key)) is None:
            blockers.append(f"budget_contract_{key}_invalid")
    active = (
        value.get("status") == "active_reserved"
        or value.get("activation_allowed") is True
    )
    if active:
        if value.get("blocked_by") or value.get("reactivation_requirements"):
            blockers.append("budget_contract_active_has_unresolved_blockers")
        if float(value.get("total_ceiling") or 0) <= 0:
            blockers.append("budget_contract_total_ceiling_not_positive")
        if not SHA256_RE.fullmatch(str(value.get("operator_instruction_hash") or "")):
            blockers.append("budget_contract_operator_instruction_hash_invalid")
        seen_roles: set[str] = set()
        for row in provider_roles:
            if not isinstance(row, Mapping):
                continue
            role = str(row.get("role") or "")
            if role in seen_roles:
                blockers.append(f"budget_contract_duplicate_provider_role:{role}")
            seen_roles.add(role)
            if (
                row.get("rate_basis_status") != "materialized"
                or not row.get("rate_unit")
                or not _is_number(row.get("rate_amount"))
                or float(row.get("rate_amount") or 0) <= 0
                or _safe_int(row.get("max_calls")) <= 0
                or _safe_int(row.get("max_input_tokens")) <= 0
                or _safe_int(row.get("max_output_tokens")) <= 0
            ):
                blockers.append(
                    f"budget_contract_provider_role_not_materialized:{role or 'unknown'}"
                )
    return blockers


def _validate_policy_capabilities(
    value: Any, *, schema_version: Any = POLICY_SCHEMA_VERSION
) -> list[str]:
    if not isinstance(value, Mapping):
        return ["capability_contract_invalid"]
    blockers: list[str] = []
    lightrag = (
        value.get("lightrag") if isinstance(value.get("lightrag"), Mapping) else {}
    )
    if set(value) != {"audit_mode", "lightrag", "knowledge_hub"}:
        blockers.append("capability_contract_keys_mismatch")
    required = (
        set(lightrag.get("required_capabilities", []))
        if isinstance(lightrag.get("required_capabilities"), list)
        else set()
    )
    if schema_version == POLICY_SCHEMA_VERSION_V2:
        if required != POLICY_REQUIRED_LIGHTRAG_CAPABILITIES_V2:
            blockers.append("capability_contract_lightrag_requirements_mismatch")
        knowledge_hub = (
            value.get("knowledge_hub")
            if isinstance(value.get("knowledge_hub"), Mapping)
            else {}
        )
        kh_required = (
            set(knowledge_hub.get("required_capabilities", []))
            if isinstance(knowledge_hub.get("required_capabilities"), list)
            else set()
        )
        if kh_required != POLICY_REQUIRED_KH_CAPABILITIES_V2:
            blockers.append("capability_contract_knowledge_hub_requirements_mismatch")
    elif required != POLICY_REQUIRED_LIGHTRAG_CAPABILITIES:
        blockers.append("capability_contract_lightrag_requirements_mismatch")
    return blockers


def _validate_audit_contract(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["audit_contract_invalid"]
    blockers: list[str] = []
    expected_keys = {
        "mode",
        "provider_calls",
        "source_writes",
        "datastore_writes",
        "inventory_verified",
        "rights_certification",
        "legacy_reconciliation",
        "leak_scan",
        "p0_status",
        "p1_status",
    }
    if set(value) != expected_keys:
        blockers.append("audit_contract_keys_mismatch")
    if value.get("mode") != "read_only":
        blockers.append("audit_contract_not_read_only")
    for key in ("provider_calls", "source_writes", "datastore_writes"):
        if value.get(key) != 0:
            blockers.append(f"audit_contract_{key}_nonzero")
    if not isinstance(value.get("inventory_verified"), bool):
        blockers.append("audit_contract_inventory_verified_invalid")
    for key in (
        "rights_certification",
        "legacy_reconciliation",
        "leak_scan",
        "p0_status",
        "p1_status",
    ):
        if not isinstance(value.get(key), str) or not value.get(key):
            blockers.append(f"audit_contract_{key}_invalid")
    return blockers


def _validate_stage_contract(
    value: Any,
    *,
    schema_version: Any = POLICY_SCHEMA_VERSION,
    declared_source_paths: set[str] | None = None,
    source_topics: Mapping[str, str] | None = None,
) -> list[str]:
    if not isinstance(value, Mapping):
        return ["stage_contract_invalid"]
    blockers: list[str] = []
    if set(value) != {"gate_1", "gate_2", "gate_3", "full_apply"}:
        blockers.append("stage_contract_keys_mismatch")
    gate_1 = value.get("gate_1") if isinstance(value.get("gate_1"), Mapping) else {}
    gate_2 = value.get("gate_2") if isinstance(value.get("gate_2"), Mapping) else {}
    gate_3 = value.get("gate_3") if isinstance(value.get("gate_3"), Mapping) else {}
    full = (
        value.get("full_apply") if isinstance(value.get("full_apply"), Mapping) else {}
    )
    if (
        gate_1.get("required_card_role") != "source_card"
        or gate_1.get("cumulative_unique_source_count") != 1
        or not _is_bounded_text(
            gate_1.get("selection_rule"), max_chars=MAX_CURATED_TEXT_CHARS
        )
    ):
        blockers.append("stage_contract_gate_1_invalid")
    if (
        gate_2.get("cumulative_unique_source_count") != 5
        or gate_2.get("required_new_unique_source_count") != 4
        or not _is_bounded_text(
            gate_2.get("selection_rule"), max_chars=MAX_CURATED_TEXT_CHARS
        )
    ):
        blockers.append("stage_contract_gate_2_invalid")
    if (
        not SAFE_ID_RE.fullmatch(str(gate_3.get("topic_id") or ""))
        or not isinstance(gate_3.get("minimum_new_sources"), int)
        or isinstance(gate_3.get("minimum_new_sources"), bool)
        or gate_3.get("minimum_new_sources", 0) <= 0
        or not isinstance(gate_3.get("minimum_relationship_patterns"), int)
        or isinstance(gate_3.get("minimum_relationship_patterns"), bool)
        or gate_3.get("minimum_relationship_patterns", 0) <= 0
        or gate_3.get("existing_members_are_noop") is not True
    ):
        blockers.append("stage_contract_gate_3_invalid")
    if any(
        full.get(key) is not True
        for key in (
            "requires_independent_holdout",
            "requires_fresh_rehearsed_checkpoint",
            "requires_zero_unresolved_conflicts_in_eligible_set",
        )
    ):
        blockers.append("stage_contract_full_apply_invalid")
    if schema_version == POLICY_SCHEMA_VERSION_V2:
        expected_keys = {
            "gate_1": {
                "required_card_role",
                "cumulative_unique_source_count",
                "selection_rule",
                "source_paths",
            },
            "gate_2": {
                "cumulative_unique_source_count",
                "required_new_unique_source_count",
                "selection_rule",
                "source_paths",
            },
            "gate_3": {
                "topic_id",
                "minimum_new_sources",
                "minimum_relationship_patterns",
                "existing_members_are_noop",
                "source_paths",
            },
            "full_apply": {
                "requires_independent_holdout",
                "requires_fresh_rehearsed_checkpoint",
                "requires_zero_unresolved_conflicts_in_eligible_set",
                "remaining_source_paths",
            },
        }
        for key, keys in expected_keys.items():
            row = value.get(key) if isinstance(value.get(key), Mapping) else {}
            if set(row) != keys:
                blockers.append(f"stage_contract_{key}_keys_mismatch")
        blockers.extend(
            _validate_exact_stage_paths(value, declared_source_paths or set())
        )
        cluster_paths = (
            gate_3.get("source_paths")
            if isinstance(gate_3.get("source_paths"), list)
            else []
        )
        topic_id = str(gate_3.get("topic_id") or "")
        if not isinstance(source_topics, Mapping) or not cluster_paths:
            blockers.append("stage_contract_gate_3_topic_membership_unavailable")
        elif topic_id not in set(source_topics.values()) or any(
            source_topics.get(str(path)) != topic_id for path in cluster_paths
        ):
            blockers.append("stage_contract_gate_3_topic_membership_mismatch")
    return blockers


def _validate_exact_stage_paths(
    value: Mapping[str, Any], declared_source_paths: set[str]
) -> list[str]:
    blockers: list[str] = []

    def paths(key: str, field: str) -> list[str]:
        row = value.get(key) if isinstance(value.get(key), Mapping) else {}
        raw = row.get(field)
        if not _is_bounded_string_list(raw, max_items=MAX_CURATED_LIST_ITEMS):
            blockers.append(f"stage_contract_{key}_{field}_invalid")
            return []
        result = [str(item) for item in raw]
        if len(result) != len(set(result)) or any(
            not _is_safe_relative_path(item) for item in result
        ):
            blockers.append(f"stage_contract_{key}_{field}_invalid")
        return result

    gate_one = paths("gate_1", "source_paths")
    gate_five = paths("gate_2", "source_paths")
    cluster = paths("gate_3", "source_paths")
    remaining = paths("full_apply", "remaining_source_paths")
    if len(gate_one) != 1:
        blockers.append("stage_contract_gate_1_exact_membership_invalid")
    if len(gate_five) != 5 or not set(gate_one) <= set(gate_five):
        blockers.append("stage_contract_gate_2_exact_membership_invalid")
    minimum_new = _safe_int(
        value.get("gate_3", {}).get("minimum_new_sources")
        if isinstance(value.get("gate_3"), Mapping)
        else 0
    )
    if not cluster or len(set(cluster) - set(gate_five)) < minimum_new:
        blockers.append("stage_contract_gate_3_exact_membership_invalid")
    selected = set(gate_five) | set(cluster)
    if not remaining or set(remaining) & selected:
        blockers.append("stage_contract_full_apply_exact_membership_invalid")
    if declared_source_paths and selected | set(remaining) != declared_source_paths:
        blockers.append("stage_contract_source_coverage_mismatch")
    return _dedupe(blockers)


def _validate_holdout(holdout: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    expected_keys = {
        "contract_id",
        "authored_from",
        "frozen_before_card_generation",
        "generated_card_content_allowed",
        "query_count",
        "negative_control_ids",
        "thresholds",
        "queries",
        "digest_algorithm",
        "digest_scope",
        "contract_sha256",
    }
    if set(holdout) != expected_keys:
        blockers.append("holdout_contract_keys_mismatch")
    if holdout.get("frozen_before_card_generation") is not True:
        blockers.append("holdout_not_independent")
    if holdout.get("generated_card_content_allowed") is not False:
        blockers.append("holdout_generated_card_content_allowed")
    if (
        holdout.get("digest_algorithm") != "sha256"
        or holdout.get("digest_scope") != "canonical_json_of_thresholds_and_queries"
    ):
        blockers.append("holdout_digest_contract_invalid")
    queries = holdout.get("queries") if isinstance(holdout.get("queries"), list) else []
    if not queries:
        blockers.append("holdout_queries_missing")
    if (
        not isinstance(holdout.get("query_count"), int)
        or isinstance(holdout.get("query_count"), bool)
        or holdout.get("query_count") != len(queries)
    ):
        blockers.append("holdout_query_count_mismatch")
    observed_negative_ids: list[str] = []
    for index, query in enumerate(queries):
        required = {
            "holdout_id",
            "query",
            "expected_topic_ids",
            "answer_criteria",
            "negative_control",
        }
        if not isinstance(query, Mapping) or set(query) != required:
            blockers.append(f"holdout_query_invalid:{index}")
            continue
        if not _is_bounded_text(
            query.get("holdout_id"), max_chars=MAX_CURATED_LIST_ITEM_CHARS
        ) or not _is_bounded_text(
            query.get("query"), max_chars=MAX_CURATED_TEXT_CHARS
        ):
            blockers.append(f"holdout_query_identity_invalid:{index}")
        if not _is_bounded_string_list(
            query.get("expected_topic_ids"), max_items=MAX_CURATED_LIST_ITEMS
        ) or not _is_bounded_string_list(
            query.get("answer_criteria"), max_items=MAX_CURATED_LIST_ITEMS
        ):
            blockers.append(f"holdout_query_contract_invalid:{index}")
        if not isinstance(query.get("negative_control"), bool):
            blockers.append(f"holdout_query_negative_control_invalid:{index}")
        elif query.get("negative_control") is True:
            observed_negative_ids.append(str(query.get("holdout_id") or ""))
    negative_control_ids = holdout.get("negative_control_ids")
    if (
        not _is_bounded_string_list(
            negative_control_ids,
            max_items=MAX_CURATED_LIST_ITEMS,
        )
        or len(negative_control_ids) != len(set(negative_control_ids))
        or list(negative_control_ids) != observed_negative_ids
    ):
        blockers.append("holdout_negative_control_ids_invalid")
    thresholds = (
        holdout.get("thresholds")
        if isinstance(holdout.get("thresholds"), Mapping)
        else {}
    )
    if set(thresholds) != HOLDOUT_THRESHOLD_KEYS:
        blockers.append("holdout_thresholds_schema_invalid")
    if any(
        not isinstance(thresholds.get(key), int)
        or isinstance(thresholds.get(key), bool)
        or thresholds.get(key, -1) < 0
        for key in HOLDOUT_THRESHOLD_KEYS
    ):
        blockers.append("holdout_thresholds_value_invalid")
    elif (
        thresholds["topic_routing_pass_count_min"] != len(queries)
        or thresholds["answer_criteria_pass_count_min"] != len(queries)
        or thresholds["negative_control_pass_count_min"]
        != len(observed_negative_ids)
        or any(
            thresholds[key] != 0
            for key in (
                "unsupported_current_claims_max",
                "raw_source_body_leaks_max",
                "invented_evidence_claims_max",
            )
        )
    ):
        blockers.append("holdout_thresholds_weakened")
    forbidden_keys = {
        "card_id",
        "payload_hash",
        "graph_document_id",
        "generated_answer",
        "expected_answer",
    }
    if _mapping_contains_keys(holdout, forbidden_keys):
        blockers.append("holdout_depends_on_generated_artifacts")
    return blockers


def _holdout_digest(holdout: Mapping[str, Any]) -> str:
    payload = {
        "queries": holdout.get("queries", []),
        "thresholds": holdout.get("thresholds", {}),
    }
    canonical = (
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def holdout_digest(holdout: Mapping[str, Any]) -> str:
    """Public helper used by policy authors and deterministic fixtures."""
    return _holdout_digest(holdout)


def run_all(config: GovernedCorpusConfig) -> dict[str, Any]:
    """Build one immutable P0 planning run without external side effects."""
    if config.apply:
        raise ValueError("apply_mode_not_implemented_for_governed_corpus_rollout")
    _prepare_run_directory(config)

    contracts, contract_blockers, input_leaks = _load_contracts(config)
    phases: list[PhaseResult] = []
    inventory: list[dict[str, Any]] = []
    rights_registry: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    visual_queue: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    kh_plan: list[dict[str, Any]] = []
    lightrag_plan: list[dict[str, Any]] = []
    crosswalk: list[dict[str, Any]] = []
    cag_manifest: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    cag_candidates: list[dict[str, Any]] = []
    eval_suite: list[dict[str, Any]] = []
    certification_blockers: list[str] = []
    independent_gate_blockers: dict[str, list[str]] | None = None

    if contracts is None:
        contracts_unavailable = "contracts_unavailable"
        unavailable_gate_vector = {
            "inventory": [contracts_unavailable],
            "rights": [contracts_unavailable],
            "value": [contracts_unavailable],
            "budget": [contracts_unavailable],
            "legacy": [contracts_unavailable],
            "dependency": _dedupe([*(contract_blockers or []), contracts_unavailable]),
            "leak": _dedupe(
                [
                    *(["input_manifest_public_leak"] if input_leaks else []),
                    contracts_unavailable,
                ]
            ),
            "lightrag": [contracts_unavailable],
            "knowledge_hub": [contracts_unavailable],
        }
        phases.append(
            PhaseResult(
                phase="P0-contracts",
                name="versioned-contract-validation",
                status="blocked",
                blockers=contract_blockers or ["contracts_unavailable"],
            )
        )
        certification = _finalize_run(
            config,
            contracts=None,
            phases=phases,
            blockers=certification_blockers,
            input_leaks=input_leaks,
            inventory=inventory,
            rights_registry=rights_registry,
            registry=registry,
            visual_queue=visual_queue,
            cards=cards,
            kh_plan=kh_plan,
            lightrag_plan=lightrag_plan,
            crosswalk=crosswalk,
            cag_manifest=cag_manifest,
            normalized=normalized,
            cag_candidates=cag_candidates,
            eval_suite=eval_suite,
            independent_gate_blockers=unavailable_gate_vector,
        )
        return {"ledger": _read_written_ledger(config), "certification": certification}

    phases.append(
        PhaseResult(
            phase="P0-contracts",
            name="versioned-contract-validation",
            status="complete" if not contract_blockers else "blocked",
            counts={"manifests": 4},
            blockers=contract_blockers,
        )
    )

    inventory, inventory_blockers, inventory_fatal, source_snapshots = (
        _freeze_inventory(
            config,
            contracts.policy,
        )
    )
    _write_jsonl(config.run_dir / "governed-source-inventory.jsonl", inventory)
    phases.append(
        PhaseResult(
            phase="P0-inventory",
            name="immutable-source-inventory",
            status="complete" if not inventory_blockers else "blocked",
            output_paths=["governed-source-inventory.jsonl"],
            counts={
                "sources": len(inventory),
                "markdown": sum(
                    row.get("media_type") == "text/markdown" for row in inventory
                ),
                "png": sum(row.get("media_type") == "image/png" for row in inventory),
                "duplicates": sum(
                    row.get("inventory_disposition") == "duplicate" for row in inventory
                ),
            },
            blockers=inventory_blockers,
        )
    )
    required_providers = _required_providers(contracts.profile)
    normalized_markdown_bodies = _normalized_markdown_bodies(
        inventory,
        source_snapshots,
    )
    unsafe_metadata_paths = _find_raw_body_metadata_paths(
        contracts.policy,
        inventory,
        normalized_markdown_bodies,
    )
    unsafe_holdout_query_indexes = _find_raw_body_holdout_query_indexes(
        contracts.holdout,
        normalized_markdown_bodies,
    )
    rights_registry, rights_blockers = _build_rights_registry(
        contracts.policy,
        inventory,
        required_providers=required_providers,
        policy_manifest_parent=_repo_path(config.policy_manifest).parent,
        unsafe_metadata_paths=unsafe_metadata_paths,
        source_snapshots=source_snapshots,
    )
    _write_jsonl(config.run_dir / "governed-rights-registry.jsonl", rights_registry)
    phases.append(
        PhaseResult(
            phase="P0-rights",
            name="rights-certification",
            status="complete" if not rights_blockers else "blocked",
            output_paths=["governed-rights-registry.jsonl"],
            counts={
                "rights_records": len(rights_registry),
                "eligible": sum(
                    bool(row.get("apply_eligible")) for row in rights_registry
                ),
                "unknown": sum(
                    row.get("rights_status") == "unknown" for row in rights_registry
                ),
                "blocked": sum(
                    not bool(row.get("apply_eligible")) for row in rights_registry
                ),
            },
            blockers=rights_blockers,
        )
    )
    capability_gates = _capability_gate_vector(contracts.policy, contracts.capabilities)
    lightrag_capability_blockers = capability_gates["lightrag"]
    knowledge_hub_capability_blockers = capability_gates["knowledge_hub"]
    capability_blockers = _dedupe(
        [*lightrag_capability_blockers, *knowledge_hub_capability_blockers]
    )
    phases.append(
        PhaseResult(
            phase="P0-capabilities",
            name="read-only-capability-gate",
            status="complete" if not capability_blockers else "blocked",
            counts={
                "required_lightrag_capabilities": len(REQUIRED_LIGHTRAG_CAPABILITIES)
            },
            blockers=capability_blockers,
        )
    )
    observed_inventory_digest = inventory_audit_digest(inventory) if inventory else ""
    policy_gate_blockers = _policy_gate_blockers(
        contracts.policy,
        contracts.profile,
        observed_inventory_digest,
    )
    if unsafe_holdout_query_indexes:
        policy_gate_blockers = _dedupe(
            [*policy_gate_blockers, "holdout_query_raw_source_body_reuse"]
        )
    policy_gate_groups = _split_policy_gate_blockers(policy_gate_blockers)
    if contracts.policy.get("schema_version") in {
        POLICY_SCHEMA_VERSION,
        POLICY_SCHEMA_VERSION_V2,
    }:
        contract_gate_groups = _split_contract_gate_blockers(contract_blockers)
        independent_gate_blockers = {
            "inventory": _dedupe(
                [
                    *inventory_blockers,
                    *contract_gate_groups["inventory"],
                    *policy_gate_groups["inventory"],
                ]
            ),
            "rights": _dedupe(
                [
                    *rights_blockers,
                    *contract_gate_groups["rights"],
                    *policy_gate_groups["rights"],
                ]
            ),
            "value": _dedupe(
                [*contract_gate_groups["value"], *policy_gate_groups["value"]]
            ),
            "budget": _dedupe(
                [*contract_gate_groups["budget"], *policy_gate_groups["budget"]]
            ),
            "legacy": _dedupe(
                [*contract_gate_groups["legacy"], *policy_gate_groups["legacy"]]
            ),
            "dependency": _dedupe(
                [
                    *contract_gate_groups["dependency"],
                    *policy_gate_groups["dependency"],
                ]
            ),
            "leak": _dedupe(
                [
                    *contract_gate_groups["leak"],
                    *policy_gate_groups["leak"],
                    *(["input_manifest_public_leak"] if input_leaks else []),
                ]
            ),
            "lightrag": _dedupe(
                [*contract_gate_groups["lightrag"], *lightrag_capability_blockers]
            ),
            "knowledge_hub": _dedupe(
                [
                    *contract_gate_groups["knowledge_hub"],
                    *knowledge_hub_capability_blockers,
                ]
            ),
        }
    phases.append(
        PhaseResult(
            phase="P0-value-budget",
            name="value-holdout-budget-gate",
            status="complete" if not policy_gate_blockers else "blocked",
            counts={"holdout_queries": len(contracts.holdout.get("queries", []))},
            blockers=policy_gate_blockers,
        )
    )

    if not inventory_fatal:
        registry = _build_asset_registry(inventory, rights_registry)
        _write_jsonl(config.run_dir / "black-label-asset-registry.jsonl", registry)
        _write_jsonl(
            config.run_dir / "docling-pdf-page-image-crosswalk.jsonl", registry
        )
        visual_queue = _build_visual_queue(registry, rights_registry)
        _write_jsonl(config.run_dir / "visual-enrichment-queue.jsonl", visual_queue)
        cards, card_blockers = _build_cards(
            contracts.policy,
            inventory,
            rights_registry,
            unsafe_metadata_paths=unsafe_metadata_paths,
        )
        _write_jsonl(config.run_dir / "black-label-card-manifest.jsonl", cards)
        if contracts.policy.get("schema_version") == POLICY_SCHEMA_VERSION_V2:
            assert independent_gate_blockers is not None
            independent_gate_blockers["dependency"] = _dedupe(
                [*independent_gate_blockers["dependency"], *card_blockers]
            )
            p0_gate_names = {
                "inventory",
                "rights",
                "value",
                "legacy",
                "dependency",
                "leak",
                "lightrag",
            }
            aggregate_p0_blockers = _dedupe(
                blocker
                for gate_name in sorted(p0_gate_names)
                for blocker in independent_gate_blockers[gate_name]
            )
        else:
            aggregate_p0_blockers = _dedupe(
                [
                    *contract_blockers,
                    *inventory_blockers,
                    *rights_blockers,
                    *capability_blockers,
                    *policy_gate_blockers,
                    *card_blockers,
                ]
            )
        p0_ready = not aggregate_p0_blockers
        lightrag_plan = _build_lightrag_plan(cards, p0_ready=p0_ready)
        _write_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl", lightrag_plan)
        kh_plan = _build_kh_plan(registry, cards, p0_ready=p0_ready)
        _write_jsonl(config.run_dir / "kh-multimodal-apply-plan.jsonl", kh_plan)
        cag_manifest = _build_cag_manifest(cards, lightrag_plan, p0_ready=p0_ready)
        _write_jsonl(config.run_dir / "cag-pack-manifest.jsonl", cag_manifest)
        crosswalk = _build_crosswalk(registry, cards, lightrag_plan, cag_manifest)
        _write_jsonl(config.run_dir / "package-crosswalk.jsonl", crosswalk)
        normalized = _build_normalized_source_bundle(
            inventory, rights_registry, p0_ready=p0_ready
        )
        _write_jsonl(config.run_dir / "docling-normalized-output.jsonl", normalized)
        cag_candidates = _build_cag_candidates(cag_manifest, cards, crosswalk)
        _write_jsonl(config.run_dir / "cag-pack-candidates.jsonl", cag_candidates)
        eval_suite = _build_eval_suite(
            contracts.holdout,
            contracts.holdout_hash,
            redacted_query_indexes=unsafe_holdout_query_indexes,
        )
        _write_jsonl(config.run_dir / "black-label-eval-suite.jsonl", eval_suite)
        package_paths = [
            "black-label-asset-registry.jsonl",
            "docling-pdf-page-image-crosswalk.jsonl",
            "visual-enrichment-queue.jsonl",
            "black-label-card-manifest.jsonl",
            "kh-multimodal-apply-plan.jsonl",
            "lightrag-card-apply-plan.jsonl",
            "cag-pack-manifest.jsonl",
            "package-crosswalk.jsonl",
            "docling-normalized-output.jsonl",
            "cag-pack-candidates.jsonl",
            "black-label-eval-suite.jsonl",
        ]
        phases.append(
            PhaseResult(
                phase="P0-packages",
                name="deterministic-black-label-adapter",
                status="complete" if not card_blockers else "blocked",
                output_paths=package_paths,
                counts={
                    "assets": len(registry),
                    "cards": len(cards),
                    "planned_cards": sum(
                        row.get("apply_status") == "planned" for row in lightrag_plan
                    ),
                    "visual_requests": len(visual_queue),
                    "cag_packs": len(cag_manifest),
                    "normalized_records": len(normalized),
                    "cag_candidates": len(cag_candidates),
                    "eval_queries": len(eval_suite),
                },
                blockers=card_blockers,
            )
        )
    else:
        phases.append(
            PhaseResult(
                phase="P0-packages",
                name="deterministic-black-label-adapter",
                status="skipped",
                blockers=["inventory_not_safe_for_artifact_generation"],
            )
        )

    source_reconciliation_blockers = _reconcile_source_inventory(config, inventory)
    phases.append(
        PhaseResult(
            phase="P0-source-reconciliation",
            name="final-source-path-reconciliation",
            status="complete" if not source_reconciliation_blockers else "blocked",
            counts={"sources": len(inventory)},
            blockers=source_reconciliation_blockers,
        )
    )
    contract_reconciliation_blockers = _reconcile_loaded_contracts(config, contracts)
    phases.append(
        PhaseResult(
            phase="P0-contract-reconciliation",
            name="final-contract-evidence-reconciliation",
            status="complete" if not contract_reconciliation_blockers else "blocked",
            counts={"contracts": 3},
            blockers=contract_reconciliation_blockers,
        )
    )
    if independent_gate_blockers is not None:
        independent_gate_blockers["inventory"] = _dedupe(
            [
                *independent_gate_blockers["inventory"],
                *source_reconciliation_blockers,
            ]
        )
        reconciliation_gate_groups = _split_contract_gate_blockers(
            contract_reconciliation_blockers
        )
        for gate_name, gate_values in reconciliation_gate_groups.items():
            independent_gate_blockers[gate_name] = _dedupe(
                [*independent_gate_blockers[gate_name], *gate_values]
            )

    certification = _finalize_run(
        config,
        contracts=contracts,
        phases=phases,
        blockers=certification_blockers,
        input_leaks=input_leaks,
        inventory=inventory,
        rights_registry=rights_registry,
        registry=registry,
        visual_queue=visual_queue,
        cards=cards,
        kh_plan=kh_plan,
        lightrag_plan=lightrag_plan,
        crosswalk=crosswalk,
        cag_manifest=cag_manifest,
        normalized=normalized,
        cag_candidates=cag_candidates,
        eval_suite=eval_suite,
        independent_gate_blockers=independent_gate_blockers,
    )
    return {"ledger": _read_written_ledger(config), "certification": certification}


def _freeze_inventory(
    config: GovernedCorpusConfig,
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], bool, dict[str, bytes]]:
    blockers: list[str] = []
    fatal = False
    root = _repo_path(config.source_root)
    if root.is_symlink():
        return [], ["source_root_symlink_not_allowed"], True, {}
    try:
        resolved_root = root.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return [], ["source_root_unavailable"], True, {}
    if not resolved_root.is_dir():
        return [], ["source_root_not_directory"], True, {}

    rows: list[dict[str, Any]] = []
    first_by_hash: dict[str, str] = {}
    source_identity: dict[str, str] = {}
    package_identity: dict[str, str] = {}
    source_snapshots: dict[str, bytes] = {}
    sources = policy.get("sources") if isinstance(policy.get("sources"), list) else []
    for index, source in enumerate(
        sorted(
            (row for row in sources if isinstance(row, Mapping)),
            key=lambda row: str(row.get("relative_path") or ""),
        )
    ):
        relative_path = str(source.get("relative_path") or "")
        item_blockers: list[str] = []
        actual_size = 0
        actual_sha = ""
        if not _is_safe_relative_path(relative_path):
            item_blockers.append("source_relative_path_invalid")
        else:
            snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
                resolved_root,
                relative_path,
                blocker_prefix="source",
                max_bytes=64 * 1024 * 1024,
            )
            item_blockers.extend(snapshot_blockers)
            if snapshot is not None:
                actual_size = snapshot.size_bytes
                actual_sha = snapshot.sha256
                source_snapshots[relative_path] = snapshot.data
        if actual_size != _safe_int(source.get("size_bytes")):
            item_blockers.append("source_size_mismatch")
        if actual_sha != str(source.get("source_sha256") or ""):
            item_blockers.append("source_hash_mismatch")

        source_id = str(source.get("source_id") or "")
        package_id = str(source.get("package_id") or "")
        identity_sha = actual_sha or str(source.get("source_sha256") or "")
        if source_id in source_identity and source_identity[source_id] != identity_sha:
            item_blockers.append("source_id_hash_conflict")
        source_identity[source_id] = identity_sha
        if (
            package_id in package_identity
            and package_identity[package_id] != identity_sha
        ):
            item_blockers.append("package_id_hash_conflict")
        package_identity[package_id] = identity_sha

        disposition = str(source.get("inventory_disposition") or "blocked")
        duplicate_of = ""
        if identity_sha and identity_sha in first_by_hash:
            duplicate_of = first_by_hash[identity_sha]
            disposition = "duplicate"
        elif identity_sha:
            first_by_hash[identity_sha] = source_id
        if item_blockers:
            disposition = "blocked"
            fatal = True
            blocker_token = stable_hash(relative_path or index)[:12]
            blockers.extend(f"{blocker}:{blocker_token}" for blocker in item_blockers)

        row = {
            "schema_version": SOURCE_INVENTORY_SCHEMA_VERSION,
            "inventory_id": f"inventory_{stable_hash({'path': relative_path, 'source_id': source_id})[:20]}",
            "relative_path": relative_path
            if _is_safe_relative_path(relative_path)
            else "<redacted:invalid_path>",
            "media_type": source.get("media_type", ""),
            "size_bytes": actual_size,
            "expected_size_bytes": _safe_int(source.get("size_bytes")),
            "source_sha256": actual_sha,
            "expected_source_sha256": source.get("source_sha256", ""),
            "source_id": source_id,
            "package_id": package_id,
            "source_class_id": source.get("source_class_id", ""),
            "topic_id": source.get("topic_id", ""),
            "card_role": source.get("card_role", ""),
            "risk_rank": _safe_int(source.get("risk_rank")),
            "inventory_disposition": disposition,
            "duplicate_of_source_id": duplicate_of,
            "verification_status": "verified" if not item_blockers else "blocked",
            "blocking_reasons": item_blockers,
        }
        rows.append(p0p8._public_payload(row))

    contract = (
        policy.get("inventory_contract")
        if isinstance(policy.get("inventory_contract"), Mapping)
        else {}
    )
    if len(rows) != _safe_int(contract.get("expected_file_count")):
        blockers.append("observed_file_count_mismatch")
        fatal = True
    if sum(row.get("size_bytes", 0) for row in rows) != _safe_int(
        contract.get("expected_total_size_bytes")
    ):
        blockers.append("observed_total_size_mismatch")
        fatal = True
    observed_markdown = sum(row.get("media_type") == "text/markdown" for row in rows)
    observed_png = sum(row.get("media_type") == "image/png" for row in rows)
    if observed_markdown != _safe_int(contract.get("expected_markdown_count")):
        blockers.append("observed_markdown_count_mismatch")
        fatal = True
    if observed_png != _safe_int(contract.get("expected_png_count")):
        blockers.append("observed_png_count_mismatch")
        fatal = True
    manifest_paths = {
        str(source.get("relative_path") or "")
        for source in sources
        if isinstance(source, Mapping)
    }
    observed_paths: set[str] = set()
    for path in sorted(resolved_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            token = stable_hash(path.relative_to(resolved_root).as_posix())[:12]
            blockers.append(f"unallowlisted_source_symlink:{token}")
            fatal = True
            continue
        if path.is_file():
            observed_paths.add(path.relative_to(resolved_root).as_posix())
    for relative_path in sorted(observed_paths - manifest_paths):
        blockers.append(f"unlisted_source_file:{stable_hash(relative_path)[:12]}")
        fatal = True
    return rows, _dedupe(blockers), fatal, source_snapshots


def _reconcile_source_inventory(
    config: GovernedCorpusConfig,
    inventory: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Re-read the exact source set before certification and detect drift."""

    root = _repo_path(config.source_root)
    if root.is_symlink():
        return ["source_reconciliation_root_symlink_not_allowed"]
    try:
        resolved_root = root.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return ["source_reconciliation_root_unavailable"]
    if not resolved_root.is_dir():
        return ["source_reconciliation_root_not_directory"]

    expected_paths = {
        str(row.get("relative_path") or "")
        for row in inventory
        if _is_safe_relative_path(row.get("relative_path"))
    }
    actual_paths: set[str] = set()
    blockers: list[str] = []
    try:
        candidates = sorted(resolved_root.rglob("*"), key=lambda path: path.as_posix())
    except OSError:
        return ["source_reconciliation_scan_failed"]
    for path in candidates:
        relative_path = path.relative_to(resolved_root).as_posix()
        if path.is_symlink():
            blockers.append(
                f"source_reconciliation_symlink:{stable_hash(relative_path)[:12]}"
            )
        elif path.is_file():
            actual_paths.add(relative_path)
    for relative_path in sorted(expected_paths - actual_paths):
        blockers.append(
            f"source_reconciliation_missing:{stable_hash(relative_path)[:12]}"
        )
    for relative_path in sorted(actual_paths - expected_paths):
        blockers.append(
            f"source_reconciliation_extra:{stable_hash(relative_path)[:12]}"
        )

    rows_by_path = {
        str(row.get("relative_path") or ""): row
        for row in inventory
        if _is_safe_relative_path(row.get("relative_path"))
    }
    for relative_path in sorted(expected_paths & actual_paths):
        snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
            resolved_root,
            relative_path,
            blocker_prefix="source_reconciliation",
            max_bytes=64 * 1024 * 1024,
        )
        token = stable_hash(relative_path)[:12]
        blockers.extend(f"{blocker}:{token}" for blocker in snapshot_blockers)
        if snapshot is None:
            continue
        row = rows_by_path[relative_path]
        if snapshot.sha256 != row.get(
            "source_sha256"
        ) or snapshot.size_bytes != row.get("size_bytes"):
            blockers.append(f"source_reconciliation_content_drift:{token}")
    return _dedupe(blockers)


def _reconcile_loaded_contracts(
    config: GovernedCorpusConfig,
    contracts: LoadedContracts,
) -> list[str]:
    """Reconcile all contract and hash-bound evidence bytes before certification."""

    blockers: list[str] = []
    snapshots: dict[str, authority_evidence.FileSnapshot] = {}
    payloads: dict[str, dict[str, Any]] = {}
    contract_specs = {
        "policy_manifest": (
            _repo_path(config.policy_manifest),
            contracts.policy_hash,
            contracts.policy,
        ),
        "production_profile": (
            _repo_path(config.production_profile),
            contracts.profile_hash,
            contracts.profile,
        ),
        "runtime_capabilities": (
            _repo_path(config.runtime_capabilities),
            contracts.capabilities_hash,
            contracts.capabilities,
        ),
    }
    for name, (path, expected_sha256, expected_payload) in contract_specs.items():
        payload, snapshot = _read_json_snapshot(
            path,
            blocker=f"final_{name}",
            blockers=blockers,
        )
        if snapshot is None:
            continue
        snapshots[name] = snapshot
        payloads[name] = payload
        if snapshot.sha256 != expected_sha256 or not _json_values_exact(
            payload,
            expected_payload,
        ):
            blockers.append(f"contract_reconciliation_mismatch:{name}")

    if set(snapshots) != set(contract_specs) or blockers:
        return _dedupe(blockers)

    policy = payloads["policy_manifest"]
    capabilities = payloads["runtime_capabilities"]
    policy_path = contract_specs["policy_manifest"][0]
    capabilities_path = contract_specs["runtime_capabilities"][0]
    if policy.get("schema_version") == POLICY_SCHEMA_VERSION_V2:
        try:
            blockers.extend(
                _validate_evidence_generation_files(
                    policy,
                    policy_path=policy_path,
                    capabilities=capabilities,
                    capabilities_path=capabilities_path,
                    capabilities_sha256=snapshots["runtime_capabilities"].sha256,
                )
            )
        except (TypeError, ValueError, OverflowError, UnicodeError):
            blockers.append("evidence_generation_reconciliation_failed_closed")
    try:
        blockers.extend(
            _validate_value_evidence(
                policy,
                capabilities,
                policy_manifest_parent=policy_path.parent,
                profile_hash=snapshots["production_profile"].sha256,
                capabilities_hash=snapshots["runtime_capabilities"].sha256,
                holdout_hash=contracts.holdout_hash,
            )
        )
    except (TypeError, ValueError, OverflowError, UnicodeError):
        blockers.append("value_evidence_reconciliation_failed_closed")
    return _dedupe(blockers)


def _build_rights_registry(
    policy: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
    *,
    required_providers: set[str],
    policy_manifest_parent: Path,
    unsafe_metadata_paths: set[str],
    source_snapshots: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], list[str]]:
    source_by_path = {
        str(source.get("relative_path") or ""): source
        for source in policy.get("sources", [])
        if isinstance(source, Mapping)
    }
    source_classes = {
        str(row.get("source_class_id") or ""): row
        for row in policy.get("source_classes", [])
        if isinstance(row, Mapping)
    }
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for item in inventory:
        relative_path = str(item.get("relative_path") or "")
        source = source_by_path.get(relative_path, {})
        source_class = source_classes.get(str(item.get("source_class_id") or ""), {})
        eligible, reasons = _rights_eligibility(
            source,
            item,
            required_providers,
            source_class=source_class,
            policy_manifest_parent=policy_manifest_parent,
            policy=policy,
            source_bytes=source_snapshots.get(relative_path),
        )
        unsafe_metadata = relative_path in unsafe_metadata_paths
        if unsafe_metadata:
            reasons.append("unsafe_curated_metadata_reuses_source_body")
            eligible = False
        declared = source.get("apply_eligible") is True
        if declared != eligible:
            reasons.append("declared_apply_eligibility_mismatch")
            eligible = False
        if not eligible:
            token = stable_hash(item.get("source_id") or item.get("inventory_id"))[:12]
            blockers.append(f"rights_not_apply_eligible:{token}")
        source_blocking_reasons = (
            [] if unsafe_metadata else list(source.get("blocking_reasons", []))
        )
        row = {
            "schema_version": RIGHTS_REGISTRY_SCHEMA_VERSION,
            "source_id": item.get("source_id", ""),
            "package_id": item.get("package_id", ""),
            "relative_path": item.get("relative_path", ""),
            "source_class_id": item.get("source_class_id", ""),
            "rights_status": source.get("rights_status", "unknown"),
            "rights_basis": (
                "Curated rights metadata withheld after raw-body reuse detection."
                if unsafe_metadata
                else source.get("rights_basis", "")
            ),
            "permitted_local_uses": []
            if unsafe_metadata
            else sorted(set(source.get("permitted_local_uses", []))),
            "external_processing": source.get("external_processing") is True,
            "allowed_providers": []
            if unsafe_metadata
            else sorted(set(source.get("allowed_providers", []))),
            "allowed_regions": []
            if unsafe_metadata
            else sorted(set(source.get("allowed_regions", []))),
            "allowed_source_derived_fields": []
            if unsafe_metadata
            else sorted(set(source.get("allowed_source_derived_fields", []))),
            "evidence_refs": sorted(set(source.get("evidence_refs", []))),
            "evidence_predicates": dict(source.get("evidence_predicates", {})),
            "rights_evidence_sha256": source.get("rights_evidence_sha256"),
            "review_date": source.get("review_date", ""),
            "reviewer_id": source.get("reviewer_id", ""),
            "apply_eligible": eligible,
            "compatibility_rights_status": "clear" if eligible else "blocked",
            "blocking_reasons": _dedupe(source_blocking_reasons + reasons),
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    if not any(row.get("apply_eligible") for row in rows):
        blockers.append("no_apply_eligible_sources")
    return rows, _dedupe(blockers)


def _rights_eligibility(
    source: Mapping[str, Any],
    inventory: Mapping[str, Any],
    required_providers: set[str],
    *,
    source_class: Mapping[str, Any],
    policy_manifest_parent: Path,
    policy: Mapping[str, Any],
    source_bytes: bytes | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if source.get("blocking_reasons"):
        reasons.append("declared_rights_blockers_present")
    status = str(source.get("rights_status") or "unknown")
    if status not in {"verified_clear", "internal_use_only"}:
        reasons.append(f"rights_status_{status}")
    if inventory.get("verification_status") != "verified":
        reasons.append("inventory_not_verified")
    if inventory.get("inventory_disposition") not in {"selected", "review_required"}:
        reasons.append(
            f"inventory_{inventory.get('inventory_disposition') or 'blocked'}"
        )
    if not str(source.get("rights_basis") or "").strip():
        reasons.append("rights_basis_missing")
    if not REQUIRED_LOCAL_USES <= set(source.get("permitted_local_uses", [])):
        reasons.append("local_use_permissions_incomplete")
    if source.get("external_processing") is not True:
        reasons.append("external_processing_not_permitted")
    if not required_providers <= set(source.get("allowed_providers", [])):
        reasons.append("provider_disclosure_not_permitted")
    if not source.get("allowed_regions"):
        reasons.append("provider_region_not_declared")
    if not REQUIRED_SOURCE_DERIVED_FIELDS <= set(
        source.get("allowed_source_derived_fields", [])
    ):
        reasons.append("source_derived_fields_not_permitted")
    predicates = (
        source.get("evidence_predicates")
        if isinstance(source.get("evidence_predicates"), Mapping)
        else {}
    )
    required_predicates = (
        set(source_class.get("required_true_predicates", []))
        if isinstance(source_class, Mapping)
        else set()
    )
    if not required_predicates or not required_predicates <= EVIDENCE_PREDICATE_KEYS:
        reasons.append("source_class_predicates_unavailable")
    required_predicates |= UNIVERSAL_EVIDENCE_PREDICATES
    if source.get("external_processing") is True or required_providers:
        required_predicates |= PROVIDER_EVIDENCE_PREDICATES
    if source.get("media_type") == "image/png":
        required_predicates |= VISUAL_EVIDENCE_PREDICATES
    if not set(predicates) <= EVIDENCE_PREDICATE_KEYS or any(
        predicates.get(key) is not True for key in required_predicates
    ):
        reasons.append("rights_evidence_predicates_incomplete")
    if not source.get("review_date") or not source.get("reviewer_id"):
        reasons.append("rights_review_missing")
    reasons.extend(
        _rights_evidence_blockers(
            source,
            policy_manifest_parent,
            policy=policy,
            source_bytes=source_bytes,
        )
    )
    return not reasons, reasons


def _rights_evidence_blockers(
    source: Mapping[str, Any],
    policy_manifest_parent: Path,
    *,
    policy: Mapping[str, Any] | None = None,
    source_bytes: bytes | None = None,
) -> list[str]:
    refs = (
        source.get("evidence_refs")
        if isinstance(source.get("evidence_refs"), list)
        else []
    )
    if len(refs) != 1:
        return [
            "rights_evidence_reference_missing"
            if not refs
            else "rights_evidence_reference_ambiguous"
        ]
    expected_hash = str(source.get("rights_evidence_sha256") or "")
    if not SHA256_RE.fullmatch(expected_hash):
        return ["rights_evidence_hash_missing"]
    ref = refs[0]
    if not _is_safe_relative_path(ref):
        return ["rights_evidence_reference_invalid"]
    snapshot, snapshot_blockers = authority_evidence.snapshot_anchored_file(
        policy_manifest_parent,
        ref,
        blocker_prefix="rights_evidence",
        max_bytes=2 * 1024 * 1024,
    )
    if snapshot is None:
        return snapshot_blockers
    if snapshot.sha256 != expected_hash:
        return ["rights_evidence_hash_mismatch"]
    try:
        evidence = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["rights_evidence_json_invalid"]
    if policy and policy.get("schema_version") == POLICY_SCHEMA_VERSION_V2:
        return _validate_v2_rights_evidence(
            source,
            evidence,
            policy,
            policy_manifest_parent,
            source_bytes,
        )
    expected_keys = {
        "schema_version",
        "source_id",
        "source_sha256",
        "rights_status",
        "rights_basis",
        "permitted_local_uses",
        "external_processing",
        "allowed_providers",
        "allowed_regions",
        "allowed_source_derived_fields",
        "evidence_predicates",
        "review_date",
        "reviewer_id",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != expected_keys:
        return ["rights_evidence_schema_invalid"]
    if evidence.get("schema_version") != RIGHTS_EVIDENCE_SCHEMA_VERSION:
        return ["rights_evidence_schema_version_mismatch"]
    bound_fields = expected_keys - {"schema_version"}
    mismatches = [
        key for key in sorted(bound_fields) if evidence.get(key) != source.get(key)
    ]
    if mismatches:
        return [f"rights_evidence_source_binding_mismatch:{key}" for key in mismatches]
    if not SHA256_RE.fullmatch(str(evidence.get("source_sha256") or "")):
        return ["rights_evidence_source_hash_invalid"]
    if not isinstance(evidence.get("external_processing"), bool):
        return ["rights_evidence_permissions_invalid"]
    for key in (
        "permitted_local_uses",
        "allowed_providers",
        "allowed_regions",
        "allowed_source_derived_fields",
    ):
        if not _is_bounded_string_list(
            evidence.get(key), max_items=MAX_CURATED_LIST_ITEMS
        ):
            return ["rights_evidence_permissions_invalid"]
    evidence_predicates = evidence.get("evidence_predicates")
    if (
        not isinstance(evidence_predicates, Mapping)
        or not set(evidence_predicates) <= EVIDENCE_PREDICATE_KEYS
    ):
        return ["rights_evidence_predicates_invalid"]
    if not SAFE_ID_RE.fullmatch(str(evidence.get("reviewer_id") or "")):
        return ["rights_evidence_reviewer_invalid"]
    try:
        date.fromisoformat(str(evidence.get("review_date") or ""))
    except ValueError:
        return ["rights_evidence_review_date_invalid"]
    return []


def _validate_v2_rights_evidence(
    source: Mapping[str, Any],
    evidence: Any,
    policy: Mapping[str, Any],
    policy_manifest_parent: Path,
    source_bytes: bytes | None,
) -> list[str]:
    if not isinstance(evidence, Mapping):
        return ["rights_evidence_schema_invalid"]
    generation = policy.get("evidence_generation")
    if not isinstance(generation, Mapping):
        return ["rights_evidence_generation_missing"]
    rights_records = (
        generation.get("rights_records")
        if isinstance(generation.get("rights_records"), list)
        else []
    )
    matching_records = [
        record
        for record in rights_records
        if isinstance(record, Mapping)
        and record.get("source_id") == source.get("source_id")
    ]
    if len(matching_records) != 1:
        return ["rights_evidence_generation_binding_missing"]
    record = matching_records[0]
    if record.get("artifact_ref") != source.get("evidence_refs", [None])[
        0
    ] or record.get("sha256") != source.get("rights_evidence_sha256"):
        return ["rights_evidence_generation_binding_mismatch"]

    registry_path, registry_blockers = _hash_bound_snapshot_path(
        policy_manifest_parent,
        generation.get("trust_registry_ref"),
        generation.get("trust_registry_sha256"),
        blocker_prefix="rights_trust_registry",
    )
    if registry_path is None:
        return registry_blockers
    registry, load_blockers = authority_evidence.load_trust_registry(registry_path)
    if registry is None:
        return _dedupe([*registry_blockers, *load_blockers])
    if registry.sha256 != generation.get("trust_registry_sha256"):
        return _dedupe(
            [*registry_blockers, *load_blockers, "rights_trust_registry_hash_mismatch"]
        )
    observation, observation_blockers = _load_hash_bound_json_snapshot(
        policy_manifest_parent,
        generation.get("origin_observation_ref"),
        generation.get("origin_observation_sha256"),
        blocker_prefix="rights_origin_observation",
    )
    if observation is None:
        return observation_blockers
    if not isinstance(source_bytes, bytes):
        return ["rights_source_snapshot_missing"]
    requested_uses = list(source.get("permitted_local_uses", []))
    if source.get("external_processing") is True:
        requested_uses.append("external_provider_disclosure")
    decision = authority_evidence.validate_source_authority(
        registry,
        observation,
        reviewer_id=str(source.get("reviewer_id") or ""),
        source_relative_path=str(source.get("relative_path") or ""),
        source_bytes=source_bytes,
        requested_uses=requested_uses,
    )
    blockers = list(decision.blockers)
    if not decision.eligible:
        blockers.append("rights_authority_decision_blocked")
    if not _json_values_exact(evidence, decision.evidence):
        blockers.append("rights_authority_evidence_mismatch")
    return _dedupe(blockers)


def _normalized_markdown_bodies(
    inventory: Sequence[Mapping[str, Any]],
    source_snapshots: Mapping[str, bytes] | Path,
) -> list[str]:
    """Use the inventory's immutable byte snapshots for in-memory reuse checks."""
    if isinstance(source_snapshots, Path):
        root = source_snapshots
        snapshots: dict[str, bytes] = {}
        for item in inventory:
            relative_path = str(item.get("relative_path") or "")
            if not _is_safe_relative_path(relative_path):
                continue
            snapshot, _blockers = authority_evidence.snapshot_anchored_file(
                root,
                relative_path,
                blocker_prefix="source",
                max_bytes=64 * 1024 * 1024,
            )
            if snapshot is not None:
                snapshots[relative_path] = snapshot.data
        source_snapshots = snapshots
    normalized_bodies: list[str] = []
    for item in inventory:
        if (
            item.get("verification_status") != "verified"
            or item.get("media_type") != "text/markdown"
        ):
            continue
        relative_path = str(item.get("relative_path") or "")
        if not _is_safe_relative_path(relative_path):
            continue
        body_bytes = source_snapshots.get(relative_path)
        if not isinstance(body_bytes, bytes):
            continue
        body = body_bytes.decode("utf-8", errors="replace")
        normalized = _normalize_verbatim_text(body)
        if normalized:
            normalized_bodies.append(normalized)
    return normalized_bodies


def _find_raw_body_metadata_paths(
    policy: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
    normalized_bodies: Sequence[str],
) -> set[str]:
    """Detect body-derived metadata locally without returning or persisting bodies."""

    source_by_path = {
        str(row.get("relative_path") or ""): row
        for row in policy.get("sources", [])
        if isinstance(row, Mapping)
    }
    classes = {
        str(row.get("source_class_id") or ""): row
        for row in policy.get("source_classes", [])
        if isinstance(row, Mapping)
    }
    topics = {
        str(row.get("topic_id") or ""): row
        for row in policy.get("topics", [])
        if isinstance(row, Mapping)
    }
    unsafe: set[str] = set()
    for item in inventory:
        relative_path = str(item.get("relative_path") or "")
        source = source_by_path.get(relative_path, {})
        source_class = classes.get(str(item.get("source_class_id") or ""), {})
        topic = topics.get(str(item.get("topic_id") or ""), {})
        values: list[Any] = [
            source.get("title"),
            source.get("declared_summary"),
            source.get("rights_basis"),
            source_class.get("description"),
            source_class.get("evidence_available"),
            source_class.get("adjudication_reason"),
            topic.get("description"),
            topic.get("membership_rule"),
        ]
        for key in (
            "heading_seeds",
            "relationships",
            "permitted_local_uses",
            "allowed_providers",
            "allowed_regions",
            "allowed_source_derived_fields",
            "blocking_reasons",
        ):
            if isinstance(source.get(key), list):
                values.extend(source.get(key, []))
        if any(_value_reuses_body(value, normalized_bodies) for value in values):
            unsafe.add(relative_path)
    return unsafe


def _find_raw_body_holdout_query_indexes(
    holdout: Mapping[str, Any],
    normalized_bodies: Sequence[str],
) -> set[int]:
    queries = holdout.get("queries") if isinstance(holdout.get("queries"), list) else []
    return {
        index
        for index, query in enumerate(queries)
        if isinstance(query, Mapping)
        and any(
            _value_reuses_body(value, normalized_bodies)
            for value in _iter_recursive_strings(query)
        )
    }


def _iter_recursive_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_recursive_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_recursive_strings(item)


def _normalize_verbatim_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _value_reuses_body(value: Any, normalized_bodies: Sequence[str]) -> bool:
    normalized = _normalize_verbatim_text(value)
    if not normalized:
        return False
    for body in normalized_bodies:
        if normalized in body or body in normalized:
            return True
        if len(normalized) >= MIN_BODY_REUSE_CHARS and any(
            normalized[start : start + MIN_BODY_REUSE_CHARS] in body
            for start in range(len(normalized) - MIN_BODY_REUSE_CHARS + 1)
        ):
            return True
    return False


def _build_asset_registry(
    inventory: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rights_by_source = {str(row.get("source_id") or ""): row for row in rights}
    rows: list[dict[str, Any]] = []
    for source in inventory:
        source_id = str(source.get("source_id") or "")
        source_sha = str(
            source.get("source_sha256") or source.get("expected_source_sha256") or ""
        )
        package_id = str(source.get("package_id") or "")
        media_type = str(source.get("media_type") or "")
        artifact_kind = "image" if media_type == "image/png" else "text"
        image_package_id = (
            f"img_{source_sha[:20]}" if artifact_kind == "image" and source_sha else ""
        )
        rights_row = rights_by_source.get(source_id, {})
        row = {
            "schema_version": black_label.ASSET_REGISTRY_SCHEMA_VERSION,
            "asset_id": f"asset_{stable_hash({'package_id': package_id, 'source_id': source_id})[:20]}",
            "package_key": package_id,
            "pdf_package_id": "",
            "page_package_id": "",
            "image_package_id": image_package_id,
            "source_pdf_id": source_id,
            "source_sha256": source_sha,
            "artifact_sha256": source_sha,
            "source_relative_path": source.get("relative_path", ""),
            "output_relative_path": "",
            "artifact_layer": "governed_source_asset",
            "artifact_kind": artifact_kind,
            "output_file_kind": "image" if artifact_kind == "image" else "markdown",
            "page": 0,
            "quality_status": "usable"
            if source.get("verification_status") == "verified"
            else "blocked",
            "status": "available"
            if source.get("verification_status") == "verified"
            else "blocked",
            "kh_candidate_id": f"kh_asset_{stable_hash({'package_id': package_id})[:20]}",
            "graph_document_id": "",
            "cag_pack_id": "",
            "public_label": PurePosixPath(
                str(source.get("relative_path") or source_id)
            ).stem,
            "rights_status": rights_row.get("compatibility_rights_status", "blocked"),
            "inventory_disposition": source.get("inventory_disposition", "blocked"),
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("source_relative_path") or ""),
            str(row.get("asset_id") or ""),
        ),
    )


def _build_visual_queue(
    registry: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rights_by_source = {str(row.get("source_id") or ""): row for row in rights}
    rows: list[dict[str, Any]] = []
    for asset in registry:
        if asset.get("artifact_kind") != "image":
            continue
        source_id = str(asset.get("source_pdf_id") or "")
        eligible = bool(rights_by_source.get(source_id, {}).get("apply_eligible"))
        row = {
            "schema_version": black_label.VISUAL_QUEUE_SCHEMA_VERSION,
            "request_id": f"visual_{stable_hash({'asset_id': asset.get('asset_id'), 'profile': 'metadata-only'})[:20]}",
            "asset_id": asset.get("asset_id", ""),
            "pdf_package_id": "",
            "page_package_id": "",
            "image_package_id": asset.get("image_package_id", ""),
            "package_key": asset.get("package_key", ""),
            "source_sha256": asset.get("source_sha256", ""),
            "artifact_kind": "image",
            "provider": "not_configured",
            "model": "",
            "ocr_model": "",
            "endpoint_region": "",
            "fallback_provider": "none",
            "base_url_configured": False,
            "api_key_configured": False,
            "analysis_profile": "governed_visual_metadata_only.v1",
            "requested_tasks": [],
            "priority": 0,
            "priority_batch": "not_applicable_p0",
            "visual_link_status": "missing",
            "status": "metadata_only" if eligible else "blocked",
            "readiness_status": "outside_p0_scope",
            "mutation_performed": False,
            "provider_call_performed": False,
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("asset_id") or ""))


def _build_cards(
    policy: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
    *,
    unsafe_metadata_paths: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    source_by_path = {
        str(source.get("relative_path") or ""): source
        for source in policy.get("sources", [])
        if isinstance(source, Mapping)
    }
    rights_by_source = {str(row.get("source_id") or ""): row for row in rights}
    source_classes = {
        str(row.get("source_class_id") or ""): row
        for row in policy.get("source_classes", [])
        if isinstance(row, Mapping)
    }
    topics = {
        str(row.get("topic_id") or ""): row
        for row in policy.get("topics", [])
        if isinstance(row, Mapping)
    }
    corpus_id = str(policy.get("corpus_id") or "corpus")
    cards_by_id: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for item in inventory:
        if item.get("verification_status") != "verified":
            continue
        relative_path = str(item.get("relative_path") or "")
        source = source_by_path.get(relative_path, {})
        source_id = str(item.get("source_id") or "")
        source_sha = str(item.get("source_sha256") or "")
        role = str(item.get("card_role") or "source_card")
        card_id = f"card_{role}_{stable_hash({'source_sha256': source_sha, 'card_role': role})[:20]}"
        topic_id = str(item.get("topic_id") or "general")
        topic = topics.get(topic_id, {})
        source_class = source_classes.get(str(item.get("source_class_id") or ""), {})
        unsafe_metadata = relative_path in unsafe_metadata_paths
        fallback_title = (
            PurePosixPath(relative_path)
            .stem.replace("-", " ")
            .replace("_", " ")
            .title()[:160]
        )
        fallback_summary = f"Curated metadata withheld for governed topic {topic_id}."
        if unsafe_metadata:
            title = fallback_title
            summary = fallback_summary
            heading_seeds = [topic_id[:96]]
            relationships = [
                f"belongs_to_topic:{topic_id}",
                f"derived_from_package:{item.get('package_id')}",
            ]
        else:
            title = str(source.get("title") or fallback_title)[:160]
            summary = str(
                source.get("declared_summary")
                or source_class.get("description")
                or fallback_summary
            )[:1_024]
            heading_seeds = [
                str(value)[:160]
                for value in source.get("heading_seeds", [])
                if str(value).strip()
            ][:8]
            if not heading_seeds:
                topic_label = str(topic.get("description") or topic_id)
                heading_seeds = [topic_label[:96]]
            relationships = [
                str(value)[:MAX_CURATED_LIST_ITEM_CHARS]
                for value in source.get("relationships", [])
                if str(value).strip()
            ][:16]
            if not relationships:
                relationships = [
                    f"belongs_to_topic:{topic_id}",
                    f"derived_from_package:{item.get('package_id')}",
                ]
        payload = {
            "title": title,
            "summary": summary,
            "heading_seeds": heading_seeds,
            "relationships": relationships,
            "topic_id": topic_id,
            "source_class_id": item.get("source_class_id", ""),
            "package_ids": [item.get("package_id")],
            "source_hashes": [source_sha],
        }
        payload_hash = stable_hash(payload)
        rights_row = rights_by_source.get(source_id, {})
        eligible = bool(rights_row.get("apply_eligible")) and not unsafe_metadata
        card = {
            "schema_version": black_label.CARD_SCHEMA_VERSION,
            "card_id": card_id,
            "revision_id": f"card_revision_{payload_hash[:20]}",
            "card_role": role,
            "title": title,
            "topic_id": topic_id,
            "risk_rank": _safe_int(item.get("risk_rank")),
            "source_id": source_id,
            "source_relative_path": relative_path,
            "package_ids": [item.get("package_id")],
            "source_hashes": [source_sha],
            "source_pdf_id": source_id,
            "model_profile": "governed_corpus_cards.v1",
            "rights_status": "clear" if eligible else "blocked",
            "rights_warnings": []
            if eligible
            else list(rights_row.get("blocking_reasons", [])),
            "raw_source_text_included": unsafe_metadata,
            "payload_outline": summary,
            "payload_contract": payload,
            "payload_hash": payload_hash,
            "estimated_chars": len(
                json.dumps(payload, sort_keys=True, ensure_ascii=True)
            ),
            "status": "candidate" if eligible else "blocked",
            "blocked_reason": (
                ""
                if eligible
                else "unsafe_curated_metadata_detected"
                if unsafe_metadata
                else "rights_status_not_clear"
            ),
            "file_source": f"black-label-governed/{slugify(corpus_id)}/{card_id}.md",
        }
        card["provenance_hash"] = stable_hash(
            {key: value for key, value in card.items() if key != "provenance_hash"}
        )
        existing = cards_by_id.get(card_id)
        if existing and existing.get("payload_hash") != payload_hash:
            blockers.append(f"logical_card_payload_conflict:{card_id}")
            continue
        if item.get("inventory_disposition") == "duplicate":
            continue
        cards_by_id.setdefault(card_id, p0p8._public_payload(card))
    rows = sorted(
        cards_by_id.values(),
        key=lambda row: (
            str(row.get("source_id") or ""),
            str(row.get("card_role") or ""),
        ),
    )
    if not rows:
        blockers.append("no_cards_generated")
    if any(row.get("raw_source_text_included") for row in rows):
        blockers.append("raw_source_text_included")
    return rows, _dedupe(blockers)


def _build_lightrag_plan(
    cards: Sequence[Mapping[str, Any]],
    *,
    p0_ready: bool,
    p1_controller_ready: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        rights_clear = card.get("rights_status") == "clear" and not card.get(
            "raw_source_text_included"
        )
        eligible = p0_ready and p1_controller_ready and rights_clear
        if not p0_ready:
            blocked_reason = "p0_gate_blocked"
        elif not rights_clear:
            blocked_reason = "rights_or_content_gate_blocked"
        elif not p1_controller_ready:
            blocked_reason = "p1_controller_not_implemented"
        else:
            blocked_reason = ""
        graph_document_id = (
            f"lightrag_black_label_{stable_hash({'card_id': card.get('card_id')})[:20]}"
        )
        row = {
            "schema_version": black_label.LIGHTRAG_PLAN_SCHEMA_VERSION,
            "graph_document_id": graph_document_id,
            "card_id": card.get("card_id", ""),
            "revision_id": card.get("revision_id", ""),
            "payload_hash": card.get("payload_hash", ""),
            "file_source": card.get("file_source", ""),
            "card_role": card.get("card_role", ""),
            "topic_id": card.get("topic_id", ""),
            "source_id": card.get("source_id", ""),
            "source_package_refs": card.get("package_ids", []),
            "source_hashes": card.get("source_hashes", []),
            "estimated_chars": _safe_int(card.get("estimated_chars")),
            "rights_status": card.get("rights_status", "blocked"),
            "apply_stage": "not_assigned_p0" if p0_ready else "blocked_p0",
            "apply_status": "planned" if eligible else "blocked",
            "blocked_reason": blocked_reason,
            "p0_gate_ready": p0_ready,
            "p1_controller_ready": p1_controller_ready,
            "mutation_performed": False,
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("card_id") or ""))


def _build_kh_plan(
    registry: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    *,
    p0_ready: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in registry:
        row = {
            "schema_version": black_label.KH_PLAN_SCHEMA_VERSION,
            "kh_plan_id": f"kh_asset_{stable_hash({'asset_id': asset.get('asset_id')})[:20]}",
            "target": "knowledge_hub_multimodal_package",
            "asset_id": asset.get("asset_id", ""),
            "package_key": asset.get("package_key", ""),
            "pdf_package_id": "",
            "image_package_id": asset.get("image_package_id", ""),
            "modality": "image" if asset.get("artifact_kind") == "image" else "text",
            "artifact_kind": asset.get("artifact_kind", ""),
            "source_sha256": asset.get("source_sha256", ""),
            "preview_reference": "",
            "apply_status": "blocked" if not p0_ready else "deferred_p0",
            "blocked_reason": "p0_gate_blocked"
            if not p0_ready
            else "kh_promotion_outside_p0",
            "handoff_status": "blocked_until_p0_green"
            if not p0_ready
            else "kh_promotion_capability_required",
            "direct_datastore_write": False,
            "mutation_performed": False,
        }
        rows.append(p0p8._public_payload(row))
    for card in cards:
        row = {
            "schema_version": black_label.KH_PLAN_SCHEMA_VERSION,
            "kh_plan_id": f"kh_card_{stable_hash({'card_id': card.get('card_id')})[:20]}",
            "target": "knowledge_hub_text_layer",
            "card_id": card.get("card_id", ""),
            "card_role": card.get("card_role", ""),
            "package_ids": card.get("package_ids", []),
            "modality": "text",
            "apply_status": "blocked" if not p0_ready else "deferred_p0",
            "blocked_reason": "p0_gate_blocked"
            if not p0_ready
            else "kh_promotion_outside_p0",
            "handoff_status": "blocked_until_p0_green"
            if not p0_ready
            else "kh_promotion_capability_required",
            "direct_datastore_write": False,
            "mutation_performed": False,
        }
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("kh_plan_id") or ""))


def _build_cag_manifest(
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
    *,
    p0_ready: bool,
) -> list[dict[str, Any]]:
    graph_by_card = {str(row.get("card_id") or ""): row for row in lightrag_plan}
    by_topic: dict[str, list[Mapping[str, Any]]] = {}
    for card in cards:
        by_topic.setdefault(str(card.get("topic_id") or "general"), []).append(card)
    rows: list[dict[str, Any]] = []
    for topic_id, topic_cards in sorted(by_topic.items()):
        evidence_ids = sorted(
            str(card.get("card_id") or "")
            for card in topic_cards
            if p0_ready
            and card.get("rights_status") == "clear"
            and not card.get("raw_source_text_included")
        )
        graph_refs = sorted(
            str(graph_by_card.get(card_id, {}).get("graph_document_id") or "")
            for card_id in evidence_ids
            if graph_by_card.get(card_id, {}).get("apply_status") == "planned"
        )
        visual_refs: list[str] = []
        row = {
            "schema_version": black_label.CAG_MANIFEST_SCHEMA_VERSION,
            "cag_pack_id": f"cag_black_label_{slugify(topic_id)}_{stable_hash(evidence_ids)[:12]}",
            "topic": topic_id,
            "topic_id": topic_id,
            "evidence_card_ids": evidence_ids,
            "graph_refs": graph_refs,
            "visual_refs": visual_refs,
            "refresh_hash": stable_hash(
                {"cards": evidence_ids, "graphs": graph_refs, "visual": visual_refs}
            ),
            "raw_source_text_included": any(
                card.get("raw_source_text_included") for card in topic_cards
            ),
            "status": "available" if evidence_ids and graph_refs else "blocked",
            "blocked_reason": (
                ""
                if evidence_ids and graph_refs
                else "p0_gate_blocked"
                if not p0_ready
                else "p1_controller_not_implemented"
            ),
            "graph_readiness_status": "pending_lightrag_stage_evidence",
            "visual_readiness_status": "outside_p0_scope",
            "mutation_performed": False,
        }
        rows.append(p0p8._public_payload(row))
    return rows


def _build_crosswalk(
    registry: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
    cag_manifest: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cards_by_package: dict[str, list[Mapping[str, Any]]] = {}
    for card in cards:
        for package_id in card.get("package_ids", []):
            cards_by_package.setdefault(str(package_id), []).append(card)
    plan_by_card = {str(row.get("card_id") or ""): row for row in lightrag_plan}
    cag_by_card: dict[str, str] = {}
    for pack in cag_manifest:
        for card_id in pack.get("evidence_card_ids", []):
            cag_by_card.setdefault(str(card_id), str(pack.get("cag_pack_id") or ""))
    rows: list[dict[str, Any]] = []
    for asset in registry:
        package_id = str(asset.get("package_key") or "")
        package_cards = cards_by_package.get(package_id, [])
        card_ids = sorted(str(card.get("card_id") or "") for card in package_cards)
        graph_refs = sorted(
            str(plan_by_card.get(card_id, {}).get("graph_document_id") or "")
            for card_id in card_ids
            if plan_by_card.get(card_id, {}).get("apply_status") == "planned"
        )
        cag_ids = sorted(
            {
                cag_by_card.get(card_id, "")
                for card_id in card_ids
                if cag_by_card.get(card_id, "")
            }
        )
        row = {
            "schema_version": p0p8.CROSSWALK_SCHEMA_VERSION,
            "package_key": package_id,
            "public_label": asset.get("public_label", ""),
            "layer": asset.get("artifact_layer", ""),
            "source_sha256": asset.get("source_sha256", ""),
            "kh_candidate_id": asset.get("kh_candidate_id", ""),
            "graph_document_id": graph_refs[0] if graph_refs else "",
            "graph_document_ids": graph_refs,
            "card_ids": card_ids,
            "cag_pack_id": cag_ids[0] if cag_ids else "",
            "cag_pack_ids": cag_ids,
            "status": "linked"
            if card_ids and graph_refs
            else "partial"
            if card_ids
            else "blocked",
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("package_key") or ""))


def _build_normalized_source_bundle(
    inventory: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
    *,
    p0_ready: bool,
) -> list[dict[str, Any]]:
    """Project governed inventory into the existing metadata-only source contract."""
    rights_by_source = {str(row.get("source_id") or ""): row for row in rights}
    rows: list[dict[str, Any]] = []
    for source in inventory:
        source_id = str(source.get("source_id") or "")
        source_sha = str(source.get("source_sha256") or "")
        relative_path = str(source.get("relative_path") or "")
        media_type = str(source.get("media_type") or "")
        rights_eligible = bool(
            rights_by_source.get(source_id, {}).get("apply_eligible")
        )
        eligible = p0_ready and rights_eligible
        row = {
            "schema_version": p0p8.NORMALIZED_SCHEMA_VERSION,
            "record_id": f"governed_{stable_hash({'source_id': source_id, 'source_sha256': source_sha})[:20]}",
            "package_key": source.get("package_id", ""),
            "public_label": PurePosixPath(relative_path or source_id).stem,
            "artifact_layer": "governed_source_asset",
            "status": "available" if eligible else "blocked",
            "overlay_level": "none",
            "source_pdf_id": source_id,
            "source_relative_path": relative_path,
            "source_sha256": source_sha,
            "output_relative_path": "",
            "output_file_kind": "image" if media_type == "image/png" else "markdown",
            "artifact_sha256": source_sha,
            "quality_status": "usable" if eligible else "blocked",
            "rights_status": "clear" if eligible else "blocked",
            "blocked_reason": ""
            if eligible
            else "p0_gate_blocked"
            if not p0_ready
            else "rights_status_not_clear",
            "raw_source_text_included": False,
        }
        row["provenance_hash"] = stable_hash(row)
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("package_key") or ""))


def _build_cag_candidates(
    cag_manifest: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cards_by_id = {str(row.get("card_id") or ""): row for row in cards}
    crosswalk_by_package = {str(row.get("package_key") or ""): row for row in crosswalk}
    rows: list[dict[str, Any]] = []
    for pack in cag_manifest:
        evidence_cards = [
            cards_by_id[card_id]
            for card_id in (str(value) for value in pack.get("evidence_card_ids", []))
            if card_id in cards_by_id
        ]
        package_keys = sorted(
            {
                str(package_key)
                for card in evidence_cards
                for package_key in card.get("package_ids", [])
                if str(package_key) in crosswalk_by_package
            }
        )
        row = {
            "schema_version": p0p8.CAG_SCHEMA_VERSION,
            "cag_pack_id": pack.get("cag_pack_id", ""),
            "topic": pack.get("topic", "general"),
            "status": "available"
            if pack.get("status") == "available" and package_keys
            else "blocked",
            "evidence_package_keys": package_keys,
            "source_hashes": sorted(
                {
                    str(crosswalk_by_package[key].get("source_sha256") or "")
                    for key in package_keys
                    if crosswalk_by_package[key].get("source_sha256")
                }
            ),
            "crosswalk_hash": stable_hash(
                [crosswalk_by_package[key] for key in package_keys]
            ),
            "raw_source_text_included": False,
            "mutation_performed": False,
        }
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("cag_pack_id") or ""))


def _build_eval_suite(
    holdout: Mapping[str, Any],
    holdout_hash: str,
    *,
    redacted_query_indexes: set[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queries = holdout.get("queries") if isinstance(holdout.get("queries"), list) else []
    for index, query in enumerate(queries):
        if not isinstance(query, Mapping):
            continue
        redacted = index in redacted_query_indexes
        raw_query_id = query.get("holdout_id") or query.get("query_id")
        query_id_valid = _is_bounded_text(
            raw_query_id,
            max_chars=MAX_CURATED_LIST_ITEM_CHARS,
        )
        query_id = (
            f"redacted_{stable_hash({'holdout_hash': holdout_hash, 'query_index': index})[:20]}"
            if redacted
            else str(raw_query_id)
            if query_id_valid
            else f"invalid_{stable_hash({'holdout_hash': holdout_hash, 'query_index': index})[:20]}"
        )
        query_text_valid = _is_bounded_text(
            query.get("query"),
            max_chars=MAX_CURATED_TEXT_CHARS,
        )
        expected_topic_ids = query.get("expected_topic_ids")
        expected_topic_ids_valid = _is_bounded_string_list(
            expected_topic_ids,
            max_items=MAX_CURATED_LIST_ITEMS,
        )
        answer_criteria = query.get("answer_criteria")
        answer_criteria_valid = _is_bounded_string_list(
            answer_criteria,
            max_items=MAX_CURATED_LIST_ITEMS,
        )
        row = {
            "schema_version": black_label.EVAL_SCHEMA_VERSION,
            "eval_id": f"eval_holdout_{stable_hash({'holdout_hash': holdout_hash, 'query_id': query_id})[:20]}",
            "query_id": query_id,
            "query": REDACTED_HOLDOUT_QUERY
            if redacted
            else str(query.get("query"))
            if query_text_valid
            else REDACTED_INVALID_HOLDOUT_QUERY,
            "expected_topic_ids": []
            if redacted or not expected_topic_ids_valid
            else list(expected_topic_ids),
            "answer_criteria_hash": stable_hash(
                [] if redacted or not answer_criteria_valid else answer_criteria
            ),
            "expected_source_ids": [],
            "expected_package_refs": [],
            "negative_control": query.get("negative_control") is True,
            "independent_holdout": True,
            "holdout_hash": holdout_hash,
            "expected_rights_safe": True,
            "gate": "governed_corpus_independent_holdout",
        }
        rows.append(p0p8._public_payload(row))
    return sorted(rows, key=lambda row: str(row.get("query_id") or ""))


def _capability_gate_vector(
    policy: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> dict[str, list[str]]:
    if capabilities.get("schema_version") != RUNTIME_CAPABILITY_SCHEMA_VERSION_V2:
        return {
            "lightrag": _capability_gate_blockers_v1(policy, capabilities),
            "knowledge_hub": [],
        }

    decisions = runtime_evidence.recompute_gate_decisions(capabilities)
    lightrag_decision = decisions.get("lightrag_mutation", {})
    knowledge_hub_decision = decisions.get("knowledge_hub_promotion", {})
    lightrag_blockers = list(lightrag_decision.get("blockers", []))
    knowledge_hub_blockers = list(knowledge_hub_decision.get("blockers", []))
    policy_contract = (
        policy.get("capability_contract")
        if isinstance(policy.get("capability_contract"), Mapping)
        else {}
    )
    lightrag_contract = (
        policy_contract.get("lightrag")
        if isinstance(policy_contract.get("lightrag"), Mapping)
        else {}
    )
    kh_contract = (
        policy_contract.get("knowledge_hub")
        if isinstance(policy_contract.get("knowledge_hub"), Mapping)
        else {}
    )
    if (
        lightrag_contract.get("status") != "green"
        or lightrag_contract.get("mutation_eligible") is not True
    ):
        lightrag_blockers.append("lightrag_capability_policy_not_green")
    if (
        kh_contract.get("status") != "green"
        or kh_contract.get("promotion_eligible") is not True
    ):
        knowledge_hub_blockers.append("knowledge_hub_capability_policy_not_green")
    audit = (
        policy.get("audit_contract")
        if isinstance(policy.get("audit_contract"), Mapping)
        else {}
    )
    if audit.get("legacy_reconciliation") != "green":
        lightrag_blockers.append("lightrag_capability_legacy_reconciliation_not_green")
    return {
        "lightrag": _dedupe(lightrag_blockers),
        "knowledge_hub": _dedupe(knowledge_hub_blockers),
    }


def _capability_gate_blockers_v1(
    policy: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = ["runtime_capabilities_v1_legacy_positive_proof_unsupported"]
    policy_contract = (
        policy.get("capability_contract")
        if isinstance(policy.get("capability_contract"), Mapping)
        else {}
    )
    lightrag_contract = (
        policy_contract.get("lightrag")
        if isinstance(policy_contract.get("lightrag"), Mapping)
        else {}
    )
    if (
        lightrag_contract.get("mutation_eligible") is not True
        or lightrag_contract.get("status") != "green"
    ):
        blockers.append("lightrag_capability_policy_not_green")
    audit = (
        policy.get("audit_contract")
        if isinstance(policy.get("audit_contract"), Mapping)
        else {}
    )
    if audit.get("legacy_reconciliation") != "green":
        blockers.append("lightrag_capability_legacy_reconciliation_not_green")

    capability_rows = (
        capabilities.get("capabilities")
        if isinstance(capabilities.get("capabilities"), list)
        else []
    )
    available = {
        str(row.get("capability_id") or "")
        for row in capability_rows
        if isinstance(row, Mapping) and row.get("status") == "available"
    }
    for capability_id in sorted(REQUIRED_LIGHTRAG_CAPABILITIES - available):
        blockers.append(f"lightrag_capability_unavailable:{capability_id}")
    decisions = (
        capabilities.get("gate_decisions")
        if isinstance(capabilities.get("gate_decisions"), Mapping)
        else {}
    )
    lightrag_decision = (
        decisions.get("lightrag_mutation")
        if isinstance(decisions.get("lightrag_mutation"), Mapping)
        else {}
    )
    if lightrag_decision.get("decision") != "allowed":
        blockers.append("lightrag_capability_gate_blocked")
    return _dedupe(blockers)


def _effective_capability_decisions(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    if capabilities.get("schema_version") == RUNTIME_CAPABILITY_SCHEMA_VERSION_V2:
        return runtime_evidence.recompute_gate_decisions(capabilities)
    legacy_blocker = "runtime_capabilities_v1_legacy_positive_proof_unsupported"
    return {
        "p0_read_only": {"decision": "allowed", "mutation_allowed": False},
        "lightrag_mutation": {
            "decision": "blocked",
            "blockers": [legacy_blocker, *sorted(REQUIRED_LIGHTRAG_CAPABILITIES)],
        },
        "knowledge_hub_promotion": {
            "decision": "blocked",
            "blockers": [legacy_blocker, *sorted(POLICY_REQUIRED_KH_CAPABILITIES_V2)],
        },
    }


def _policy_gate_blockers(
    policy: Mapping[str, Any],
    profile: Mapping[str, Any],
    observed_inventory_digest: str,
    *,
    now: datetime | None = None,
) -> list[str]:
    blockers: list[str] = []
    current_time = now or _utc_now()
    value = (
        policy.get("value_contract")
        if isinstance(policy.get("value_contract"), Mapping)
        else {}
    )
    baseline = (
        value.get("baseline") if isinstance(value.get("baseline"), Mapping) else {}
    )
    candidate = (
        value.get("candidate") if isinstance(value.get("candidate"), Mapping) else {}
    )
    if value.get("status") != "frozen_green":
        blockers.append("value_contract_not_green")
    if not baseline.get("snapshot_id") or not baseline.get("captured_at"):
        blockers.append("value_baseline_not_captured")
    if value.get("status") == "frozen_green":
        if value.get("mutation_gate_open") is not True:
            blockers.append("value_mutation_gate_closed")
        holdout = (
            policy.get("holdout_contract")
            if isinstance(policy.get("holdout_contract"), Mapping)
            else {}
        )
        thresholds = (
            holdout.get("thresholds")
            if isinstance(holdout.get("thresholds"), Mapping)
            else {}
        )
        query_count = _safe_int(holdout.get("query_count"))
        required_numeric = {
            "routing_pass_count",
            "answer_criteria_pass_count",
            "negative_control_pass_count",
            "irrelevant_hit_rate_at_5",
            "estimated_cost_usd",
        }
        if not candidate.get("certificate_id") or not candidate.get("evaluated_at"):
            blockers.append("value_candidate_not_evaluated")
        if any(
            not _is_number(baseline.get(key)) or not _is_number(candidate.get(key))
            for key in required_numeric
        ):
            blockers.append("value_metrics_incomplete")
        else:
            if candidate["routing_pass_count"] < _safe_int(
                thresholds.get("topic_routing_pass_count_min")
            ):
                blockers.append("value_routing_threshold_not_met")
            if candidate["answer_criteria_pass_count"] < _safe_int(
                thresholds.get("answer_criteria_pass_count_min")
            ):
                blockers.append("value_answer_threshold_not_met")
            if candidate["negative_control_pass_count"] < _safe_int(
                thresholds.get("negative_control_pass_count_min")
            ):
                blockers.append("value_negative_control_threshold_not_met")
            normalized_gain = (
                (
                    float(candidate["answer_criteria_pass_count"])
                    - float(baseline["answer_criteria_pass_count"])
                )
                / query_count
                if query_count > 0
                else float("-inf")
            )
            if normalized_gain < float(
                value.get("minimum_absolute_answer_pass_gain") or 0
            ):
                blockers.append("value_normalized_answer_gain_not_met")
            if float(candidate["irrelevant_hit_rate_at_5"]) > float(
                value.get("maximum_irrelevant_hit_rate_at_5") or 0
            ):
                blockers.append("value_noise_ceiling_exceeded")
            incremental_cost = float(candidate["estimated_cost_usd"]) - float(
                baseline["estimated_cost_usd"]
            )
            if incremental_cost < 0 or incremental_cost > float(
                value.get("maximum_incremental_eval_cost_usd") or 0
            ):
                blockers.append("value_cost_ceiling_exceeded")
        for metric, threshold_key in (
            ("unsupported_current_claims", "unsupported_current_claims_max"),
            ("raw_source_body_leaks", "raw_source_body_leaks_max"),
            ("invented_evidence_claims", "invented_evidence_claims_max"),
        ):
            if not isinstance(candidate.get(metric), int) or candidate.get(
                metric
            ) > _safe_int(thresholds.get(threshold_key)):
                blockers.append(f"value_safety_threshold_not_met:{metric}")
    budget = (
        policy.get("budget_contract")
        if isinstance(policy.get("budget_contract"), Mapping)
        else {}
    )
    if (
        budget.get("status") != "active_reserved"
        or budget.get("activation_allowed") is not True
    ):
        blockers.append("budget_contract_not_active")
    if budget.get("reservation_status") != "reserved":
        blockers.append("budget_reservation_missing")
    if not SHA256_RE.fullmatch(str(budget.get("operator_instruction_hash") or "")):
        blockers.append("budget_authorization_incomplete")
    issued_at = _parse_utc_timestamp(budget.get("issued_at"))
    expires_at = _parse_utc_timestamp(budget.get("expires_at"))
    if (
        issued_at is None
        or expires_at is None
        or not (issued_at <= current_time < expires_at)
    ):
        blockers.append("budget_authorization_not_current")
    if budget.get("corpus_digest_sha256") != observed_inventory_digest:
        blockers.append("budget_corpus_digest_mismatch")
    if not budget.get("external_processing") or not budget.get("source_derived_fields"):
        blockers.append("budget_disclosure_contract_incomplete")
    provider_roles = (
        budget.get("provider_roles")
        if isinstance(budget.get("provider_roles"), list)
        else []
    )
    if any(
        not isinstance(row, Mapping)
        or row.get("rate_basis_status") != "materialized"
        or _safe_int(row.get("max_calls")) <= 0
        for row in provider_roles
    ):
        blockers.append("budget_provider_rate_basis_incomplete")
    required_roles = _required_provider_roles(profile)
    actual_roles = {
        str(row.get("role") or ""): (
            str(row.get("provider") or ""),
            str(row.get("model") or ""),
        )
        for row in provider_roles
        if isinstance(row, Mapping)
    }
    if actual_roles != required_roles:
        blockers.append("budget_provider_profile_binding_mismatch")
    if (
        not _is_number(budget.get("total_ceiling"))
        or float(budget.get("total_ceiling") or 0) <= 0
    ):
        blockers.append("budget_total_ceiling_not_positive")
    audit = (
        policy.get("audit_contract")
        if isinstance(policy.get("audit_contract"), Mapping)
        else {}
    )
    if audit.get("inventory_verified") is not True:
        blockers.append("inventory_audit_not_green")
    if audit.get("rights_certification") != "green":
        blockers.append("rights_audit_not_green")
    if audit.get("legacy_reconciliation") != "green":
        blockers.append("legacy_reconciliation_not_green")
    if audit.get("leak_scan") != "green":
        blockers.append("policy_leak_scan_not_green")
    if audit.get("p0_status") not in {"green_dry_run", "ready_for_p0"}:
        blockers.append("policy_p0_status_blocked")
    return _dedupe(blockers)


def _split_policy_gate_blockers(blockers: Sequence[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "inventory": [],
        "rights": [],
        "value": [],
        "budget": [],
        "legacy": [],
        "dependency": [],
        "leak": [],
    }
    for blocker in blockers:
        if blocker.startswith(("value_", "holdout_")):
            gate = "value"
        elif blocker.startswith("budget_"):
            gate = "budget"
        elif blocker in {
            "legacy_reconciliation_not_green",
            "lightrag_capability_legacy_reconciliation_not_green",
        }:
            gate = "legacy"
        elif blocker in {
            "inventory_audit_not_green",
            "inventory_audit_digest_mismatch",
        }:
            gate = "inventory"
        elif blocker == "rights_audit_not_green":
            gate = "rights"
        elif blocker in {"policy_leak_scan_not_green", "public_leak_detected"}:
            gate = "leak"
        else:
            gate = "dependency"
        groups[gate].append(blocker)
    return {key: _dedupe(value) for key, value in groups.items()}


def _split_contract_gate_blockers(
    blockers: Sequence[str],
) -> dict[str, list[str]]:
    """Assign every structural blocker to exactly one truthful gate owner."""

    groups: dict[str, list[str]] = {
        "inventory": [],
        "rights": [],
        "value": [],
        "budget": [],
        "legacy": [],
        "dependency": [],
        "leak": [],
        "lightrag": [],
        "knowledge_hub": [],
    }
    for blocker in blockers:
        gate = "dependency"
        capability_service = next(
            (
                spec.service_id
                for capability_id, spec in runtime_evidence.CAPABILITY_SPECS.items()
                if capability_id in blocker
            ),
            None,
        )
        if capability_service in {"lightrag", "knowledge_hub"}:
            gate = capability_service
        elif "knowledge_hub" in blocker:
            gate = "knowledge_hub"
        elif "lightrag" in blocker:
            gate = "lightrag"
        elif blocker.startswith(("value_", "holdout_")):
            gate = "value"
        elif blocker.startswith(
            ("evidence_generation_value", "evidence_generation_holdout")
        ):
            gate = "value"
        elif blocker.startswith("budget_"):
            gate = "budget"
        elif blocker.startswith(("inventory_", "source_root_")):
            gate = "inventory"
        elif blocker.startswith(
            (
                "authority_",
                "rights_",
                "evidence_generation_authority",
                "evidence_generation_origin",
                "evidence_generation_license",
                "evidence_generation_rights",
                "evidence_generation_source_rights",
                "evidence_generation_directory",
                "evidence_generation_ref_outside",
                "evidence_generation_trust_registry",
            )
        ):
            gate = "rights"
        elif blocker in {"input_manifest_public_leak", "policy_leak_scan_not_green"}:
            gate = "leak"
        elif "legacy_reconciliation" in blocker:
            gate = "legacy"
        groups[gate].append(blocker)
    return {key: _dedupe(value) for key, value in groups.items()}


def _finalize_run(
    config: GovernedCorpusConfig,
    *,
    contracts: LoadedContracts | None,
    phases: Sequence[PhaseResult],
    blockers: Sequence[str],
    input_leaks: Sequence[str],
    inventory: Sequence[Mapping[str, Any]],
    rights_registry: Sequence[Mapping[str, Any]],
    registry: Sequence[Mapping[str, Any]],
    visual_queue: Sequence[Mapping[str, Any]],
    cards: Sequence[Mapping[str, Any]],
    kh_plan: Sequence[Mapping[str, Any]],
    lightrag_plan: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
    cag_manifest: Sequence[Mapping[str, Any]],
    normalized: Sequence[Mapping[str, Any]],
    cag_candidates: Sequence[Mapping[str, Any]],
    eval_suite: Sequence[Mapping[str, Any]],
    independent_gate_blockers: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    all_blockers = _dedupe(
        [
            *blockers,
            *(blocker for phase in phases for blocker in phase.blockers),
        ]
    )
    observed_inventory_audit_digest = (
        inventory_audit_digest(inventory) if inventory else ""
    )
    policy_inventory_audit_digest = ""
    if contracts:
        inventory_contract = contracts.policy.get("inventory_contract")
        if isinstance(inventory_contract, Mapping):
            policy_inventory_audit_digest = str(
                inventory_contract.get("audit_digest_sha256") or ""
            )
    inventory_audit_digest_match = bool(
        policy_inventory_audit_digest
        and observed_inventory_audit_digest
        and policy_inventory_audit_digest == observed_inventory_audit_digest
    )
    if policy_inventory_audit_digest and not inventory_audit_digest_match:
        all_blockers.append("inventory_audit_digest_mismatch")
    if input_leaks:
        all_blockers.append("public_leak_detected")
    public_payload = {
        "inventory": list(inventory),
        "rights": list(rights_registry),
        "registry": list(registry),
        "visual_queue": list(visual_queue),
        "cards": list(cards),
        "kh_plan": list(kh_plan),
        "lightrag_plan": list(lightrag_plan),
        "crosswalk": list(crosswalk),
        "cag_manifest": list(cag_manifest),
        "normalized": list(normalized),
        "cag_candidates": list(cag_candidates),
        "eval_suite": list(eval_suite),
    }
    output_leaks = find_public_leaks(public_payload)
    if output_leaks:
        all_blockers.append("public_leak_detected")
    if any(card.get("raw_source_text_included") for card in cards):
        all_blockers.append("raw_source_text_included")
    if any(plan.get("mutation_performed") for plan in lightrag_plan) or any(
        plan.get("mutation_performed") for plan in kh_plan
    ):
        all_blockers.append("dry_run_mutation_detected")
    all_blockers = _dedupe(all_blockers)
    gate_blockers = (
        {key: _dedupe(value) for key, value in independent_gate_blockers.items()}
        if independent_gate_blockers is not None
        else None
    )
    if gate_blockers is not None:
        expected_gate_names = {
            "inventory",
            "rights",
            "value",
            "budget",
            "legacy",
            "dependency",
            "leak",
            "lightrag",
            "knowledge_hub",
        }
        if set(gate_blockers) != expected_gate_names:
            gate_blockers = {
                key: list(gate_blockers.get(key, []))
                for key in sorted(expected_gate_names)
            }
            gate_blockers["dependency"] = _dedupe(
                [*gate_blockers["dependency"], "independent_gate_vector_shape_invalid"]
            )
        gate_blockers["dependency"] = _dedupe([*gate_blockers["dependency"], *blockers])
        if policy_inventory_audit_digest and not inventory_audit_digest_match:
            gate_blockers["inventory"] = _dedupe(
                [*gate_blockers["inventory"], "inventory_audit_digest_mismatch"]
            )
        if input_leaks or output_leaks:
            gate_blockers["leak"] = _dedupe(
                [*gate_blockers["leak"], "public_leak_detected"]
            )
        if any(
            blocker in {"raw_source_text_included", "dry_run_mutation_detected"}
            for blocker in all_blockers
        ):
            gate_blockers["dependency"] = _dedupe(
                [
                    *gate_blockers["dependency"],
                    *(
                        blocker
                        for blocker in all_blockers
                        if blocker
                        in {"raw_source_text_included", "dry_run_mutation_detected"}
                    ),
                ]
            )
        p0_gate_names = {
            "inventory",
            "rights",
            "value",
            "legacy",
            "dependency",
            "leak",
            "lightrag",
        }
        ok = not any(gate_blockers[name] for name in p0_gate_names)
    else:
        ok = not all_blockers
    terminal_state = "green_dry_run" if ok else "blocked_no_mutation"
    corpus_digest = observed_inventory_audit_digest
    capability_decisions = {}
    kh_promotion_eligible = False
    source_manifest_hash = ""
    profile_hash = ""
    capabilities_hash = ""
    holdout_hash = ""
    corpus_id = ""
    policy_version = ""
    subject_revision = ""
    executable_tree_sha256 = ""
    subject_binding_verified = False
    if contracts:
        decisions = _effective_capability_decisions(contracts.capabilities)
        capability_decisions = p0p8._public_payload(
            decisions if isinstance(decisions, Mapping) else {}
        )
        source_manifest_hash = contracts.policy_hash
        profile_hash = contracts.profile_hash
        capabilities_hash = contracts.capabilities_hash
        holdout_hash = contracts.holdout_hash
        corpus_id = str(contracts.policy.get("corpus_id") or "")
        policy_version = str(contracts.policy.get("policy_version") or "")
        generation = contracts.policy.get("evidence_generation")
        if isinstance(generation, Mapping):
            subject_revision = str(generation.get("subject_revision") or "")
            executable_tree_sha256 = str(generation.get("executable_tree_sha256") or "")
            subject_binding_verified = bool(
                subject_revision
                and executable_tree_sha256
                and not any(
                    blocker.startswith(
                        (
                            "subject_",
                            "evidence_generation_subject_",
                            "runtime_capabilities_subject_",
                        )
                    )
                    for blocker in all_blockers
                )
            )

    counts = {
        "sources": len(inventory),
        "markdown_sources": sum(
            row.get("media_type") == "text/markdown" for row in inventory
        ),
        "png_sources": sum(row.get("media_type") == "image/png" for row in inventory),
        "eligible_sources": sum(
            bool(row.get("apply_eligible")) for row in rights_registry
        ),
        "blocked_sources": sum(
            not bool(row.get("apply_eligible")) for row in rights_registry
        ),
        "assets": len(registry),
        "cards": len(cards),
        "lightrag_plan_rows": len(lightrag_plan),
        "lightrag_planned_rows": sum(
            row.get("apply_status") == "planned" for row in lightrag_plan
        ),
        "kh_plan_rows": len(kh_plan),
        "visual_requests": len(visual_queue),
        "cag_packs": len(cag_manifest),
        "normalized_records": len(normalized),
        "cag_candidates": len(cag_candidates),
        "eval_queries": len(eval_suite),
        "provider_calls": 0,
        "source_writes": 0,
        "datastore_writes": 0,
        "leaks": len(input_leaks) + len(output_leaks),
    }
    policy = contracts.policy if contracts else {}
    generation = (
        policy.get("evidence_generation")
        if isinstance(policy.get("evidence_generation"), Mapping)
        else {}
    )
    value_contract = (
        policy.get("value_contract")
        if isinstance(policy.get("value_contract"), Mapping)
        else {}
    )
    budget_contract = (
        policy.get("budget_contract")
        if isinstance(policy.get("budget_contract"), Mapping)
        else {}
    )
    audit_contract = (
        policy.get("audit_contract")
        if isinstance(policy.get("audit_contract"), Mapping)
        else {}
    )
    gate_evidence: dict[str, Mapping[str, Any]] = {
        "inventory": {
            "observed_audit_digest_sha256": observed_inventory_audit_digest,
            "policy_audit_digest_sha256": policy_inventory_audit_digest,
            "digest_match": inventory_audit_digest_match,
            "source_count": len(inventory),
        },
        "rights": {
            "eligible_source_count": counts["eligible_sources"],
            "blocked_source_count": counts["blocked_sources"],
            "authority_sha256": str(generation.get("authority_sha256") or ""),
            "trust_registry_sha256": str(generation.get("trust_registry_sha256") or ""),
        },
        "value": {
            "status": str(value_contract.get("status") or "unavailable"),
            "candidate_evidence_sha256": str(
                value_contract.get("candidate_evidence_sha256") or ""
            ),
            "holdout_sha256": holdout_hash,
        },
        "budget": {
            "status": str(budget_contract.get("status") or "unavailable"),
            "reservation_status": str(
                budget_contract.get("reservation_status") or "unavailable"
            ),
            "activation_allowed": budget_contract.get("activation_allowed") is True,
        },
        "legacy": {
            "reconciliation_status": str(
                audit_contract.get("legacy_reconciliation") or "unavailable"
            )
        },
        "dependency": {
            "policy_sha256": source_manifest_hash,
            "production_profile_sha256": profile_hash,
            "runtime_capabilities_sha256": capabilities_hash,
            "subject_revision": subject_revision,
            "executable_tree_sha256": executable_tree_sha256,
            "subject_binding_verified": subject_binding_verified,
        },
        "leak": {
            "input_leak_count": len(input_leaks),
            "output_leak_count": len(output_leaks),
            "raw_source_text_included": any(
                card.get("raw_source_text_included") for card in cards
            ),
        },
        "lightrag": {
            "runtime_capabilities_sha256": capabilities_hash,
            "decision": capability_decisions.get("lightrag_mutation", {}),
        },
        "knowledge_hub": {
            "runtime_capabilities_sha256": capabilities_hash,
            "decision": capability_decisions.get("knowledge_hub_promotion", {}),
        },
    }
    downstream_scope = {
        "inventory": "p0_dry_run",
        "rights": "p0_dry_run",
        "value": "p0_dry_run",
        "budget": "p1_external_processing",
        "legacy": "p0_dry_run",
        "dependency": "p0_dry_run",
        "leak": "p0_dry_run",
        "lightrag": "p0_dry_run",
        "knowledge_hub": "knowledge_hub_promotion",
    }
    certification = {
        "schema_version": black_label.CERTIFICATION_SCHEMA_VERSION,
        "rollout_schema_version": SCHEMA_VERSION,
        "rollout_provenance": black_label.GOVERNED_ROLLOUT_PROVENANCE,
        "run_id": config.run_id,
        "corpus_id": corpus_id,
        "policy_version": policy_version,
        "corpus_digest": corpus_digest,
        "policy_inventory_audit_digest_sha256": policy_inventory_audit_digest,
        "observed_inventory_audit_digest_sha256": observed_inventory_audit_digest,
        "inventory_audit_digest_match": inventory_audit_digest_match,
        "source_run": p0p8._public_path(config.run_dir),
        "source_manifest_hash": source_manifest_hash,
        "production_profile_hash": profile_hash,
        "runtime_capabilities_hash": capabilities_hash,
        "holdout_hash": holdout_hash,
        "subject_revision": subject_revision,
        "executable_tree_sha256": executable_tree_sha256,
        "subject_binding_verified": subject_binding_verified,
        "ok": ok,
        "terminal_state": terminal_state,
        "dry_run": True,
        "mutation_performed": False,
        "provider_call_performed": False,
        "governed_p1_authorization": {
            "authorized": False,
            "separately_reviewed": False,
            "controller_ready": False,
        },
        "quality_bar": {
            "p0_green_dry_run": ok,
            "independent_holdout_required": True,
            "full_corpus_apply_allowed": False,
            "kh_promotion_eligible": kh_promotion_eligible,
        },
        "rollout_gates": {
            "gate_0_governed_dry_run": "pass" if ok else "blocked",
            "gate_1_lightrag_one_card_sample": (
                "blocked_p1_controller_not_implemented"
                if ok
                else "blocked_until_p0_green"
            ),
            "gate_2_lightrag_five_source_sample": (
                "blocked_p1_controller_not_implemented"
                if ok
                else "blocked_until_p0_green"
            ),
            "gate_3_lightrag_topic_cluster": (
                "blocked_p1_controller_not_implemented"
                if ok
                else "blocked_until_p0_green"
            ),
            "gate_4_knowledge_hub_promotion": (
                "blocked_separate_authorization_required"
                if ok
                else "blocked_until_p0_green"
            ),
            # Compatibility key consumed by the existing full-corpus guard.
            "gate_6_full_84_pdf_apply": "blocked_p0_only",
        },
        "capability_decisions": capability_decisions,
        "independent_gate_vector": (
            {
                name: {
                    "status": (
                        "no_go"
                        if name in {"budget", "knowledge_hub"} and gate_blockers[name]
                        else "blocked"
                        if gate_blockers[name]
                        else "pass"
                    ),
                    "blockers": gate_blockers[name],
                    "evidence": p0p8._public_payload(gate_evidence[name]),
                    "downstream_permission": {
                        "scope": downstream_scope[name],
                        "allowed": not gate_blockers[name],
                    },
                }
                for name in sorted(gate_blockers)
            }
            if gate_blockers is not None
            else None
        ),
        "counts": counts,
        "blockers": all_blockers,
        "leak_samples": list(input_leaks[:5]) + list(output_leaks[:5]),
    }
    certification = p0p8._public_payload(certification)
    _write_json(config.run_dir / "black-label-certification.json", certification)
    source_certification = {
        "schema_version": p0p8.CERTIFICATION_SCHEMA_VERSION,
        "rollout_schema_version": SCHEMA_VERSION,
        "rollout_provenance": black_label.GOVERNED_ROLLOUT_PROVENANCE,
        "run_id": config.run_id,
        "ok": ok,
        "dry_run": True,
        "mutation_performed": False,
        "governed_p1_authorization": {
            "authorized": False,
            "separately_reviewed": False,
            "controller_ready": False,
        },
        "terminal_state": terminal_state,
        "source_manifest_hash": source_manifest_hash,
        "subject_revision": subject_revision,
        "executable_tree_sha256": executable_tree_sha256,
        "subject_binding_verified": subject_binding_verified,
        "policy_inventory_audit_digest_sha256": policy_inventory_audit_digest,
        "observed_inventory_audit_digest_sha256": observed_inventory_audit_digest,
        "inventory_audit_digest_match": inventory_audit_digest_match,
        "counts": {
            "normalized_records": len(normalized),
            "crosswalk_rows": len(crosswalk),
            "cag_candidates": len(cag_candidates),
            "leaks": len(input_leaks) + len(output_leaks),
        },
        "blockers": all_blockers,
        "leak_samples": list(input_leaks[:5]) + list(output_leaks[:5]),
    }
    _write_json(
        config.run_dir / "p0-p8-certification.json",
        p0p8._public_payload(source_certification),
    )
    final_phase = PhaseResult(
        phase="P0-certify",
        name="governed-corpus-certification",
        status="complete" if ok else "blocked",
        output_paths=[
            "black-label-certification.json",
            "p0-p8-certification.json",
            "phase-ledger.json",
            "report.md",
        ],
        counts={key: int(value) for key, value in counts.items()},
        blockers=all_blockers,
    )
    all_phases = [*phases, final_phase]
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "run_id": config.run_id,
        "corpus_id": corpus_id,
        "corpus_digest": corpus_digest,
        "policy_inventory_audit_digest_sha256": policy_inventory_audit_digest,
        "observed_inventory_audit_digest_sha256": observed_inventory_audit_digest,
        "inventory_audit_digest_match": inventory_audit_digest_match,
        "terminal_state": terminal_state,
        "subject_revision": subject_revision,
        "executable_tree_sha256": executable_tree_sha256,
        "subject_binding_verified": subject_binding_verified,
        "dry_run": True,
        "mutation_performed": False,
        "provider_calls": 0,
        "source_writes": 0,
        "datastore_writes": 0,
        "phases": [asdict(phase) for phase in all_phases],
    }
    _write_json(config.run_dir / "phase-ledger.json", p0p8._public_payload(ledger))
    _write_report(config, certification)
    return certification


def _write_report(
    config: GovernedCorpusConfig, certification: Mapping[str, Any]
) -> None:
    counts = (
        certification.get("counts")
        if isinstance(certification.get("counts"), Mapping)
        else {}
    )
    blockers = (
        certification.get("blockers")
        if isinstance(certification.get("blockers"), list)
        else []
    )
    lines = [
        "# Governed Corpus P0 Report",
        "",
        f"- Run id: `{config.run_id}`",
        f"- Corpus id: `{certification.get('corpus_id', '')}`",
        f"- Terminal state: `{certification.get('terminal_state', 'blocked_no_mutation')}`",
        "- Dry run: `true`",
        "- Provider calls: `0`",
        "- Source writes: `0`",
        "- Datastore writes: `0`",
        f"- Accounted sources: `{counts.get('sources', 0)}`",
        f"- Eligible sources: `{counts.get('eligible_sources', 0)}`",
        f"- Cards: `{counts.get('cards', 0)}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- `{p0p8._public_string(str(blocker))}`" for blocker in blockers)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Mutation Boundary",
            "",
            "This P0 run performed no provider calls or source/datastore writes. Later LightRAG and Knowledge Hub stages are outside this module.",
            "",
        ]
    )
    _write_text_atomic(config.run_dir / "report.md", "\n".join(lines))


def _required_providers(profile: Mapping[str, Any]) -> set[str]:
    return {provider for provider, _model in _required_provider_roles(profile).values()}


def _required_provider_roles(profile: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    graph = (
        profile.get("graph_runtime")
        if isinstance(profile.get("graph_runtime"), Mapping)
        else {}
    )
    roles: dict[str, tuple[str, str]] = {}
    for role in ("extraction_and_merge", "embeddings", "retrieval_rerank"):
        row = graph.get(role) if isinstance(graph.get(role), Mapping) else {}
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if provider and model:
            roles[role] = (provider, model)
    return roles


def _is_safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("~"):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_bounded_text(value: Any, *, max_chars: int, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and (allow_empty or bool(value.strip()))
        and len(value) <= max_chars
    )


def _is_bounded_string_list(
    value: Any,
    *,
    max_items: int,
    max_chars: int = MAX_CURATED_LIST_ITEM_CHARS,
) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= max_items
        and all(
            _is_bounded_text(item, max_chars=max_chars, allow_empty=False)
            for item in value
        )
    )


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _resolve_json_pointer(payload: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    current = payload
    for encoded_part in pointer[1:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return current


def _mapping_contains_keys(value: Any, keys: set[str]) -> bool:
    if isinstance(value, Mapping):
        if keys & {str(key) for key in value}:
            return True
        return any(_mapping_contains_keys(item, keys) for item in value.values())
    if isinstance(value, list):
        return any(_mapping_contains_keys(item, keys) for item in value)
    return False


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _write_json(path: Path, value: Any) -> None:
    _write_text_atomic(
        path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    content = "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n" for row in rows
    )
    _write_text_atomic(path, content)


def _write_text_atomic(path: Path, content: str) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("artifact_parent_not_regular_directory")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _read_written_ledger(config: GovernedCorpusConfig) -> dict[str, Any]:
    return json.loads(
        (config.run_dir / "phase-ledger.json").read_text(encoding="utf-8")
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a provider-free governed corpus P0 dry-run."
    )
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--policy-manifest", type=Path, required=True)
    parser.add_argument(
        "--production-profile", type=Path, default=DEFAULT_PRODUCTION_PROFILE
    )
    parser.add_argument(
        "--runtime-capabilities", type=Path, default=DEFAULT_RUNTIME_CAPABILITIES
    )
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Unsupported; P0 is dry-run only and fails closed.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> GovernedCorpusConfig:
    return GovernedCorpusConfig(
        run_id=args.run_id,
        source_root=args.source_root,
        policy_manifest=args.policy_manifest,
        production_profile=args.production_profile,
        runtime_capabilities=args.runtime_capabilities,
        artifact_root=args.artifact_root,
        apply=args.apply,
    )


def config_to_argv(config: GovernedCorpusConfig) -> list[str]:
    argv = [
        "--run-id",
        config.run_id,
        "--source-root",
        str(config.source_root),
        "--policy-manifest",
        str(config.policy_manifest),
        "--production-profile",
        str(config.production_profile),
        "--runtime-capabilities",
        str(config.runtime_capabilities),
        "--artifact-root",
        str(config.artifact_root),
    ]
    if config.apply:
        argv.append("--apply")
    return argv


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = config_from_args(args)
    if config.apply:
        payload = {
            "run_id": config.run_id,
            "ok": False,
            "terminal_state": "blocked_no_mutation",
            "blockers": ["apply_mode_not_implemented_for_governed_corpus_rollout"],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    try:
        result = run_all(config)
    except (FileExistsError, ValueError) as exc:
        payload = {
            "run_id": config.run_id,
            "ok": False,
            "terminal_state": "blocked_no_mutation",
            "blockers": [p0p8._public_string(str(exc))],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    certification = result["certification"]
    print(
        json.dumps(
            {
                "run_id": config.run_id,
                "run_dir": p0p8._public_path(config.run_dir),
                "ok": certification.get("ok"),
                "terminal_state": certification.get("terminal_state"),
                "blockers": certification.get("blockers", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if certification.get("terminal_state") == "green_dry_run" else 2


if __name__ == "__main__":
    raise SystemExit(main())
