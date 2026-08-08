from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app import governed_corpus_rollout as subject


PALETTE_PATHS = {
    "bold-energetic.md",
    "clean-corporate.md",
    "dark-premium.md",
    "jewel-rich.md",
    "monochrome.md",
    "nature-earth.md",
    "neon-electric.md",
    "pastel-soft.md",
    "warm-editorial.md",
}
PALETTE_TOPICS = {
    path: (
        "chromatic-expression"
        if path
        in {
            "bold-energetic.md",
            "jewel-rich.md",
            "neon-electric.md",
            "pastel-soft.md",
        }
        else "supporting-palette"
    )
    for path in PALETTE_PATHS
}


def strict_v2_value_fixture() -> tuple[dict, dict]:
    evaluated_at = "2026-08-08T10:48:39Z"
    queries = [
        {
            "holdout_id": f"H{index}",
            "query": f"Fixture holdout query {index}",
            "expected_topic_ids": [] if index == 5 else ["chromatic-expression"],
            "answer_criteria": ["Routes deterministically or abstains."],
            "negative_control": index == 5,
        }
        for index in range(1, 6)
    ]
    thresholds = {
        "topic_routing_pass_count_min": 5,
        "answer_criteria_pass_count_min": 5,
        "negative_control_pass_count_min": 1,
        "unsupported_current_claims_max": 0,
        "raw_source_body_leaks_max": 0,
        "invented_evidence_claims_max": 0,
    }
    holdout = {
        "contract_id": "hyperframes-palettes-holdout-20260808",
        "authored_from": "operator_facing_source_intent_only",
        "frozen_before_card_generation": True,
        "generated_card_content_allowed": False,
        "query_count": 5,
        "negative_control_ids": ["H5"],
        "thresholds": thresholds,
        "queries": queries,
        "digest_algorithm": "sha256",
        "digest_scope": "canonical_json_of_thresholds_and_queries",
        "contract_sha256": "",
    }
    holdout["contract_sha256"] = subject.holdout_digest(holdout)
    candidate = {
        "certificate_id": "hyperframes-palettes-value-20260808",
        "evaluated_at": evaluated_at,
        "routing_pass_count": 5,
        "answer_criteria_pass_count": 5,
        "negative_control_pass_count": 1,
        "irrelevant_hit_rate_at_5": 0.0,
        "estimated_cost_usd": 0.0,
        "unsupported_current_claims": 0,
        "raw_source_body_leaks": 0,
        "invented_evidence_claims": 0,
    }
    policy = {
        "schema_version": subject.POLICY_SCHEMA_VERSION_V2,
        "inventory_contract": {"audit_digest_sha256": "5" * 64},
        "holdout_contract": holdout,
        "value_contract": {
            "contract_id": "hyperframes-palettes-phase0-value-20260808",
            "status": "frozen_green",
            "authored_from": "read_only_dashboard_baseline_and_independent_metadata",
            "hypothesis": "The bounded corpus fills observed routing gaps.",
            "operator_workflows": ["multi-brief_palette_routing"],
            "baseline": {
                "snapshot_id": "dantedash-phase0-search-20260808",
                "captured_at": evaluated_at,
                "routing_pass_count": 0,
                "answer_criteria_pass_count": 0,
                "negative_control_pass_count": 0,
                "irrelevant_hit_rate_at_5": 0.0,
                "estimated_cost_usd": 0.0,
            },
            "candidate": candidate,
            "candidate_evidence_ref": "value-certificate.json",
            "candidate_evidence_sha256": "6" * 64,
            "minimum_absolute_answer_pass_gain": 0.8,
            "maximum_irrelevant_hit_rate_at_5": 0.0,
            "maximum_incremental_eval_cost_usd": 0.0,
            "mutation_gate_open": True,
        },
    }
    preflight = {
        "schema_version": subject.HYPERFRAMES_VALUE_PREFLIGHT_SCHEMA_VERSION,
        "captured_at": evaluated_at,
        "collection_mode": "read_only_local_search_and_curated_metadata_coverage",
        "dashboard_stats": subject.HYPERFRAMES_VALUE_PREFLIGHT_STATS,
        "frontend_head_status": 200,
        "baseline_queries": [
            {
                "query_id": query_id,
                "request_sha256": request_sha256,
                "response_sha256": (
                    subject.HYPERFRAMES_VALUE_PREFLIGHT_EMPTY_RESPONSE_SHA256
                ),
                "result_count": 0,
                "local_metadata_covers_need": True,
            }
            for query_id, request_sha256 in (
                subject.HYPERFRAMES_VALUE_PREFLIGHT_QUERY_HASHES.items()
            )
        ],
        "candidate_evaluation": {
            "method": "deterministic_curated_metadata_routing",
            "holdout_ids": [f"H{index}" for index in range(1, 6)],
            **{
                key: candidate[key]
                for key in (
                    "routing_pass_count",
                    "answer_criteria_pass_count",
                    "negative_control_pass_count",
                    "unsupported_current_claims",
                    "raw_source_body_leaks",
                    "invented_evidence_claims",
                )
            },
        },
        "provider_calls": 0,
        "source_bodies_persisted": False,
    }
    return policy, preflight


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def materialize_v2_value_evidence(
    root: Path,
    policy: dict,
    preflight: dict,
    *,
    include_extra_artifact: bool = False,
) -> tuple[dict, str, str, str]:
    preflight_ref = "value-preflight.json"
    preflight_path = root / preflight_ref
    write_json(preflight_path, preflight)
    artifacts = [
        {
            "artifact_ref": preflight_ref,
            "sha256": subject.sha256_file(preflight_path),
        }
    ]
    if include_extra_artifact:
        extra_path = root / "extra-value.json"
        write_json(extra_path, {"unexpected": True})
        artifacts.append(
            {
                "artifact_ref": extra_path.name,
                "sha256": subject.sha256_file(extra_path),
            }
        )
    manifest_path = root / "value-artifacts.json"
    write_json(
        manifest_path,
        {
            "schema_version": subject.VALUE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
            "artifacts": artifacts,
        },
    )
    profile_hash = "2" * 64
    capabilities_hash = "3" * 64
    holdout_hash = policy["holdout_contract"]["contract_sha256"]
    candidate = policy["value_contract"]["candidate"]
    certificate = {
        "schema_version": subject.VALUE_EVIDENCE_SCHEMA_VERSION,
        "certificate_id": candidate["certificate_id"],
        "evaluated_at": candidate["evaluated_at"],
        "evaluated_repository_revision": "a" * 40,
        "corpus_digest_sha256": policy["inventory_contract"][
            "audit_digest_sha256"
        ],
        "holdout_sha256": holdout_hash,
        "production_profile_sha256": profile_hash,
        "runtime_capabilities_sha256": capabilities_hash,
        "candidate_metrics": {
            key: candidate[key] for key in subject.VALUE_CANDIDATE_METRIC_KEYS
        },
        "artifact_manifest_ref": manifest_path.name,
        "artifact_manifest_sha256": subject.sha256_file(manifest_path),
    }
    certificate_path = root / "value-certificate.json"
    write_json(certificate_path, certificate)
    policy["value_contract"]["candidate_evidence_ref"] = certificate_path.name
    policy["value_contract"]["candidate_evidence_sha256"] = subject.sha256_file(
        certificate_path
    )
    return (
        {
            "schema_version": subject.RUNTIME_CAPABILITY_SCHEMA_VERSION_V2,
            "subject": {"revision": "a" * 40},
        },
        profile_hash,
        capabilities_hash,
        holdout_hash,
    )


def test_unhashable_policy_schema_version_fails_closed() -> None:
    blockers = subject._validate_policy({"schema_version": []})

    assert "policy_schema_mismatch" in blockers
    assert "policy_top_level_keys_mismatch" in blockers


class StaticHttpClient:
    """Small httpx-compatible stub; no socket or transport is opened."""

    def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        assert headers == {"accept": "application/json"}
        service_id = "knowledge_hub" if "knowledge-hub" in url else "lightrag"
        if url.endswith("/health"):
            return httpx.Response(
                200,
                json={
                    "service_id": service_id,
                    "version": "fixture-v1",
                    "server_epoch": f"{service_id}-epoch-1",
                    "executable_fingerprint": f"{service_id}-executable-1",
                },
            )
        if url.endswith("/openapi.json"):
            return httpx.Response(
                200,
                json={
                    "openapi": "3.1.0",
                    "info": {"title": service_id, "version": "1"},
                    "paths": {f"/{service_id}/read-only": {"get": {}}},
                },
            )
        raise AssertionError(f"unexpected read-only URL: {url}")


def fresh_negative_manifest() -> dict:
    return subject.runtime_evidence.produce_runtime_capability_evidence(
        http_client=StaticHttpClient(),
        probes=(
            subject.runtime_evidence.ServiceProbe(
                service_id="lightrag",
                health_url="https://lightrag.invalid/health",
                openapi_url="https://lightrag.invalid/openapi.json",
            ),
            subject.runtime_evidence.ServiceProbe(
                service_id="knowledge_hub",
                health_url="https://knowledge-hub.invalid/health",
                openapi_url="https://knowledge-hub.invalid/openapi.json",
            ),
        ),
        manifest_id="fixture-runtime-capabilities-v2",
        subject_revision="a" * 40,
        executable_tree_sha256="b" * 64,
        observed_at=datetime.now(timezone.utc),
    )


def green_capability_policy() -> dict:
    return {
        "capability_contract": {
            "lightrag": {"status": "green", "mutation_eligible": True},
            "knowledge_hub": {"status": "green", "promotion_eligible": True},
        },
        "audit_contract": {"legacy_reconciliation": "green"},
    }


def empty_gate_blockers(**overrides: list[str]) -> dict[str, list[str]]:
    blockers = {
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
    blockers.update(overrides)
    return blockers


def finalize_with_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    gate_blockers: dict[str, list[str]],
) -> dict:
    monkeypatch.setattr(subject.p0p8, "DEFAULT_PUBLIC_ROOT", tmp_path)
    config = subject.GovernedCorpusConfig(
        run_id=run_id,
        source_root=tmp_path / "source",
        policy_manifest=tmp_path / "policy.json",
        artifact_root=tmp_path / "logs" / "governed-v2-tests",
    )
    subject._prepare_run_directory(config)
    return subject._finalize_run(
        config,
        contracts=None,
        phases=[],
        blockers=[],
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
        independent_gate_blockers=gate_blockers,
    )


def exact_stage_contract() -> dict:
    return {
        "gate_1": {
            "required_card_role": "source_card",
            "cumulative_unique_source_count": 1,
            "selection_rule": "named_representative",
            "source_paths": ["clean-corporate.md"],
        },
        "gate_2": {
            "cumulative_unique_source_count": 5,
            "required_new_unique_source_count": 4,
            "selection_rule": "named_additions",
            "source_paths": [
                "clean-corporate.md",
                "bold-energetic.md",
                "dark-premium.md",
                "pastel-soft.md",
                "warm-editorial.md",
            ],
        },
        "gate_3": {
            "topic_id": "chromatic-expression",
            "minimum_new_sources": 1,
            "minimum_relationship_patterns": 1,
            "existing_members_are_noop": True,
            "source_paths": [
                "bold-energetic.md",
                "jewel-rich.md",
                "neon-electric.md",
                "pastel-soft.md",
            ],
        },
        "full_apply": {
            "requires_independent_holdout": True,
            "requires_fresh_rehearsed_checkpoint": True,
            "requires_zero_unresolved_conflicts_in_eligible_set": True,
            "remaining_source_paths": ["monochrome.md", "nature-earth.md"],
        },
    }


def evidence_policy() -> dict:
    return {
        "sources": [
            {
                "source_id": "source-a",
                "apply_eligible": True,
                "evidence_refs": ["evidence/generation/rights-a.json"],
                "rights_evidence_sha256": "8" * 64,
            },
            {
                "source_id": "source-b",
                "apply_eligible": True,
                "evidence_refs": ["evidence/generation/rights-b.json"],
                "rights_evidence_sha256": "9" * 64,
            },
        ]
    }


def exact_evidence_generation() -> dict:
    return {
        "generation_id": "fixture-generation-v1",
        "subject_revision": "a" * 40,
        "executable_tree_sha256": "b" * 64,
        "trust_registry_ref": "evidence/generation/trust-registry.json",
        "trust_registry_sha256": "1" * 64,
        "origin_observation_ref": "evidence/generation/origin-observation.json",
        "origin_observation_sha256": "2" * 64,
        "authority_ref": "evidence/generation/authority.json",
        "authority_sha256": "3" * 64,
        "license_ref": "evidence/generation/LICENSE",
        "license_sha256": "4" * 64,
        "value_baseline_ref": "evidence/generation/value-baseline.json",
        "value_baseline_sha256": "5" * 64,
        "holdout_ref": "evidence/generation/holdout.json",
        "holdout_sha256": "6" * 64,
        "runtime_capabilities_ref": "evidence/generation/runtime-capabilities.json",
        "runtime_capabilities_sha256": "7" * 64,
        "rights_records": [
            {
                "source_id": "source-a",
                "artifact_ref": "evidence/generation/rights-a.json",
                "sha256": "8" * 64,
            },
            {
                "source_id": "source-b",
                "artifact_ref": "evidence/generation/rights-b.json",
                "sha256": "9" * 64,
            },
        ],
    }


def test_runtime_schema_dispatches_without_copying_v1_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_validate_runtime_capabilities_v1",
        lambda _capabilities, _profile_sha256: ["legacy-validator-called"],
    )
    monkeypatch.setattr(
        subject.runtime_evidence,
        "validate_runtime_capability_evidence",
        lambda _capabilities: ["v2-validator-called"],
    )

    assert subject._validate_runtime_capabilities(
        {"schema_version": subject.RUNTIME_CAPABILITY_SCHEMA_VERSION},
        "0" * 64,
    ) == ["legacy-validator-called"]
    assert subject._validate_runtime_capabilities(
        {"schema_version": subject.RUNTIME_CAPABILITY_SCHEMA_VERSION_V2},
        "0" * 64,
    ) == ["v2-validator-called"]
    assert subject._validate_runtime_capabilities(
        {"schema_version": "unsupported.v9"},
        "0" * 64,
    ) == ["runtime_capabilities_schema_mismatch"]


def test_fresh_negative_v2_manifest_is_structurally_valid_and_gate_separated(
    tmp_path: Path,
) -> None:
    manifest = fresh_negative_manifest()

    assert subject._validate_runtime_capabilities(manifest, "0" * 64) == []
    gates = subject._capability_gate_vector(green_capability_policy(), manifest)
    assert set(gates["lightrag"]) == {
        capability_id
        for capability_id, spec in subject.runtime_evidence.CAPABILITY_SPECS.items()
        if spec.service_id == "lightrag"
    }
    assert set(gates["knowledge_hub"]) == {
        capability_id
        for capability_id, spec in subject.runtime_evidence.CAPABILITY_SPECS.items()
        if spec.service_id == "knowledge_hub"
    }


def test_budget_and_knowledge_hub_no_go_do_not_block_hypothetical_p0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certification = finalize_with_gates(
        tmp_path,
        monkeypatch,
        run_id="green-p0",
        gate_blockers=empty_gate_blockers(
            budget=["budget_contract_not_active"],
            knowledge_hub=["knowledge_hub.atomic_import"],
        ),
    )

    assert certification["ok"] is True
    assert certification["terminal_state"] == "green_dry_run"
    assert certification["independent_gate_vector"]["budget"]["status"] == "no_go"
    assert (
        certification["independent_gate_vector"]["knowledge_hub"]["status"] == "no_go"
    )
    assert certification["independent_gate_vector"]["lightrag"]["status"] == "pass"
    assert all(
        set(gate)
        == {
            "status",
            "blockers",
            "evidence",
            "downstream_permission",
        }
        for gate in certification["independent_gate_vector"].values()
    )
    assert certification["independent_gate_vector"]["budget"][
        "downstream_permission"
    ] == {"scope": "p1_external_processing", "allowed": False}


def test_lightrag_no_go_blocks_p0_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certification = finalize_with_gates(
        tmp_path,
        monkeypatch,
        run_id="blocked-p0",
        gate_blockers=empty_gate_blockers(
            lightrag=["lightrag.authoritative_payload_hash_lookup"],
        ),
    )

    assert certification["ok"] is False
    assert certification["terminal_state"] == "blocked_no_mutation"
    lightrag_gate = certification["independent_gate_vector"]["lightrag"]
    assert lightrag_gate["status"] == "blocked"
    assert lightrag_gate["blockers"] == ["lightrag.authoritative_payload_hash_lookup"]
    assert lightrag_gate["downstream_permission"] == {
        "scope": "p0_dry_run",
        "allowed": False,
    }
    assert set(lightrag_gate["evidence"]) == {
        "runtime_capabilities_sha256",
        "decision",
    }


def test_knowledge_hub_contract_blocker_does_not_contaminate_dependency_gate() -> None:
    groups = subject._split_contract_gate_blockers(
        ["capability_contract_knowledge_hub_requirements_mismatch"]
    )

    assert groups["knowledge_hub"] == [
        "capability_contract_knowledge_hub_requirements_mismatch"
    ]
    assert groups["dependency"] == []


def test_generation_binding_blockers_keep_their_gate_owner() -> None:
    groups = subject._split_contract_gate_blockers(
        [
            "evidence_generation_source_rights_binding_mismatch",
            "evidence_generation_holdout_binding_mismatch",
            "evidence_generation_value_binding_mismatch",
        ]
    )

    assert groups["rights"] == ["evidence_generation_source_rights_binding_mismatch"]
    assert groups["value"] == [
        "evidence_generation_holdout_binding_mismatch",
        "evidence_generation_value_binding_mismatch",
    ]
    assert groups["dependency"] == []


def test_exact_stage_membership_accepts_named_nine_source_partition() -> None:
    assert (
        subject._validate_stage_contract(
            exact_stage_contract(),
            schema_version=subject.POLICY_SCHEMA_VERSION_V2,
            declared_source_paths=PALETTE_PATHS,
            source_topics=PALETTE_TOPICS,
        )
        == []
    )


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        ("short_gate_five", "stage_contract_gate_2_exact_membership_invalid"),
        (
            "cluster_without_new_source",
            "stage_contract_gate_3_exact_membership_invalid",
        ),
        ("overlapping_remaining", "stage_contract_full_apply_exact_membership_invalid"),
    ],
)
def test_exact_stage_membership_rejects_partial_or_overlapping_sets(
    mutation: str,
    expected_blocker: str,
) -> None:
    contract = exact_stage_contract()
    if mutation == "short_gate_five":
        contract["gate_2"]["source_paths"].pop()
    elif mutation == "cluster_without_new_source":
        contract["gate_3"]["source_paths"] = ["bold-energetic.md", "pastel-soft.md"]
    else:
        contract["full_apply"]["remaining_source_paths"][0] = "clean-corporate.md"

    blockers = subject._validate_stage_contract(
        contract,
        schema_version=subject.POLICY_SCHEMA_VERSION_V2,
        declared_source_paths=PALETTE_PATHS,
        source_topics=PALETTE_TOPICS,
    )

    assert expected_blocker in blockers


@pytest.mark.parametrize(
    ("gate_name", "field", "invalid_value", "expected_blocker"),
    [
        ("gate_1", "selection_rule", None, "stage_contract_gate_1_invalid"),
        ("gate_2", "selection_rule", "", "stage_contract_gate_2_invalid"),
        (
            "gate_3",
            "minimum_relationship_patterns",
            "nonsense",
            "stage_contract_gate_3_invalid",
        ),
        (
            "gate_3",
            "existing_members_are_noop",
            False,
            "stage_contract_gate_3_invalid",
        ),
    ],
)
def test_stage_semantics_reject_malformed_operational_fields(
    gate_name: str,
    field: str,
    invalid_value: object,
    expected_blocker: str,
) -> None:
    contract = exact_stage_contract()
    contract[gate_name][field] = invalid_value

    blockers = subject._validate_stage_contract(
        contract,
        schema_version=subject.POLICY_SCHEMA_VERSION_V2,
        declared_source_paths=PALETTE_PATHS,
        source_topics=PALETTE_TOPICS,
    )

    assert expected_blocker in blockers


def test_evidence_generation_shape_accepts_exact_rights_membership() -> None:
    assert (
        subject._validate_evidence_generation_shape(
            exact_evidence_generation(),
            evidence_policy(),
        )
        == []
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "mixed"])
def test_evidence_generation_shape_rejects_missing_extra_or_mixed_rights_refs(
    mutation: str,
) -> None:
    policy = evidence_policy()
    generation = exact_evidence_generation()
    expected_blocker = "evidence_generation_rights_membership_mismatch"
    if mutation == "missing":
        generation["rights_records"].pop()
    elif mutation == "extra":
        generation["rights_records"].append(
            {
                "source_id": "source-c",
                "artifact_ref": "evidence/generation/rights-c.json",
                "sha256": "c" * 64,
            }
        )
    else:
        generation["rights_records"][0]["artifact_ref"] = (
            "evidence/generation/rights-b.json"
        )
        generation["rights_records"][0]["sha256"] = "9" * 64
        generation["rights_records"][1]["artifact_ref"] = (
            "evidence/generation/rights-a.json"
        )
        generation["rights_records"][1]["sha256"] = "8" * 64
        expected_blocker = "evidence_generation_source_rights_binding_mismatch"

    blockers = subject._validate_evidence_generation_shape(generation, policy)

    assert expected_blocker in blockers


def test_stage_topic_membership_rejects_a_mixed_cluster() -> None:
    topics = dict(PALETTE_TOPICS)
    topics["jewel-rich.md"] = "supporting-palette"

    blockers = subject._validate_stage_contract(
        exact_stage_contract(),
        schema_version=subject.POLICY_SCHEMA_VERSION_V2,
        declared_source_paths=PALETTE_PATHS,
        source_topics=topics,
    )

    assert "stage_contract_gate_3_topic_membership_mismatch" in blockers


def test_strict_v2_value_preflight_is_semantically_validated(tmp_path: Path) -> None:
    policy, preflight = strict_v2_value_fixture()
    capabilities, profile_hash, capabilities_hash, holdout_hash = (
        materialize_v2_value_evidence(tmp_path, policy, preflight)
    )

    blockers = subject._validate_value_evidence(
        policy,
        capabilities,
        policy_manifest_parent=tmp_path,
        profile_hash=profile_hash,
        capabilities_hash=capabilities_hash,
        holdout_hash=holdout_hash,
    )

    assert blockers == []


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        ("query_hash", "value_preflight_baseline_query_mismatch:dark-premium-gap"),
        ("provider_calls", "value_preflight_provider_calls_nonzero"),
        ("raw_body_leak", "value_preflight_candidate_metric_mismatch:raw_source_body_leaks"),
        ("source_bodies", "value_preflight_source_bodies_persisted"),
        ("holdout_membership", "value_preflight_holdout_membership_mismatch"),
    ],
)
def test_strict_v2_value_preflight_rejects_self_attested_or_unsafe_evidence(
    tmp_path: Path,
    mutation: str,
    expected_blocker: str,
) -> None:
    policy, preflight = strict_v2_value_fixture()
    if mutation == "query_hash":
        preflight["baseline_queries"][0]["request_sha256"] = "f" * 64
    elif mutation == "provider_calls":
        preflight["provider_calls"] = 1
    elif mutation == "raw_body_leak":
        preflight["candidate_evaluation"]["raw_source_body_leaks"] = 1
    elif mutation == "source_bodies":
        preflight["source_bodies_persisted"] = True
    else:
        preflight["candidate_evaluation"]["holdout_ids"] = ["H1"]
    capabilities, profile_hash, capabilities_hash, holdout_hash = (
        materialize_v2_value_evidence(tmp_path, policy, preflight)
    )

    blockers = subject._validate_value_evidence(
        policy,
        capabilities,
        policy_manifest_parent=tmp_path,
        profile_hash=profile_hash,
        capabilities_hash=capabilities_hash,
        holdout_hash=holdout_hash,
    )

    assert expected_blocker in blockers


def test_strict_v2_value_artifact_membership_is_exact(tmp_path: Path) -> None:
    policy, preflight = strict_v2_value_fixture()
    capabilities, profile_hash, capabilities_hash, holdout_hash = (
        materialize_v2_value_evidence(
            tmp_path,
            policy,
            preflight,
            include_extra_artifact=True,
        )
    )

    blockers = subject._validate_value_evidence(
        policy,
        capabilities,
        policy_manifest_parent=tmp_path,
        profile_hash=profile_hash,
        capabilities_hash=capabilities_hash,
        holdout_hash=holdout_hash,
    )

    assert "value_artifact_manifest_v2_membership_mismatch" in blockers


def test_holdout_and_v2_value_thresholds_cannot_be_weakened() -> None:
    policy, _preflight = strict_v2_value_fixture()
    holdout = policy["holdout_contract"]
    value = policy["value_contract"]

    assert subject._validate_holdout(holdout) == []
    assert subject._validate_value_contract(value, strict_v2=True) == []

    holdout["thresholds"]["topic_routing_pass_count_min"] = 4
    value["minimum_absolute_answer_pass_gain"] = 0.79

    assert "holdout_thresholds_weakened" in subject._validate_holdout(holdout)
    assert "value_contract_v2_thresholds_weakened" in subject._validate_value_contract(
        value,
        strict_v2=True,
    )


def test_active_budget_rejects_declared_blockers() -> None:
    budget = {
        "contract_id": "fixture-active-budget",
        "status": "active_reserved",
        "activation_allowed": True,
        "blocked_by": ["operator_budget_reservation_absent"],
        "currency": "USD",
        "corpus_digest_sha256": "a" * 64,
        "operator_instruction_hash": "b" * 64,
        "issued_at": "2026-08-08T00:00:00Z",
        "expires_at": "2026-08-09T00:00:00Z",
        "provider_roles": [
            {
                "role": "embeddings",
                "provider": "voyage",
                "model": "voyage-4-large",
                "rate_basis_status": "materialized",
                "rate_unit": "token",
                "rate_amount": 0.001,
                "max_calls": 1,
                "max_input_tokens": 100,
                "max_output_tokens": 1,
            }
        ],
        "total_ceiling": 1.0,
        "reservation_status": "reserved",
        "source_derived_fields": ["title"],
        "external_processing": True,
        "reactivation_requirements": [],
    }

    blockers = subject._validate_budget_contract(budget)

    assert "budget_contract_active_has_unresolved_blockers" in blockers
