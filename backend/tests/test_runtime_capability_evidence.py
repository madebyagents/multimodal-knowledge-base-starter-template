from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

import httpx

from app import runtime_capability_evidence as subject


OBSERVED_AT = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def make_client(
    *,
    epochs: dict[str, tuple[str | None, str | None]] | None = None,
    openapi_versions: dict[str, tuple[int, int]] | None = None,
) -> tuple[httpx.Client, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    counts: Counter[tuple[str, str]] = Counter()
    configured_epochs = epochs or {
        "lightrag": ("lightrag-epoch-1", "lightrag-epoch-1"),
        "knowledge_hub": ("kh-epoch-1", "kh-epoch-1"),
    }
    configured_openapi_versions = openapi_versions or {
        "lightrag": (1, 1),
        "knowledge_hub": (1, 1),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        service_id = (
            "knowledge_hub"
            if request.url.host.startswith("knowledge-hub") or request.url.port == 8098
            else "lightrag"
        )
        key = (service_id, request.url.path)
        sequence_index = counts[key]
        counts[key] += 1

        if request.url.path == "/health":
            epoch = configured_epochs[service_id][sequence_index]
            payload: dict[str, object] = {
                "service_id": service_id,
                "version": "fixture-v1",
                "executable_fingerprint": f"{service_id}-executable",
            }
            if epoch is not None:
                payload["server_epoch"] = epoch
            return httpx.Response(200, json=payload)

        if request.url.path == "/openapi.json":
            version = configured_openapi_versions[service_id][sequence_index]
            return httpx.Response(
                200,
                json={
                    "openapi": "3.1.0",
                    "info": {"title": service_id, "version": str(version)},
                    "paths": {f"/{service_id}/route-v{version}": {"get": {}}},
                },
            )

        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def probes(
    *, loopback: bool = False
) -> tuple[subject.ServiceProbe, subject.ServiceProbe]:
    if loopback:
        lightrag_origin = "http://127.0.0.1:9621"
        knowledge_hub_origin = "http://127.0.0.1:8098"
    else:
        lightrag_origin = "https://lightrag.invalid"
        knowledge_hub_origin = "https://knowledge-hub.invalid"
    return (
        subject.ServiceProbe(
            service_id="lightrag",
            health_url=f"{lightrag_origin}/health",
            openapi_url=f"{lightrag_origin}/openapi.json",
        ),
        subject.ServiceProbe(
            service_id="knowledge_hub",
            health_url=f"{knowledge_hub_origin}/health",
            openapi_url=f"{knowledge_hub_origin}/openapi.json",
        ),
    )


def produce(
    *,
    client: httpx.Client,
    service_probes: tuple[subject.ServiceProbe, subject.ServiceProbe] | None = None,
    negative_signals: dict[str, dict[str, bool]] | None = None,
) -> dict:
    return subject.produce_runtime_capability_evidence(
        http_client=client,
        probes=service_probes or probes(),
        manifest_id="fixture-runtime-capabilities",
        subject_revision="a" * 40,
        executable_tree_sha256="b" * 64,
        observed_at=OBSERVED_AT,
        negative_signals=negative_signals,
    )


def test_producer_emits_exact_negative_contract_with_get_only() -> None:
    client, requests = make_client()

    manifest = produce(client=client)

    assert subject.validate_runtime_capability_evidence(manifest) == []
    assert manifest["schema_version"] == subject.SCHEMA_VERSION
    assert set(manifest) == subject.TOP_LEVEL_KEYS
    assert {row["capability_id"] for row in manifest["capabilities"]} == set(
        subject.CAPABILITY_SPECS
    )
    assert {row["status"] for row in manifest["capabilities"]} == {"not_provable"}
    assert {row["proof_level"] for row in manifest["capabilities"]} == {"discovered"}
    assert all(row["blocking"] is True for row in manifest["capabilities"])
    assert manifest["gate_decisions"] == subject.recompute_gate_decisions(manifest)
    assert manifest["gate_decisions"]["lightrag_mutation"]["decision"] == "blocked"
    assert (
        manifest["gate_decisions"]["knowledge_hub_promotion"]["decision"] == "blocked"
    )
    assert all(request.method == "GET" for request in requests)
    assert len(requests) == 8
    assert "cache" not in repr(manifest).lower()


def test_absent_epoch_is_recorded_as_gate_local_blocker() -> None:
    client, _requests = make_client(
        epochs={
            "lightrag": (None, None),
            "knowledge_hub": ("kh-epoch-1", "kh-epoch-1"),
        }
    )

    manifest = produce(client=client)

    assert subject.validate_runtime_capability_evidence(manifest) == []
    assert (
        manifest["service_observations"]["lightrag"]["coherence"]["stable_server_epoch"]
        is False
    )
    assert (
        "lightrag.server_epoch_missing"
        in manifest["gate_decisions"]["lightrag_mutation"]["blockers"]
    )
    assert (
        "lightrag.server_epoch_missing"
        not in manifest["gate_decisions"]["knowledge_hub_promotion"]["blockers"]
    )


def test_declared_knowledge_hub_decision_mismatch_is_gate_local() -> None:
    client, _requests = make_client()
    manifest = produce(client=client)
    manifest["gate_decisions"]["knowledge_hub_promotion"] = {
        "decision": "blocked",
        "blockers": [],
    }

    blockers = subject.validate_runtime_capability_evidence(manifest)

    assert blockers == [
        "runtime_capabilities_gate_decisions_mismatch:knowledge_hub_promotion"
    ]


def test_unhashable_capability_status_and_proof_level_fail_closed() -> None:
    client, _requests = make_client()
    manifest = produce(client=client)
    manifest["capabilities"][0]["status"] = []
    manifest["capabilities"][0]["proof_level"] = {}

    blockers = subject.validate_runtime_capability_evidence(manifest)

    capability_id = manifest["capabilities"][0]["capability_id"]
    assert f"runtime_capability_status_invalid:{capability_id}" in blockers
    assert f"runtime_capability_proof_level_invalid:{capability_id}" in blockers


def test_restart_or_openapi_change_invalidates_only_affected_epoch() -> None:
    client, _requests = make_client(
        epochs={
            "lightrag": ("epoch-before", "epoch-after"),
            "knowledge_hub": ("kh-epoch-1", "kh-epoch-1"),
        },
        openapi_versions={
            "lightrag": (1, 2),
            "knowledge_hub": (1, 1),
        },
    )

    manifest = produce(client=client)
    lightrag_blockers = manifest["gate_decisions"]["lightrag_mutation"]["blockers"]
    kh_blockers = manifest["gate_decisions"]["knowledge_hub_promotion"]["blockers"]

    assert "lightrag.server_epoch_changed" in lightrag_blockers
    assert "lightrag.server_identity_changed" in lightrag_blockers
    assert "lightrag.openapi_changed" in lightrag_blockers
    assert not any(
        blocker.startswith("knowledge_hub.server_") for blocker in kh_blockers
    )
    assert "knowledge_hub.openapi_changed" not in kh_blockers
    assert subject.validate_runtime_capability_evidence(manifest) == []


def test_loopback_and_self_declared_positive_claims_never_open_gate() -> None:
    client, _requests = make_client()
    manifest = produce(
        client=client,
        service_probes=probes(loopback=True),
        negative_signals={
            "lightrag": {
                "content_md5_observed": True,
                "local_client_guard_observed": True,
            }
        },
    )
    forged = deepcopy(manifest)
    row = next(
        row
        for row in forged["capabilities"]
        if row["capability_id"].startswith("lightrag.")
    )
    row["status"] = "available"
    row["proof_level"] = "deployment_bound"
    row["blocking"] = False
    forged["gate_decisions"] = subject.recompute_gate_decisions(forged)

    blockers = subject.validate_runtime_capability_evidence(forged)

    assert (
        f"runtime_capability_positive_claim_unsupported:{row['capability_id']}"
        in blockers
    )
    assert (
        f"runtime_capability_deployment_bound_unsupported:{row['capability_id']}"
        in blockers
    )
    assert f"runtime_capability_not_blocking:{row['capability_id']}" in blockers
    assert forged["gate_decisions"]["lightrag_mutation"]["decision"] == "blocked"
    assert (
        row["capability_id"]
        in forged["gate_decisions"]["lightrag_mutation"]["blockers"]
    )


def test_route_md5_and_local_guard_signals_remain_negative_evidence() -> None:
    client, _requests = make_client()
    manifest = produce(
        client=client,
        negative_signals={
            "lightrag": {
                "content_md5_observed": True,
                "local_client_guard_observed": True,
            },
            "knowledge_hub": {
                "content_md5_observed": False,
                "local_client_guard_observed": True,
            },
        },
    )

    for service_id, observation in manifest["service_observations"].items():
        assert observation["negative_signals"]["route_advertised"] is True
        rows = [
            row
            for row in manifest["capabilities"]
            if subject.CAPABILITY_SPECS[row["capability_id"]].service_id == service_id
        ]
        assert {row["status"] for row in rows} == {"not_provable"}
        assert {row["proof_level"] for row in rows} == {"observed"}
        assert all(row["blocking"] is True for row in rows)

    assert subject.validate_runtime_capability_evidence(manifest) == []


def test_pointer_scope_and_exact_schema_contradictions_are_rejected() -> None:
    client, _requests = make_client()
    manifest = produce(client=client)
    invalid = deepcopy(manifest)
    row = next(
        row
        for row in invalid["capabilities"]
        if row["capability_id"].startswith("lightrag.")
    )
    row["scope"] = "knowledge_hub_promotion"
    row["evidence_refs"] = ["/service_observations/knowledge_hub/missing"]
    row["unexpected"] = True
    invalid["unexpected"] = True

    blockers = subject.validate_runtime_capability_evidence(invalid)

    assert "runtime_capabilities_top_level_keys_mismatch" in blockers
    assert f"runtime_capability_keys_mismatch:{row['capability_id']}" in blockers
    assert f"runtime_capability_scope_mismatch:{row['capability_id']}" in blockers
    assert (
        f"runtime_capability_evidence_scope_mismatch:{row['capability_id']}" in blockers
    )
    assert f"runtime_capability_evidence_unresolved:{row['capability_id']}" in blockers


def test_mixed_gate_recomputation_never_cross_contaminates_blockers() -> None:
    client, _requests = make_client(
        epochs={
            "lightrag": ("lightrag-epoch-1", "lightrag-epoch-1"),
            "knowledge_hub": (None, None),
        }
    )
    manifest = produce(client=client)

    decisions = subject.recompute_gate_decisions(manifest)

    assert all(
        blocker.startswith("lightrag.")
        for blocker in decisions["lightrag_mutation"]["blockers"]
    )
    assert all(
        blocker.startswith("knowledge_hub.")
        for blocker in decisions["knowledge_hub_promotion"]["blockers"]
    )
    assert (
        "knowledge_hub.server_epoch_missing"
        in decisions["knowledge_hub_promotion"]["blockers"]
    )
    assert (
        "knowledge_hub.server_epoch_missing"
        not in decisions["lightrag_mutation"]["blockers"]
    )


def test_declared_gate_decisions_must_match_unconditional_recomputation() -> None:
    client, _requests = make_client()
    manifest = produce(client=client)
    manifest["gate_decisions"]["lightrag_mutation"] = {
        "decision": "allowed",
        "blockers": [],
    }

    blockers = subject.validate_runtime_capability_evidence(manifest)

    assert "runtime_capabilities_gate_decisions_mismatch:lightrag_mutation" in blockers
    recomputed = subject.recompute_gate_decisions(manifest)
    assert recomputed["lightrag_mutation"]["decision"] == "blocked"
    assert recomputed["lightrag_mutation"]["blockers"]
