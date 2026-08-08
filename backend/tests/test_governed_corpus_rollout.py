from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import governed_corpus_rollout as subject


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(autouse=True)
def isolated_repository_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository_root = tmp_path / "repository"
    (repository_root / "logs").mkdir(parents=True)
    monkeypatch.setattr(subject.p0p8, "DEFAULT_PUBLIC_ROOT", repository_root)


def capability_profile() -> dict:
    return {
        "schema_version": subject.PRODUCTION_PROFILE_SCHEMA_VERSION,
        "profile_id": "fixture-production-profile",
        "status": "active",
        "graph_runtime": {
            "extraction_and_merge": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
            },
            "embeddings": {"provider": "voyage", "model": "voyage-4-large"},
            "retrieval_rerank": {
                "provider": "cohere",
                "model": "rerank-v4.0-pro",
                "retrieval_only": True,
            },
        },
        "ingestion_policy": {
            "accepted_unit": "rights_safe_curated_card",
            "raw_book_markdown_allowed": False,
            "binary_media_in_lightrag_allowed": False,
            "direct_datastore_writes_allowed": False,
            "credentials_may_be_persisted_in_manifests": False,
        },
        "rollout": [
            {"order": 1, "stage": "one_document_sample", "requires": []},
            {"order": 2, "stage": "five_document_sample", "requires": []},
            {"order": 3, "stage": "topic_cluster_sample", "requires": []},
            {"order": 4, "stage": "full_corpus_after_certification", "requires": []},
        ],
    }


def runtime_capabilities(profile_path: Path, *, lightrag_allowed: bool = True) -> dict:
    required = {
        "lightrag.legacy_identity_reconciliation",
        "lightrag.authoritative_payload_hash_lookup",
        "lightrag.service_enforced_fencing",
    }
    capabilities = [
        {
            "capability_id": capability_id,
            "status": "available" if lightrag_allowed else "unavailable",
            "blocking": not lightrag_allowed,
            "scope": "lightrag_mutation",
            "evidence_refs": [
                f"/live_read_only_observations/lightrag/{capability_id.rsplit('.', 1)[-1]}"
            ],
        }
        for capability_id in sorted(required)
    ]
    return {
        "schema_version": subject.RUNTIME_CAPABILITY_SCHEMA_VERSION,
        "manifest_id": "fixture-runtime-capabilities",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_mode": "redacted_read_only",
        "policy": {
            "allowed_statuses": ["available", "unavailable", "not_provable"],
            "not_provable_is_blocking": True,
            "live_mutation_attempted": False,
            "promotion_attempted": False,
        },
        "dependency_provenance": {
            "repository_head": {"revision": "a" * 40, "state": "committed_head"},
            "production_profile": {
                "artifact_ref": profile_path.name,
                "approval_basis": "approved_snapshot_artifact",
                "approval_snapshot_id": "fixture",
                "sha256": subject.sha256_file(profile_path),
                "verification": "hash_match",
            },
        },
        "redaction_contract": {
            "absolute_paths_included": False,
            "private_endpoint_values_included": False,
            "credentials_or_sessions_included": False,
            "raw_provider_or_service_responses_included": False,
            "document_content_included": False,
        },
        "live_read_only_observations": {
            "lightrag": {
                capability_id.rsplit(".", 1)[-1]: {
                    "status": "observed",
                    **subject.REQUIRED_LIGHTRAG_CAPABILITY_PROOFS[capability_id],
                }
                for capability_id in required
            }
        },
        "capabilities": capabilities,
        "gate_decisions": {
            "p0_read_only": {"decision": "allowed", "mutation_allowed": False},
            "lightrag_mutation": {
                "decision": "allowed" if lightrag_allowed else "blocked",
                "blockers": [] if lightrag_allowed else sorted(required),
            },
            "knowledge_hub_promotion": {
                "decision": "blocked",
                "blockers": ["fixture-deferred"],
            },
        },
    }


def eligible_rights() -> dict:
    return {
        "rights_status": "verified_clear",
        "rights_basis": "fixture operator-authored source",
        "permitted_local_uses": ["local_embedding", "derived_summary"],
        "external_processing": True,
        "allowed_providers": ["deepseek", "voyage", "cohere"],
        "allowed_regions": ["approved-fixture-region"],
        "allowed_source_derived_fields": [
            "title",
            "summary",
            "heading_seeds",
            "relationships",
        ],
        "evidence_refs": [],
        "evidence_predicates": {
            "provenance_present": True,
            "hash_bound_rights_record_present": True,
            "rightsholder_authority_proven": True,
            "local_embedding_permission_explicit": True,
            "derived_summary_permission_explicit": True,
            "external_provider_disclosure_permission_explicit": True,
            "generated_output_use_terms_preserved": True,
            "registered_asset_or_likeness_attestation_present": True,
        },
        "rights_evidence_sha256": None,
        "review_date": "2026-08-08",
        "reviewer_id": "fixture-reviewer",
        "apply_eligible": True,
        "blocking_reasons": [],
    }


def source_entry(
    relative_path: str,
    body: bytes,
    *,
    role: str,
    topic: str,
    rights: dict | None = None,
) -> dict:
    source_sha = sha256_bytes(body)
    rights_payload = rights or eligible_rights()
    return {
        "relative_path": relative_path,
        "media_type": "image/png"
        if relative_path.endswith(".png")
        else "text/markdown",
        "size_bytes": len(body),
        "source_sha256": source_sha,
        "source_id": f"source_{source_sha[:20]}",
        "package_id": f"package_{source_sha[:20]}",
        "source_class_id": "fixture-authored",
        "topic_id": topic,
        "card_role": role,
        "risk_rank": 10,
        "inventory_disposition": "selected"
        if rights_payload["apply_eligible"]
        else "blocked",
        **rights_payload,
    }


def materialize_rights_evidence(parent: Path, sources: list[dict]) -> None:
    evidence_fields = {
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
    for index, source in enumerate(sources):
        if source["apply_eligible"] is not True:
            source["evidence_refs"] = []
            source["rights_evidence_sha256"] = None
            continue
        ref = f"evidence/rights-{index}.json"
        evidence = {"schema_version": subject.RIGHTS_EVIDENCE_SCHEMA_VERSION}
        evidence.update({key: source[key] for key in evidence_fields})
        evidence_path = parent / ref
        write_json(evidence_path, evidence)
        source["evidence_refs"] = [ref]
        source["rights_evidence_sha256"] = subject.sha256_file(evidence_path)


def refresh_rights_evidence(parent: Path, source: dict) -> None:
    ref = source["evidence_refs"][0]
    evidence = {
        "schema_version": subject.RIGHTS_EVIDENCE_SCHEMA_VERSION,
        **{
            key: source[key]
            for key in (
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
            )
        },
    }
    evidence_path = parent / ref
    write_json(evidence_path, evidence)
    source["rights_evidence_sha256"] = subject.sha256_file(evidence_path)


def materialize_value_evidence(
    parent: Path,
    policy: dict,
    profile_path: Path,
    capabilities_path: Path,
) -> None:
    value = policy["value_contract"]
    candidate = value["candidate"]
    artifact_ref = "evidence/value-eval-results.json"
    artifact_path = parent / artifact_ref
    write_json(
        artifact_path,
        {
            "schema_version": "fixture.governed_eval_results.v1",
            "candidate_metrics": {
                key: candidate[key] for key in subject.VALUE_CANDIDATE_METRIC_KEYS
            },
        },
    )
    artifact_manifest_ref = "evidence/value-artifacts.json"
    artifact_manifest_path = parent / artifact_manifest_ref
    write_json(
        artifact_manifest_path,
        {
            "schema_version": subject.VALUE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
            "artifacts": [
                {
                    "artifact_ref": artifact_ref,
                    "sha256": subject.sha256_file(artifact_path),
                }
            ],
        },
    )
    capabilities = json.loads(capabilities_path.read_text(encoding="utf-8"))
    certificate_ref = "evidence/value-certificate.json"
    certificate_path = parent / certificate_ref
    write_json(
        certificate_path,
        {
            "schema_version": subject.VALUE_EVIDENCE_SCHEMA_VERSION,
            "certificate_id": candidate["certificate_id"],
            "evaluated_at": candidate["evaluated_at"],
            "evaluated_repository_revision": capabilities["dependency_provenance"][
                "repository_head"
            ]["revision"],
            "corpus_digest_sha256": policy["inventory_contract"]["audit_digest_sha256"],
            "holdout_sha256": policy["holdout_contract"]["contract_sha256"],
            "production_profile_sha256": subject.sha256_file(profile_path),
            "runtime_capabilities_sha256": subject.sha256_file(capabilities_path),
            "candidate_metrics": {
                key: candidate[key] for key in subject.VALUE_CANDIDATE_METRIC_KEYS
            },
            "artifact_manifest_ref": artifact_manifest_ref,
            "artifact_manifest_sha256": subject.sha256_file(artifact_manifest_path),
        },
    )
    value["candidate_evidence_ref"] = certificate_ref
    value["candidate_evidence_sha256"] = subject.sha256_file(certificate_path)


def policy_manifest(sources: list[dict], *, capability_green: bool = True) -> dict:
    markdown_count = sum(row["media_type"] == "text/markdown" for row in sources)
    png_count = sum(row["media_type"] == "image/png" for row in sources)
    topic_counts = Counter(row["topic_id"] for row in sources)
    holdout = {
        "contract_id": "fixture-independent-holdout.v1",
        "authored_from": "operator_facing_source_intent_only",
        "frozen_before_card_generation": True,
        "generated_card_content_allowed": False,
        "query_count": 1,
        "negative_control_ids": ["H1"],
        "thresholds": {
            "topic_routing_pass_count_min": 1,
            "answer_criteria_pass_count_min": 1,
            "negative_control_pass_count_min": 1,
            "unsupported_current_claims_max": 0,
            "raw_source_body_leaks_max": 0,
            "invented_evidence_claims_max": 0,
        },
        "queries": [
            {
                "holdout_id": "H1",
                "query": "Which unrelated accounting rule applies?",
                "expected_topic_ids": ["camera"],
                "answer_criteria": ["abstains from unrelated claims"],
                "negative_control": True,
            }
        ],
        "digest_algorithm": "sha256",
        "digest_scope": "canonical_json_of_thresholds_and_queries",
        "contract_sha256": "",
    }
    holdout["contract_sha256"] = subject.holdout_digest(holdout)
    return {
        "schema_version": subject.POLICY_SCHEMA_VERSION,
        "corpus_id": "fixture-corpus",
        "policy_version": "2026-08-08.v1",
        "policy_status": "frozen",
        "source_root_contract": {
            "runtime_argument_required": True,
            "relative_path_base": "runtime_source_root",
            "read_only": True,
            "persist_source_root": False,
            "allow_symlinks": False,
            "allow_unlisted_files": False,
            "allowed_extensions": [".md", ".png"],
        },
        "inventory_contract": {
            "sort_key": "relative_path",
            "digest_input_format": "relative_path<TAB>size_bytes<TAB>source_sha256<LF>",
            "hash_algorithm": "sha256",
            "expected_markdown_count": markdown_count,
            "expected_png_count": png_count,
            "expected_file_count": len(sources),
            "expected_total_size_bytes": sum(row["size_bytes"] for row in sources),
            "audit_digest_sha256": subject.inventory_audit_digest(sources),
        },
        "source_classes": [
            {
                "source_class_id": "fixture-authored",
                "description": "Operator-authored fixture.",
                "expected_member_count": len(sources),
                "evidence_available": "Hash-bound fixture rights record.",
                "required_true_predicates": sorted(
                    subject.UNIVERSAL_EVIDENCE_PREDICATES
                    | subject.PROVIDER_EVIDENCE_PREDICATES
                ),
                "current_rights_status": "verified_clear",
                "permitted_local_uses": ["local_embedding", "derived_summary"],
                "external_processing": True,
                "adjudication_reason": "Fixture exercises the eligible path.",
            }
        ],
        "topics": [
            {
                "topic_id": topic_id,
                "description": f"Fixture {topic_id} topic.",
                "expected_member_count": count,
                "membership_rule": "source.topic_id_exact_match",
            }
            for topic_id, count in sorted(topic_counts.items())
        ],
        "stage_contract": {
            "gate_1": {
                "required_card_role": "source_card",
                "cumulative_unique_source_count": 1,
                "selection_rule": "lowest_numeric_risk_rank_among_eligible_sources",
            },
            "gate_2": {
                "cumulative_unique_source_count": 5,
                "required_new_unique_source_count": 4,
                "selection_rule": "deterministic_role_and_size_stratification_without_repeated_source_fallback",
            },
            "gate_3": {
                "topic_id": "camera",
                "minimum_new_sources": 1,
                "minimum_relationship_patterns": 1,
                "existing_members_are_noop": True,
            },
            "full_apply": {
                "requires_independent_holdout": True,
                "requires_fresh_rehearsed_checkpoint": True,
                "requires_zero_unresolved_conflicts_in_eligible_set": True,
            },
        },
        "sources": sources,
        "value_contract": {
            "contract_id": "fixture-value.v1",
            "status": "frozen_green",
            "authored_from": "operator_facing_source_intent_only",
            "hypothesis": "The fixture should improve bounded camera craft retrieval.",
            "operator_workflows": ["camera craft retrieval"],
            "baseline": {
                "snapshot_id": "fixture-baseline",
                "captured_at": "2026-08-08T00:00:00Z",
                "routing_pass_count": 0,
                "answer_criteria_pass_count": 0,
                "negative_control_pass_count": 1,
                "irrelevant_hit_rate_at_5": 0.1,
                "estimated_cost_usd": 0,
            },
            "candidate": {
                "certificate_id": "fixture-candidate",
                "evaluated_at": "2026-08-08T01:00:00Z",
                "routing_pass_count": 1,
                "answer_criteria_pass_count": 1,
                "negative_control_pass_count": 1,
                "irrelevant_hit_rate_at_5": 0.1,
                "estimated_cost_usd": 0.5,
                "unsupported_current_claims": 0,
                "raw_source_body_leaks": 0,
                "invented_evidence_claims": 0,
            },
            "candidate_evidence_ref": None,
            "candidate_evidence_sha256": None,
            "minimum_absolute_answer_pass_gain": 0.1,
            "maximum_irrelevant_hit_rate_at_5": 0.2,
            "maximum_incremental_eval_cost_usd": 1.0,
            "mutation_gate_open": True,
        },
        "holdout_contract": holdout,
        "budget_contract": {
            "contract_id": "fixture-budget.v1",
            "status": "active_reserved",
            "activation_allowed": True,
            "blocked_by": [],
            "currency": "USD",
            "corpus_digest_sha256": subject.inventory_audit_digest(sources),
            "operator_instruction_hash": "f" * 64,
            "issued_at": "2026-01-01T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "provider_roles": [
                {
                    "role": role,
                    "provider": provider,
                    "model": model,
                    "rate_basis_status": "materialized",
                    "rate_unit": "token",
                    "rate_amount": 0.001,
                    "max_calls": 10,
                    "max_input_tokens": 10000,
                    "max_output_tokens": 1000,
                }
                for role, provider, model in (
                    ("extraction_and_merge", "deepseek", "deepseek-v4-pro"),
                    ("embeddings", "voyage", "voyage-4-large"),
                    ("retrieval_rerank", "cohere", "rerank-v4.0-pro"),
                )
            ],
            "total_ceiling": 1.0,
            "reservation_status": "reserved",
            "source_derived_fields": [
                "title",
                "summary",
                "heading_seeds",
                "relationships",
            ],
            "external_processing": True,
            "reactivation_requirements": [],
        },
        "capability_contract": {
            "audit_mode": "read_only",
            "lightrag": {
                "status": "green" if capability_green else "blocked",
                "required_capabilities": sorted(
                    subject.POLICY_REQUIRED_LIGHTRAG_CAPABILITIES
                ),
                "mutation_eligible": capability_green,
            },
            "knowledge_hub": {
                "status": "deferred",
                "required_capabilities": [],
                "promotion_eligible": False,
            },
        },
        "audit_contract": {
            "mode": "read_only",
            "provider_calls": 0,
            "source_writes": 0,
            "datastore_writes": 0,
            "inventory_verified": True,
            "rights_certification": "green",
            "legacy_reconciliation": "green" if capability_green else "blocked",
            "leak_scan": "green",
            "p0_status": "green_dry_run" if capability_green else "blocked_no_mutation",
            "p1_status": "no_go",
        },
    }


def make_fixture(
    tmp_path: Path,
    *,
    eligible: bool = True,
    lightrag_allowed: bool = True,
    markdown_body: bytes | None = None,
) -> subject.GovernedCorpusConfig:
    source_root = tmp_path / "source"
    markdown = (
        markdown_body
        or b"# Raw marker that must never enter artifacts\n\nSensitive source body.\n"
    )
    image = b"\x89PNG\r\n\x1a\nfixture-binary-marker"
    (source_root / "01-notes").mkdir(parents=True)
    (source_root / "03-assets").mkdir(parents=True)
    (source_root / "01-notes" / "guide.md").write_bytes(markdown)
    (source_root / "03-assets" / "frame.png").write_bytes(image)

    rights = eligible_rights()
    if not eligible:
        rights = {
            **rights,
            "rights_status": "unknown",
            "rights_basis": "insufficient evidence",
            "permitted_local_uses": [],
            "external_processing": False,
            "allowed_providers": [],
            "allowed_regions": [],
            "allowed_source_derived_fields": [],
            "rights_evidence_sha256": None,
            "apply_eligible": False,
            "blocking_reasons": ["rights_unknown"],
        }
        rights["evidence_predicates"] = {
            key: False for key in rights["evidence_predicates"]
        }
        rights["evidence_refs"] = []

    sources = [
        source_entry(
            "01-notes/guide.md",
            markdown,
            role="source_card",
            topic="camera",
            rights=rights,
        ),
        source_entry(
            "03-assets/frame.png",
            image,
            role="visual_evidence_card",
            topic="visual",
            rights=rights,
        ),
    ]
    profile_path = tmp_path / "profile.json"
    write_json(profile_path, capability_profile())
    capabilities_path = tmp_path / "runtime-capabilities.json"
    write_json(
        capabilities_path,
        runtime_capabilities(profile_path, lightrag_allowed=lightrag_allowed),
    )
    policy_path = tmp_path / "policy.json"
    materialize_rights_evidence(policy_path.parent, sources)
    policy = policy_manifest(sources, capability_green=lightrag_allowed)
    materialize_value_evidence(
        policy_path.parent, policy, profile_path, capabilities_path
    )
    write_json(policy_path, policy)
    return subject.GovernedCorpusConfig(
        run_id="fixture-run",
        source_root=source_root,
        policy_manifest=policy_path,
        production_profile=profile_path,
        runtime_capabilities=capabilities_path,
        artifact_root=subject.p0p8.DEFAULT_PUBLIC_ROOT
        / "logs"
        / "fixtures"
        / tmp_path.name,
    )


def test_legacy_v1_run_emits_complete_fail_closed_artifacts_without_raw_content(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert (
        "runtime_capabilities_v1_legacy_positive_proof_unsupported"
        in result["certification"]["blockers"]
    )
    assert result["certification"]["mutation_performed"] is False
    assert result["certification"]["counts"]["provider_calls"] == 0
    inventory = read_jsonl(config.run_dir / "governed-source-inventory.jsonl")
    expected_digest = subject.inventory_audit_digest(inventory)
    assert result["certification"]["corpus_digest"] == expected_digest
    assert (
        result["certification"]["policy_inventory_audit_digest_sha256"]
        == expected_digest
    )
    assert (
        result["certification"]["observed_inventory_audit_digest_sha256"]
        == expected_digest
    )
    assert result["certification"]["inventory_audit_digest_match"] is True
    expected = {
        "governed-source-inventory.jsonl",
        "governed-rights-registry.jsonl",
        "p0-p8-certification.json",
        "docling-normalized-output.jsonl",
        "package-crosswalk.jsonl",
        "cag-pack-candidates.jsonl",
        "black-label-asset-registry.jsonl",
        "docling-pdf-page-image-crosswalk.jsonl",
        "visual-enrichment-queue.jsonl",
        "black-label-card-manifest.jsonl",
        "kh-multimodal-apply-plan.jsonl",
        "lightrag-card-apply-plan.jsonl",
        "cag-pack-manifest.jsonl",
        "black-label-eval-suite.jsonl",
        "black-label-certification.json",
        "phase-ledger.json",
        "report.md",
    }
    assert expected <= {path.name for path in config.run_dir.iterdir()}
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in config.run_dir.iterdir()
    )
    assert "Sensitive source body" not in serialized
    assert "fixture-binary-marker" not in serialized
    assert str(tmp_path.resolve()) not in serialized
    assert not subject.find_public_leaks(serialized)

    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    crosswalk = read_jsonl(config.run_dir / "package-crosswalk.jsonl")
    cag_candidates = read_jsonl(config.run_dir / "cag-pack-candidates.jsonl")
    plans = read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    assert len(normalized) == len(crosswalk) == 2
    assert {row["schema_version"] for row in normalized} == {
        "docling_normalized_output.v1"
    }
    assert all(row["apply_status"] == "blocked" for row in plans)
    assert all(row["blocked_reason"] == "p0_gate_blocked" for row in plans)
    assert all(row["status"] == "blocked" for row in cag_candidates)
    source_certification = json.loads(
        (config.run_dir / "p0-p8-certification.json").read_text(encoding="utf-8")
    )
    assert source_certification["rollout_schema_version"] == subject.SCHEMA_VERSION
    assert source_certification["governed_p1_authorization"] == {
        "authorized": False,
        "separately_reviewed": False,
        "controller_ready": False,
    }


def test_finalization_merges_phase_and_certification_blockers_once(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)
    subject._prepare_run_directory(config)

    certification = subject._finalize_run(
        config,
        contracts=None,
        phases=[
            subject.PhaseResult(
                phase="P0-test",
                name="phase-blocker-test",
                status="blocked",
                blockers=["phase_only", "shared"],
            )
        ],
        blockers=["shared", "certification_only"],
        input_leaks=[],
        inventory=[],
        rights_registry=[],
        registry=[],
        visual_queue=[],
        cards=[],
        kh_plan=[],
        lightrag_plan=[],
        crosswalk=[],
        cag_manifest=[],
        normalized=[],
        cag_candidates=[],
        eval_suite=[],
    )

    assert certification["blockers"] == ["shared", "certification_only", "phase_only"]
    assert certification["terminal_state"] == "blocked_no_mutation"


def test_malformed_null_source_list_fails_closed_without_crashing(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["sources"] = None
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert "policy_sources_invalid" in result["certification"]["blockers"]
    gate_vector = result["certification"]["independent_gate_vector"]
    assert gate_vector is not None
    assert all(
        gate["downstream_permission"]["allowed"] is False
        for gate in gate_vector.values()
    )
    assert all(gate["blockers"] for gate in gate_vector.values())


def test_global_v2_authority_failure_preserves_inventory_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["schema_version"] = subject.POLICY_SCHEMA_VERSION_V2
    write_json(config.policy_manifest, policy)
    monkeypatch.setattr(subject, "_validate_policy", lambda _policy: [])
    monkeypatch.setattr(
        subject,
        "_validate_evidence_generation_files",
        lambda *_args, **_kwargs: ["authority_observation_schema_invalid"],
    )

    result = subject.run_all(config)
    inventory = read_jsonl(config.run_dir / "governed-source-inventory.jsonl")
    rights = read_jsonl(config.run_dir / "governed-rights-registry.jsonl")

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert len(inventory) == len(rights) == 2
    assert all(row["apply_eligible"] is False for row in rights)
    assert "authority_observation_schema_invalid" in result["certification"][
        "blockers"
    ]


def test_final_source_reconciliation_detects_post_snapshot_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_fixture(tmp_path)
    original = subject._build_cards

    def build_then_mutate(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        source_path = config.source_root / "01-notes" / "guide.md"
        source_path.write_text("changed after inventory snapshot\n", encoding="utf-8")
        return result

    monkeypatch.setattr(subject, "_build_cards", build_then_mutate)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert any(
        blocker.startswith("source_reconciliation_content_drift:")
        for blocker in result["certification"]["blockers"]
    )


def test_final_contract_reconciliation_detects_policy_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_fixture(tmp_path)
    original = subject._build_cards

    def build_then_delete_policy(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        config.policy_manifest.unlink()
        return result

    monkeypatch.setattr(subject, "_build_cards", build_then_delete_policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert "final_policy_manifest_missing" in result["certification"]["blockers"]


def test_unknown_rights_remain_accounted_and_block_all_apply_rows(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path, eligible=False)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    inventory = read_jsonl(config.run_dir / "governed-source-inventory.jsonl")
    rights = read_jsonl(config.run_dir / "governed-rights-registry.jsonl")
    plans = read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    assert len(inventory) == len(rights) == 2
    assert {row["rights_status"] for row in rights} == {"unknown"}
    assert all(row["apply_status"] == "blocked" for row in plans)
    assert all(row["blocked_reason"] == "p0_gate_blocked" for row in plans)
    compatibility_certification = json.loads(
        (config.run_dir / "p0-p8-certification.json").read_text(encoding="utf-8")
    )
    assert compatibility_certification["ok"] is False
    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    cag_candidates = read_jsonl(config.run_dir / "cag-pack-candidates.jsonl")
    assert all(
        row["status"] == row["quality_status"] == row["rights_status"] == "blocked"
        for row in normalized
    )
    assert all(
        row["status"] == "blocked" and not row["evidence_package_keys"]
        for row in cag_candidates
    )
    with pytest.raises(ValueError, match="black_label_source_not_certified"):
        subject.black_label.load_source_bundle(
            subject.black_label.BlackLabelConfig(
                run_id="blocked-source-bundle", source_run=config.run_dir
            )
        )


@pytest.mark.parametrize("bad_path", ["../escape.md", "/tmp/private.md", "script.py"])
def test_invalid_or_unallowlisted_path_blocks_before_card_generation(
    tmp_path: Path, bad_path: str
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["sources"][0]["relative_path"] = bad_path
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert not (config.run_dir / "black-label-card-manifest.jsonl").exists()


def test_symlink_escape_and_hash_drift_fail_closed(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    linked = config.source_root / "01-notes" / "guide.md"
    linked.unlink()
    linked.symlink_to(outside)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert any(
        "source_symlink" in blocker or "source_path_escape" in blocker
        for blocker in result["certification"]["blockers"]
    )

    linked.unlink()
    linked.write_text("changed bytes", encoding="utf-8")
    second = subject.run_all(replace(config, run_id="hash-drift"))
    assert any(
        "source_hash_mismatch" in blocker
        for blocker in second["certification"]["blockers"]
    )
    assert second["certification"]["inventory_audit_digest_match"] is False
    assert (
        second["certification"]["policy_inventory_audit_digest_sha256"]
        != second["certification"]["observed_inventory_audit_digest_sha256"]
    )
    assert not (
        second["certification"]
        and config.artifact_root / "hash-drift" / "black-label-card-manifest.jsonl"
    ).exists()


def test_logical_card_id_is_stable_while_revision_changes(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    subject.run_all(config)
    first = next(
        row
        for row in read_jsonl(config.run_dir / "black-label-card-manifest.jsonl")
        if row["card_role"] == "source_card"
    )

    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["source_classes"][0]["description"] = "A revised bounded fixture summary."
    write_json(config.policy_manifest, policy)
    revised = replace(config, run_id="revised-run")
    subject.run_all(revised)
    second = next(
        row
        for row in read_jsonl(revised.run_dir / "black-label-card-manifest.jsonl")
        if row["card_role"] == "source_card"
    )

    assert first["card_id"] == second["card_id"]
    assert first["payload_hash"] != second["payload_hash"]
    assert first["revision_id"] != second["revision_id"]
    assert first["file_source"] == second["file_source"]


def test_holdout_is_consumed_without_mutation_or_generated_answer_leak(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)
    before = config.policy_manifest.read_bytes()

    subject.run_all(config)

    assert config.policy_manifest.read_bytes() == before
    eval_rows = read_jsonl(config.run_dir / "black-label-eval-suite.jsonl")
    assert eval_rows
    assert all(row["independent_holdout"] is True for row in eval_rows)
    assert all("expected_answer" not in row for row in eval_rows)


@pytest.mark.parametrize(
    "leak_field",
    ["holdout_id", "query", "expected_topic_ids", "answer_criteria"],
)
def test_holdout_source_body_reuse_is_redacted_from_all_run_artifacts_and_blocks(
    tmp_path: Path,
    leak_field: str,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    raw_body = (config.source_root / "01-notes" / "guide.md").read_text(
        encoding="utf-8"
    )
    policy["holdout_contract"]["queries"][0][leak_field] = (
        [raw_body]
        if leak_field in {"expected_topic_ids", "answer_criteria"}
        else raw_body
    )
    policy["holdout_contract"]["contract_sha256"] = subject.holdout_digest(
        policy["holdout_contract"]
    )
    materialize_value_evidence(
        config.policy_manifest.parent,
        policy,
        config.production_profile,
        config.runtime_capabilities,
    )
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in config.run_dir.iterdir()
        if path.is_file()
    )
    eval_rows = read_jsonl(config.run_dir / "black-label-eval-suite.jsonl")
    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert "holdout_query_raw_source_body_reuse" in result["certification"]["blockers"]
    assert eval_rows[0]["query"] == subject.REDACTED_HOLDOUT_QUERY
    assert eval_rows[0]["query_id"].startswith("redacted_")
    assert eval_rows[0]["expected_topic_ids"] == []
    assert raw_body.strip() not in serialized
    assert "Sensitive source body" not in serialized


def test_short_markdown_body_is_detected_in_metadata_and_holdout(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    relative_path = "short.md"
    raw_body = "Crown launch note: ember."
    (source_root / relative_path).write_text(raw_body, encoding="utf-8")
    inventory = [
        {
            "relative_path": relative_path,
            "verification_status": "verified",
            "media_type": "text/markdown",
            "source_class_id": "notes",
            "topic_id": "launch",
        }
    ]
    policy = {
        "sources": [{"relative_path": relative_path, "declared_summary": raw_body}],
        "source_classes": [
            {
                "source_class_id": "notes",
                "description": "Independent class description.",
            }
        ],
        "topics": [
            {"topic_id": "launch", "description": "Independent topic description."}
        ],
    }
    holdout = {"queries": [{"query": raw_body}]}

    bodies = subject._normalized_markdown_bodies(inventory, source_root)

    assert bodies == [raw_body]
    assert subject._find_raw_body_metadata_paths(policy, inventory, bodies) == {
        relative_path
    }
    assert subject._find_raw_body_holdout_query_indexes(holdout, bodies) == {0}


def test_short_markdown_body_is_redacted_from_all_emitted_artifacts(
    tmp_path: Path,
) -> None:
    raw_body = b"Crown launch note: ember."
    config = make_fixture(tmp_path, markdown_body=raw_body)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["source_classes"][0]["description"] = raw_body.decode("utf-8")
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in config.run_dir.iterdir()
        if path.is_file()
    )
    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert "raw_source_text_included" in result["certification"]["blockers"]
    assert raw_body.decode("utf-8") not in serialized


def test_runtime_capability_no_go_blocks_green_certification(tmp_path: Path) -> None:
    config = make_fixture(tmp_path, lightrag_allowed=False)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert any(
        "lightrag_capability" in blocker
        for blocker in result["certification"]["blockers"]
    )
    assert all(
        row["apply_status"] == "blocked"
        for row in read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    )
    assert all(
        row["status"] == "blocked"
        for row in read_jsonl(config.run_dir / "cag-pack-manifest.jsonl")
    )
    assert all(
        row["status"] == "blocked"
        for row in read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    )
    assert set(result["certification"]["rollout_gates"].values()) >= {
        "blocked_until_p0_green"
    }


def test_cli_returns_nonzero_for_legacy_v1_and_rights_blocked_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = make_fixture(tmp_path / "legacy")
    legacy_rc = subject.main(subject.config_to_argv(legacy))
    blocked = make_fixture(tmp_path / "blocked", eligible=False)
    blocked_rc = subject.main(subject.config_to_argv(blocked))

    assert legacy_rc == 2
    assert blocked_rc == 2
    assert '"terminal_state": "blocked_no_mutation"' in capsys.readouterr().out


def test_identical_rerun_is_byte_deterministic(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    other = replace(
        config,
        artifact_root=subject.p0p8.DEFAULT_PUBLIC_ROOT / "logs" / "other-artifacts",
    )

    subject.run_all(config)
    first = {
        path.name: path.read_bytes()
        for path in config.run_dir.iterdir()
        if path.is_file()
    }
    subject.run_all(other)
    second = {
        path.name: path.read_bytes()
        for path in other.run_dir.iterdir()
        if path.is_file()
    }

    first_certification = json.loads(first.pop("black-label-certification.json"))
    second_certification = json.loads(second.pop("black-label-certification.json"))
    first_certification.pop("source_run")
    second_certification.pop("source_run")
    assert second == first
    assert second_certification == first_certification


@pytest.mark.parametrize("run_id", ["../escape", "/absolute", "nested/run"])
def test_run_id_must_be_one_safe_component(tmp_path: Path, run_id: str) -> None:
    config = make_fixture(tmp_path)
    invalid = replace(config, run_id=run_id)

    with pytest.raises(ValueError, match="run_id_must_be_one_safe_component"):
        subject.run_all(invalid)

    assert not config.artifact_root.exists()


def test_artifact_root_is_logs_bounded_and_cannot_overlap_source(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)
    outside = replace(config, artifact_root=tmp_path / "outside")
    overlap = replace(config, source_root=config.artifact_root)

    with pytest.raises(ValueError, match="artifact_root_outside_repository_logs"):
        subject.run_all(outside)
    with pytest.raises(ValueError, match="source_artifact_overlap_not_allowed"):
        subject.run_all(overlap)


def test_duplicate_run_id_preserves_first_published_run(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    subject.run_all(config)
    before = {
        path.name: sha256_bytes(path.read_bytes())
        for path in config.run_dir.iterdir()
        if path.is_file()
    }

    with pytest.raises(FileExistsError, match="run_id_already_exists"):
        subject.run_all(config)

    after = {
        path.name: sha256_bytes(path.read_bytes())
        for path in config.run_dir.iterdir()
        if path.is_file()
    }
    assert after == before
    assert subject.build_run_id() != subject.build_run_id()


def test_cli_duplicate_run_id_fails_closed_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_fixture(tmp_path)
    subject.run_all(config)
    before = {
        path.name: sha256_bytes(path.read_bytes())
        for path in config.run_dir.iterdir()
        if path.is_file()
    }

    return_code = subject.main(subject.config_to_argv(config))
    output = capsys.readouterr().out

    after = {
        path.name: sha256_bytes(path.read_bytes())
        for path in config.run_dir.iterdir()
        if path.is_file()
    }
    assert return_code == 2
    assert '"terminal_state": "blocked_no_mutation"' in output
    assert "run_id_already_exists" in output
    assert "Traceback" not in output
    assert after == before


@pytest.mark.parametrize("failure", ["missing", "hash_mismatch"])
def test_rights_evidence_must_exist_and_match_exact_file_hash(
    tmp_path: Path, failure: str
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    evidence_path = (
        config.policy_manifest.parent / policy["sources"][0]["evidence_refs"][0]
    )
    if failure == "missing":
        evidence_path.unlink()
    else:
        evidence_path.write_text("{}\n", encoding="utf-8")

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    rights = read_jsonl(config.run_dir / "governed-rights-registry.jsonl")
    assert any(
        f"rights_evidence_{failure}" in blocker
        for row in rights
        for blocker in row["blocking_reasons"]
    )
    assert all(
        row["apply_status"] == "blocked"
        for row in read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    )


def test_declared_rights_blockers_override_an_eligible_source(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["sources"][0]["blocking_reasons"] = ["manual_rights_hold"]
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)
    rights = read_jsonl(config.run_dir / "governed-rights-registry.jsonl")
    held = next(row for row in rights if row["relative_path"] == "01-notes/guide.md")

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert held["apply_eligible"] is False
    assert "declared_rights_blockers_present" in held["blocking_reasons"]


def test_text_rights_do_not_require_visual_only_predicates(tmp_path: Path) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    text_source = next(
        row for row in policy["sources"] if row["media_type"] == "text/markdown"
    )
    for predicate in subject.VISUAL_EVIDENCE_PREDICATES:
        text_source["evidence_predicates"][predicate] = False
    refresh_rights_evidence(config.policy_manifest.parent, text_source)
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)
    rights = read_jsonl(config.run_dir / "governed-rights-registry.jsonl")

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert (
        "runtime_capabilities_v1_legacy_positive_proof_unsupported"
        in result["certification"]["blockers"]
    )
    assert (
        next(row for row in rights if row["source_id"] == text_source["source_id"])[
            "apply_eligible"
        ]
        is True
    )


def test_verbatim_markdown_body_metadata_is_redacted_and_blocks_certification(
    tmp_path: Path,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    raw_body = (config.source_root / "01-notes" / "guide.md").read_text(
        encoding="utf-8"
    )
    policy["source_classes"][0]["description"] = raw_body
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)
    cards = read_jsonl(config.run_dir / "black-label-card-manifest.jsonl")
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in config.run_dir.iterdir()
    )

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert "raw_source_text_included" in result["certification"]["blockers"]
    assert any(card["raw_source_text_included"] is True for card in cards)
    assert raw_body.strip() not in serialized
    assert "Sensitive source body" not in serialized


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        ("expires_at", "2000-01-01T00:00:00Z", "budget_authorization_not_current"),
        ("corpus_digest_sha256", "a" * 64, "budget_corpus_digest_mismatch"),
    ],
)
def test_budget_must_be_current_and_bound_to_observed_inventory(
    tmp_path: Path,
    field: str,
    value: str,
    expected_blocker: str,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    policy["budget_contract"][field] = value
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert expected_blocker in result["certification"]["blockers"]
    assert all(
        row["apply_status"] == "blocked"
        for row in read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    )


@pytest.mark.parametrize("failure", ["stale", "unresolved_evidence"])
def test_allowed_capabilities_require_fresh_resolved_observations(
    tmp_path: Path, failure: str
) -> None:
    config = make_fixture(tmp_path)
    capabilities = json.loads(config.runtime_capabilities.read_text(encoding="utf-8"))
    if failure == "stale":
        capabilities["observed_at"] = "2000-01-01T00:00:00Z"
    else:
        capabilities["capabilities"][0]["evidence_refs"] = [
            "/live_read_only_observations/lightrag/does_not_exist"
        ]
    write_json(config.runtime_capabilities, capabilities)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert any(
        "runtime_capabilit" in blocker
        for blocker in result["certification"]["blockers"]
    )
    assert all(
        row["status"] == "blocked"
        for row in read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    )


@pytest.mark.parametrize(
    ("failure", "expected_blocker"),
    [
        ("bad_shape", "runtime_capability_evidence_shape_invalid"),
        ("bad_status", "runtime_capability_evidence_shape_invalid"),
        ("duplicate", "runtime_capability_duplicate_id"),
    ],
)
def test_available_capabilities_require_unique_ids_and_capability_specific_proof(
    tmp_path: Path,
    failure: str,
    expected_blocker: str,
) -> None:
    config = make_fixture(tmp_path)
    capabilities = json.loads(config.runtime_capabilities.read_text(encoding="utf-8"))
    row = capabilities["capabilities"][0]
    if failure == "bad_shape":
        evidence = subject._resolve_json_pointer(capabilities, row["evidence_refs"][0])
        evidence.clear()
        evidence["status"] = "observed"
    elif failure == "bad_status":
        evidence = subject._resolve_json_pointer(capabilities, row["evidence_refs"][0])
        evidence["status"] = "failed"
    else:
        capabilities["capabilities"].append({**row})
    write_json(config.runtime_capabilities, capabilities)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert any(
        blocker.startswith(expected_blocker)
        for blocker in result["certification"]["blockers"]
    )


@pytest.mark.parametrize("failure", ["closed_gate", "unsupported_claim"])
def test_frozen_green_value_contract_requires_measured_thresholds(
    tmp_path: Path, failure: str
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    if failure == "closed_gate":
        policy["value_contract"]["mutation_gate_open"] = False
    else:
        policy["value_contract"]["candidate"]["unsupported_current_claims"] = 1
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert all(
        row["apply_status"] == "blocked"
        for row in read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    )


@pytest.mark.parametrize(
    ("failure", "expected_blocker"),
    [
        ("certificate_hash", "value_evidence_hash_mismatch"),
        ("certificate_symlink", "value_evidence_symlink_not_allowed"),
        ("candidate_binding", "value_evidence_candidate_metrics_mismatch"),
        ("artifact_manifest_hash", "value_artifact_manifest_hash_mismatch"),
        ("artifact_hash", "value_artifact_hash_mismatch"),
        ("nan_metric", "value_contract_green_metric_invalid:irrelevant_hit_rate_at_5"),
        (
            "infinite_metric",
            "value_contract_green_metric_invalid:irrelevant_hit_rate_at_5",
        ),
    ],
)
def test_frozen_green_value_evidence_is_hash_bound_and_exact(
    tmp_path: Path,
    failure: str,
    expected_blocker: str,
) -> None:
    config = make_fixture(tmp_path)
    policy = json.loads(config.policy_manifest.read_text(encoding="utf-8"))
    value = policy["value_contract"]
    certificate_path = config.policy_manifest.parent / value["candidate_evidence_ref"]
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    manifest_path = config.policy_manifest.parent / certificate["artifact_manifest_ref"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if failure == "certificate_hash":
        certificate["candidate_metrics"]["routing_pass_count"] = 2
        write_json(certificate_path, certificate)
    elif failure == "certificate_symlink":
        target = certificate_path.with_name("value-certificate-target.json")
        certificate_path.rename(target)
        certificate_path.symlink_to(target.name)
    elif failure == "candidate_binding":
        certificate["candidate_metrics"]["routing_pass_count"] = 2
        write_json(certificate_path, certificate)
        value["candidate_evidence_sha256"] = subject.sha256_file(certificate_path)
    elif failure == "artifact_manifest_hash":
        manifest["artifacts"].append(
            {"artifact_ref": "missing.json", "sha256": "a" * 64}
        )
        write_json(manifest_path, manifest)
    elif failure == "artifact_hash":
        artifact_path = (
            config.policy_manifest.parent / manifest["artifacts"][0]["artifact_ref"]
        )
        artifact_path.write_text("tampered\n", encoding="utf-8")
    else:
        value["candidate"]["irrelevant_hit_rate_at_5"] = (
            float("nan") if failure == "nan_metric" else float("inf")
        )
        materialize_value_evidence(
            config.policy_manifest.parent,
            policy,
            config.production_profile,
            config.runtime_capabilities,
        )
    write_json(config.policy_manifest, policy)

    result = subject.run_all(config)

    assert result["certification"]["terminal_state"] == "blocked_no_mutation"
    assert expected_blocker in result["certification"]["blockers"]


def test_checked_in_seedance_manifest_binds_exact_inventory() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "app/dante_visual/manifests/seedance_i2v_corpus_20260808.v1.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    assert len(sources) == 21
    assert sum(row["media_type"] == "text/markdown" for row in sources) == 17
    assert sum(row["media_type"] == "image/png" for row in sources) == 4
    assert sum(row["size_bytes"] for row in sources) == 3_388_683
    assert (
        subject.inventory_audit_digest(sources)
        == "38ca2330651ce290da8d97b1d1cb8b2a11ce83161687013af32ac83ede6b40e3"
    )
    assert manifest["inventory_contract"][
        "audit_digest_sha256"
    ] == subject.inventory_audit_digest(sources)
    assert manifest["budget_contract"][
        "corpus_digest_sha256"
    ] == subject.inventory_audit_digest(sources)
    assert manifest["value_contract"]["candidate_evidence_ref"] is None
    assert manifest["value_contract"]["candidate_evidence_sha256"] is None
    assert subject._validate_value_contract(manifest["value_contract"]) == []
    assert all(
        row["source_id"] == f"seedance-i2v:source:{row['source_sha256']}"
        for row in sources
    )
    assert all(
        row["package_id"] == f"seedance-i2v:package:{row['source_sha256']}"
        for row in sources
    )
