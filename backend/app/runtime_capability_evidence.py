"""Read-only runtime capability evidence for governed corpus P0 audits.

Version 2 deliberately supports negative certification only. It can discover
routes and record weak local signals, but it cannot mint the service-signed
attestation required for a positive mutation or promotion capability. Gate
decisions are therefore recomputed from the evidence on every validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import httpx


SCHEMA_VERSION = "dantedash.governed_runtime_capabilities.v2"
EVIDENCE_MODE = "redacted_read_only_negative_audit"
PROOF_LEVELS = {"discovered", "observed", "deployment_bound"}
CAPABILITY_STATUSES = {"available", "unavailable", "not_provable"}
SERVICE_IDS = ("lightrag", "knowledge_hub")

TOP_LEVEL_KEYS = {
    "schema_version",
    "manifest_id",
    "observed_at",
    "evidence_mode",
    "subject",
    "policy",
    "service_observations",
    "capabilities",
    "gate_decisions",
}
SUBJECT_KEYS = {"revision", "executable_tree_sha256"}
POLICY_KEYS = {
    "positive_attestation_supported",
    "live_mutation_attempted",
    "promotion_attempted",
}
SERVICE_OBSERVATION_KEYS = {"pre", "post", "negative_signals", "coherence"}
BRACKET_KEYS = {"identity", "openapi"}
IDENTITY_KEYS = {
    "http_status",
    "service_id",
    "version",
    "server_epoch",
    "executable_fingerprint",
    "request_error",
}
OPENAPI_KEYS = {"http_status", "sha256", "request_error"}
NEGATIVE_SIGNAL_KEYS = {
    "route_advertised",
    "content_md5_observed",
    "local_client_guard_observed",
}
COHERENCE_KEYS = {
    "identity_unchanged",
    "openapi_unchanged",
    "stable_server_epoch",
    "coherent",
    "blockers",
}
CAPABILITY_KEYS = {
    "capability_id",
    "scope",
    "status",
    "proof_level",
    "blocking",
    "evidence_refs",
    "reason",
}
GATE_DECISION_KEYS = {
    "p0_read_only",
    "lightrag_mutation",
    "knowledge_hub_promotion",
}
READ_ONLY_DECISION_KEYS = {"decision", "mutation_allowed"}
BLOCKED_DECISION_KEYS = {"decision", "blockers"}

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


@dataclass(frozen=True)
class CapabilitySpec:
    service_id: str
    scope: str


CAPABILITY_SPECS: dict[str, CapabilitySpec] = {
    "lightrag.legacy_identity_reconciliation": CapabilitySpec(
        service_id="lightrag",
        scope="lightrag_mutation",
    ),
    "lightrag.authoritative_payload_hash_lookup": CapabilitySpec(
        service_id="lightrag",
        scope="lightrag_mutation",
    ),
    "lightrag.service_enforced_fencing": CapabilitySpec(
        service_id="lightrag",
        scope="lightrag_mutation",
    ),
    "knowledge_hub.atomic_import": CapabilitySpec(
        service_id="knowledge_hub",
        scope="knowledge_hub_promotion",
    ),
    "knowledge_hub.single_use_capability": CapabilitySpec(
        service_id="knowledge_hub",
        scope="knowledge_hub_promotion",
    ),
    "knowledge_hub.watchdog_or_lease_ttl": CapabilitySpec(
        service_id="knowledge_hub",
        scope="knowledge_hub_promotion",
    ),
    "knowledge_hub.gate_close": CapabilitySpec(
        service_id="knowledge_hub",
        scope="knowledge_hub_promotion",
    ),
    "knowledge_hub.restart": CapabilitySpec(
        service_id="knowledge_hub",
        scope="knowledge_hub_promotion",
    ),
}


@dataclass(frozen=True)
class ServiceProbe:
    """Read-only endpoints used to bracket one service observation."""

    service_id: str
    health_url: str
    openapi_url: str


def produce_runtime_capability_evidence(
    *,
    http_client: httpx.Client,
    probes: Sequence[ServiceProbe],
    manifest_id: str,
    subject_revision: str,
    executable_tree_sha256: str,
    observed_at: datetime | None = None,
    negative_signals: Mapping[str, Mapping[str, bool]] | None = None,
) -> dict[str, Any]:
    """Collect a coherent, read-only, negative runtime capability audit.

    The caller owns the injected client, including timeout, transport, TLS, and
    redirect policy. Endpoint URLs are inputs only and never enter the returned
    public evidence.
    """

    probe_by_service = _validate_probes(probes)
    configured_signals = _validate_negative_signal_input(negative_signals or {})
    service_observations: dict[str, dict[str, Any]] = {}

    for service_id in SERVICE_IDS:
        probe = probe_by_service[service_id]
        pre_identity = _probe_identity(http_client, probe.health_url)
        pre_openapi, pre_route_advertised = _probe_openapi(
            http_client, probe.openapi_url
        )
        post_identity = _probe_identity(http_client, probe.health_url)
        post_openapi, post_route_advertised = _probe_openapi(
            http_client, probe.openapi_url
        )
        supplied = configured_signals.get(service_id, {})
        observation: dict[str, Any] = {
            "pre": {"identity": pre_identity, "openapi": pre_openapi},
            "post": {"identity": post_identity, "openapi": post_openapi},
            "negative_signals": {
                "route_advertised": pre_route_advertised or post_route_advertised,
                "content_md5_observed": supplied.get("content_md5_observed", False),
                "local_client_guard_observed": supplied.get(
                    "local_client_guard_observed", False
                ),
            },
        }
        observation["coherence"] = _recompute_service_coherence(service_id, observation)
        service_observations[service_id] = observation

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "observed_at": _format_utc(observed_at or datetime.now(timezone.utc)),
        "evidence_mode": EVIDENCE_MODE,
        "subject": {
            "revision": subject_revision,
            "executable_tree_sha256": executable_tree_sha256,
        },
        "policy": {
            "positive_attestation_supported": False,
            "live_mutation_attempted": False,
            "promotion_attempted": False,
        },
        "service_observations": service_observations,
        "capabilities": _negative_capability_rows(service_observations),
        "gate_decisions": {},
    }
    manifest["gate_decisions"] = recompute_gate_decisions(manifest)
    return manifest


def validate_runtime_capability_evidence(manifest: Mapping[str, Any]) -> list[str]:
    """Validate v2 evidence without trusting its declared gate decisions."""

    if not isinstance(manifest, Mapping):
        return ["runtime_capabilities_not_object"]

    blockers: list[str] = []
    if set(manifest) != TOP_LEVEL_KEYS:
        blockers.append("runtime_capabilities_top_level_keys_mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        blockers.append("runtime_capabilities_schema_mismatch")
    if not SAFE_ID_RE.fullmatch(str(manifest.get("manifest_id") or "")):
        blockers.append("runtime_capabilities_manifest_id_invalid")
    if _parse_utc(manifest.get("observed_at")) is None:
        blockers.append("runtime_capabilities_observed_at_invalid")
    if manifest.get("evidence_mode") != EVIDENCE_MODE:
        blockers.append("runtime_capabilities_evidence_mode_invalid")

    subject = manifest.get("subject")
    if not isinstance(subject, Mapping) or set(subject) != SUBJECT_KEYS:
        blockers.append("runtime_capabilities_subject_shape_invalid")
        subject = {}
    if not REVISION_RE.fullmatch(str(subject.get("revision") or "")):
        blockers.append("runtime_capabilities_subject_revision_invalid")
    if not SHA256_RE.fullmatch(str(subject.get("executable_tree_sha256") or "")):
        blockers.append("runtime_capabilities_executable_tree_invalid")

    policy = manifest.get("policy")
    if not isinstance(policy, Mapping) or set(policy) != POLICY_KEYS:
        blockers.append("runtime_capabilities_policy_shape_invalid")
        policy = {}
    if policy.get("positive_attestation_supported") is not False:
        blockers.append("runtime_capabilities_positive_attestation_policy_invalid")
    if policy.get("live_mutation_attempted") is not False:
        blockers.append("runtime_capabilities_live_mutation_invalid")
    if policy.get("promotion_attempted") is not False:
        blockers.append("runtime_capabilities_promotion_invalid")

    observations = manifest.get("service_observations")
    if not isinstance(observations, Mapping) or set(observations) != set(SERVICE_IDS):
        blockers.append("runtime_capabilities_service_observations_shape_invalid")
        observations = observations if isinstance(observations, Mapping) else {}
    for service_id in SERVICE_IDS:
        blockers.extend(
            _validate_service_observation(service_id, observations.get(service_id))
        )

    rows = manifest.get("capabilities")
    if not isinstance(rows, list):
        blockers.append("runtime_capabilities_rows_invalid")
        rows = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            blockers.append(f"runtime_capability_row_invalid:{index}")
            continue
        capability_id = str(row.get("capability_id") or f"index-{index}")
        if capability_id in seen:
            blockers.append(f"runtime_capability_duplicate_id:{capability_id}")
        seen.add(capability_id)
        spec = CAPABILITY_SPECS.get(capability_id)
        if spec is None:
            blockers.append(f"runtime_capability_unknown_id:{capability_id}")
            continue
        blockers.extend(_validate_capability_row(capability_id, spec, row, manifest))

    for capability_id in sorted(set(CAPABILITY_SPECS) - seen):
        blockers.append(f"runtime_capability_missing_id:{capability_id}")

    declared_decisions = manifest.get("gate_decisions")
    blockers.extend(_validate_gate_decision_shape(declared_decisions))
    declared_map = declared_decisions if isinstance(declared_decisions, Mapping) else {}
    recomputed_decisions = recompute_gate_decisions(manifest)
    for gate_name, expected_decision in recomputed_decisions.items():
        if declared_map.get(gate_name) != expected_decision:
            blockers.append(f"runtime_capabilities_gate_decisions_mismatch:{gate_name}")
    return sorted(set(blockers))


def recompute_gate_decisions(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the negative gate vector; no result is cached or trusted."""

    observations = manifest.get("service_observations")
    observation_map = observations if isinstance(observations, Mapping) else {}
    decisions: dict[str, Any] = {
        "p0_read_only": {"decision": "allowed", "mutation_allowed": False},
    }
    for service_id, gate_name in (
        ("lightrag", "lightrag_mutation"),
        ("knowledge_hub", "knowledge_hub_promotion"),
    ):
        blockers = {
            capability_id
            for capability_id, spec in CAPABILITY_SPECS.items()
            if spec.service_id == service_id
        }
        observation = observation_map.get(service_id)
        if isinstance(observation, Mapping):
            coherence = _recompute_service_coherence(service_id, observation)
            blockers.update(coherence["blockers"])
        else:
            blockers.add(f"{service_id}.observation_missing")
        decisions[gate_name] = {
            "decision": "blocked",
            "blockers": sorted(blockers),
        }
    return decisions


def _validate_probes(probes: Sequence[ServiceProbe]) -> dict[str, ServiceProbe]:
    probe_by_service: dict[str, ServiceProbe] = {}
    for probe in probes:
        if not isinstance(probe, ServiceProbe):
            raise TypeError("probes must contain ServiceProbe values")
        if probe.service_id not in SERVICE_IDS:
            raise ValueError(f"unsupported service probe: {probe.service_id}")
        if probe.service_id in probe_by_service:
            raise ValueError(f"duplicate service probe: {probe.service_id}")
        if not _is_http_url(probe.health_url) or not _is_http_url(probe.openapi_url):
            raise ValueError(f"invalid read-only endpoint for {probe.service_id}")
        probe_by_service[probe.service_id] = probe
    if set(probe_by_service) != set(SERVICE_IDS):
        raise ValueError(
            "exactly one LightRAG and one Knowledge Hub probe are required"
        )
    return probe_by_service


def _validate_negative_signal_input(
    signals: Mapping[str, Mapping[str, bool]],
) -> dict[str, dict[str, bool]]:
    if not isinstance(signals, Mapping):
        raise TypeError("negative_signals must be a mapping")
    result: dict[str, dict[str, bool]] = {}
    allowed = NEGATIVE_SIGNAL_KEYS - {"route_advertised"}
    for service_id, values in signals.items():
        if service_id not in SERVICE_IDS:
            raise ValueError(f"unsupported negative signal service: {service_id}")
        if not isinstance(values, Mapping) or not set(values) <= allowed:
            raise ValueError(f"invalid negative signals for {service_id}")
        if any(not isinstance(value, bool) for value in values.values()):
            raise ValueError(f"negative signals must be booleans for {service_id}")
        result[service_id] = dict(values)
    return result


def _probe_identity(http_client: httpx.Client, url: str) -> dict[str, Any]:
    response, error = _read_only_get(http_client, url)
    payload = _json_object(response)
    headers = response.headers if response is not None else {}
    return {
        "http_status": response.status_code if response is not None else None,
        "service_id": _bounded_identity_value(
            payload.get("service_id") or headers.get("x-service-id")
        ),
        "version": _bounded_identity_value(
            payload.get("version") or headers.get("x-service-version")
        ),
        "server_epoch": _bounded_identity_value(
            payload.get("server_epoch")
            or payload.get("process_started_at")
            or headers.get("x-server-epoch")
            or headers.get("x-process-started-at")
        ),
        "executable_fingerprint": _bounded_identity_value(
            payload.get("executable_fingerprint")
            or headers.get("x-executable-fingerprint")
        ),
        "request_error": error,
    }


def _probe_openapi(http_client: httpx.Client, url: str) -> tuple[dict[str, Any], bool]:
    response, error = _read_only_get(http_client, url)
    payload = _json_object(response)
    successful = response is not None and 200 <= response.status_code < 300
    content = response.content if successful else b""
    paths = payload.get("paths") if isinstance(payload.get("paths"), Mapping) else {}
    return (
        {
            "http_status": response.status_code if response is not None else None,
            "sha256": hashlib.sha256(content).hexdigest() if content else None,
            "request_error": error,
        },
        bool(paths),
    )


def _read_only_get(
    http_client: httpx.Client,
    url: str,
) -> tuple[httpx.Response | None, str | None]:
    try:
        response = http_client.get(url, headers={"accept": "application/json"})
    except httpx.RequestError as exc:
        return None, type(exc).__name__
    return response, None


def _json_object(response: httpx.Response | None) -> Mapping[str, Any]:
    if response is None:
        return {}
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _negative_capability_rows(
    service_observations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capability_id, spec in sorted(CAPABILITY_SPECS.items()):
        observation = service_observations[spec.service_id]
        signals = observation["negative_signals"]
        proof_level = (
            "observed"
            if signals["content_md5_observed"] or signals["local_client_guard_observed"]
            else "discovered"
        )
        rows.append(
            {
                "capability_id": capability_id,
                "scope": spec.scope,
                "status": "not_provable",
                "proof_level": proof_level,
                "blocking": True,
                "evidence_refs": [
                    f"/service_observations/{spec.service_id}/negative_signals",
                    f"/service_observations/{spec.service_id}/coherence",
                ],
                "reason": (
                    "Read-only discovery and local observations cannot provide "
                    "service-signed positive capability attestation."
                ),
            }
        )
    return rows


def _validate_service_observation(service_id: str, value: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(value, Mapping):
        return [f"runtime_capabilities_service_observation_invalid:{service_id}"]
    if set(value) != SERVICE_OBSERVATION_KEYS:
        blockers.append(
            f"runtime_capabilities_service_observation_keys_mismatch:{service_id}"
        )
    for phase in ("pre", "post"):
        bracket = value.get(phase)
        if not isinstance(bracket, Mapping) or set(bracket) != BRACKET_KEYS:
            blockers.append(f"runtime_capabilities_{phase}_shape_invalid:{service_id}")
            continue
        blockers.extend(
            _validate_identity_snapshot(service_id, phase, bracket.get("identity"))
        )
        blockers.extend(
            _validate_openapi_snapshot(service_id, phase, bracket.get("openapi"))
        )

    signals = value.get("negative_signals")
    if not isinstance(signals, Mapping) or set(signals) != NEGATIVE_SIGNAL_KEYS:
        blockers.append(
            f"runtime_capabilities_negative_signals_shape_invalid:{service_id}"
        )
    elif any(not isinstance(signals.get(key), bool) for key in NEGATIVE_SIGNAL_KEYS):
        blockers.append(
            f"runtime_capabilities_negative_signals_type_invalid:{service_id}"
        )

    coherence = value.get("coherence")
    if not isinstance(coherence, Mapping) or set(coherence) != COHERENCE_KEYS:
        blockers.append(f"runtime_capabilities_coherence_shape_invalid:{service_id}")
    else:
        if any(
            not isinstance(coherence.get(key), bool)
            for key in (
                "identity_unchanged",
                "openapi_unchanged",
                "stable_server_epoch",
                "coherent",
            )
        ):
            blockers.append(f"runtime_capabilities_coherence_type_invalid:{service_id}")
        if not _is_string_list(coherence.get("blockers")):
            blockers.append(
                f"runtime_capabilities_coherence_blockers_invalid:{service_id}"
            )
        if dict(coherence) != _recompute_service_coherence(service_id, value):
            blockers.append(f"runtime_capabilities_coherence_mismatch:{service_id}")
    return blockers


def _validate_identity_snapshot(service_id: str, phase: str, value: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(value, Mapping) or set(value) != IDENTITY_KEYS:
        return [f"runtime_capabilities_identity_shape_invalid:{service_id}:{phase}"]
    status = value.get("http_status")
    if status is not None and (not isinstance(status, int) or isinstance(status, bool)):
        blockers.append(
            f"runtime_capabilities_identity_status_invalid:{service_id}:{phase}"
        )
    for key in (
        "service_id",
        "version",
        "server_epoch",
        "executable_fingerprint",
        "request_error",
    ):
        field = value.get(key)
        if field is not None and (
            not isinstance(field, str) or not field or len(field) > 256
        ):
            blockers.append(
                f"runtime_capabilities_identity_field_invalid:{service_id}:{phase}:{key}"
            )
    declared_service = value.get("service_id")
    if declared_service is not None and declared_service != service_id:
        blockers.append(
            f"runtime_capabilities_identity_service_mismatch:{service_id}:{phase}"
        )
    return blockers


def _validate_openapi_snapshot(service_id: str, phase: str, value: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(value, Mapping) or set(value) != OPENAPI_KEYS:
        return [f"runtime_capabilities_openapi_shape_invalid:{service_id}:{phase}"]
    status = value.get("http_status")
    if status is not None and (not isinstance(status, int) or isinstance(status, bool)):
        blockers.append(
            f"runtime_capabilities_openapi_status_invalid:{service_id}:{phase}"
        )
    digest = value.get("sha256")
    if digest is not None and not SHA256_RE.fullmatch(str(digest)):
        blockers.append(
            f"runtime_capabilities_openapi_hash_invalid:{service_id}:{phase}"
        )
    error = value.get("request_error")
    if error is not None and (
        not isinstance(error, str) or not error or len(error) > 256
    ):
        blockers.append(
            f"runtime_capabilities_openapi_error_invalid:{service_id}:{phase}"
        )
    return blockers


def _validate_capability_row(
    capability_id: str,
    spec: CapabilitySpec,
    row: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if set(row) != CAPABILITY_KEYS:
        blockers.append(f"runtime_capability_keys_mismatch:{capability_id}")
    if row.get("scope") != spec.scope:
        blockers.append(f"runtime_capability_scope_mismatch:{capability_id}")
    status = row.get("status")
    if not isinstance(status, str) or status not in CAPABILITY_STATUSES:
        blockers.append(f"runtime_capability_status_invalid:{capability_id}")
    elif status == "available":
        blockers.append(
            f"runtime_capability_positive_claim_unsupported:{capability_id}"
        )
    proof_level = row.get("proof_level")
    if not isinstance(proof_level, str) or proof_level not in PROOF_LEVELS:
        blockers.append(f"runtime_capability_proof_level_invalid:{capability_id}")
    elif proof_level == "deployment_bound":
        blockers.append(
            f"runtime_capability_deployment_bound_unsupported:{capability_id}"
        )
    if status == "unavailable" and proof_level == "discovered":
        blockers.append(
            f"runtime_capability_status_proof_contradiction:{capability_id}"
        )
    if row.get("blocking") is not True:
        blockers.append(f"runtime_capability_not_blocking:{capability_id}")
    reason = row.get("reason")
    if not isinstance(reason, str) or not reason or len(reason) > 512:
        blockers.append(f"runtime_capability_reason_invalid:{capability_id}")

    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        blockers.append(f"runtime_capability_evidence_missing:{capability_id}")
    else:
        expected_prefix = f"/service_observations/{spec.service_id}/"
        for ref in evidence_refs:
            if not isinstance(ref, str):
                blockers.append(
                    f"runtime_capability_evidence_ref_invalid:{capability_id}"
                )
                continue
            if not ref.startswith(expected_prefix):
                blockers.append(
                    f"runtime_capability_evidence_scope_mismatch:{capability_id}"
                )
            if _resolve_json_pointer(manifest, ref) is _MISSING:
                blockers.append(
                    f"runtime_capability_evidence_unresolved:{capability_id}"
                )
    return blockers


def _validate_gate_decision_shape(value: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(value, Mapping) or set(value) != GATE_DECISION_KEYS:
        return ["runtime_capabilities_gate_decisions_shape_invalid"]
    p0 = value.get("p0_read_only")
    if not isinstance(p0, Mapping) or set(p0) != READ_ONLY_DECISION_KEYS:
        blockers.append("runtime_capabilities_p0_decision_shape_invalid")
    for gate_name in ("lightrag_mutation", "knowledge_hub_promotion"):
        decision = value.get(gate_name)
        if not isinstance(decision, Mapping) or set(decision) != BLOCKED_DECISION_KEYS:
            blockers.append(
                f"runtime_capabilities_gate_decision_shape_invalid:{gate_name}"
            )
        elif not _is_string_list(decision.get("blockers")):
            blockers.append(f"runtime_capabilities_gate_blockers_invalid:{gate_name}")
    return blockers


def _recompute_service_coherence(
    service_id: str, value: Mapping[str, Any]
) -> dict[str, Any]:
    pre = value.get("pre") if isinstance(value.get("pre"), Mapping) else {}
    post = value.get("post") if isinstance(value.get("post"), Mapping) else {}
    pre_identity = (
        pre.get("identity") if isinstance(pre.get("identity"), Mapping) else {}
    )
    post_identity = (
        post.get("identity") if isinstance(post.get("identity"), Mapping) else {}
    )
    pre_openapi = pre.get("openapi") if isinstance(pre.get("openapi"), Mapping) else {}
    post_openapi = (
        post.get("openapi") if isinstance(post.get("openapi"), Mapping) else {}
    )

    identity_fields = (
        "service_id",
        "version",
        "server_epoch",
        "executable_fingerprint",
    )
    identity_unchanged = all(
        pre_identity.get(key) == post_identity.get(key) for key in identity_fields
    )
    pre_epoch = pre_identity.get("server_epoch")
    post_epoch = post_identity.get("server_epoch")
    stable_server_epoch = (
        isinstance(pre_epoch, str)
        and bool(pre_epoch)
        and isinstance(post_epoch, str)
        and pre_epoch == post_epoch
    )
    pre_hash = pre_openapi.get("sha256")
    post_hash = post_openapi.get("sha256")
    openapi_unchanged = (
        isinstance(pre_hash, str)
        and SHA256_RE.fullmatch(pre_hash) is not None
        and pre_hash == post_hash
    )

    blockers: list[str] = []
    if not _successful_status(
        pre_identity.get("http_status")
    ) or not _successful_status(post_identity.get("http_status")):
        blockers.append(f"{service_id}.health_unavailable")
    if not _successful_status(pre_openapi.get("http_status")) or not _successful_status(
        post_openapi.get("http_status")
    ):
        blockers.append(f"{service_id}.openapi_unavailable")
    if not pre_epoch or not post_epoch:
        blockers.append(f"{service_id}.server_epoch_missing")
    elif pre_epoch != post_epoch:
        blockers.append(f"{service_id}.server_epoch_changed")
    if not pre_identity.get("service_id") or not post_identity.get("service_id"):
        blockers.append(f"{service_id}.service_identity_missing")
    if not pre_identity.get("version") or not post_identity.get("version"):
        blockers.append(f"{service_id}.service_version_missing")
    if not pre_identity.get("executable_fingerprint") or not post_identity.get(
        "executable_fingerprint"
    ):
        blockers.append(f"{service_id}.executable_fingerprint_missing")
    if not identity_unchanged:
        blockers.append(f"{service_id}.server_identity_changed")
    if not pre_hash or not post_hash:
        blockers.append(f"{service_id}.openapi_fingerprint_missing")
    elif pre_hash != post_hash:
        blockers.append(f"{service_id}.openapi_changed")

    return {
        "identity_unchanged": identity_unchanged,
        "openapi_unchanged": openapi_unchanged,
        "stable_server_epoch": stable_server_epoch,
        "coherent": not blockers,
        "blockers": sorted(set(blockers)),
    }


def _resolve_json_pointer(payload: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    current = payload
    for token in pointer[1:].split("/"):
        decoded = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and decoded in current:
            current = current[decoded]
        elif (
            isinstance(current, list)
            and decoded.isdigit()
            and int(decoded) < len(current)
        ):
            current = current[int(decoded)]
        else:
            return _MISSING
    return current


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _bounded_identity_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text and len(text) <= 256 else None


def _is_http_url(value: str) -> bool:
    try:
        url = httpx.URL(value)
    except (TypeError, ValueError):
        return False
    return (
        url.scheme in {"http", "https"}
        and bool(url.host)
        and not url.userinfo
        and not url.fragment
    )


def _successful_status(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 200 <= value < 300


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item for item in value
    )


_MISSING = object()
