"""Deterministic Chroma to Knowledge Hub cutover scoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


CUTOVER_GATE = 0.89

DIMENSION_WEIGHTS: dict[str, float] = {
    "inventory_coverage": 0.16,
    "package_integrity": 0.14,
    "vector_provenance": 0.10,
    "search_parity": 0.16,
    "preview_dto_library_stats": 0.12,
    "chat_context_sources": 0.12,
    "dual_fallback_independence": 0.10,
    "safety_no_leak": 0.10,
}

DIMENSION_SOURCE_SECTIONS: dict[str, str] = {
    "inventory_coverage": "inventory",
    "package_integrity": "package_integrity",
    "vector_provenance": "vector_provenance",
    "search_parity": "search_parity",
    "preview_dto_library_stats": "preview_dto_library_stats",
    "chat_context_sources": "chat_context_sources",
    "dual_fallback_independence": "dual_fallback_independence",
    "safety_no_leak": "safety_no_leak",
}


@dataclass(frozen=True)
class CutoverDimension:
    key: str
    weight: float
    score: float
    weighted: float
    evidence: dict[str, Any]


@dataclass(frozen=True)
class CutoverScoreResult:
    score: float
    raw_weighted_score: float
    gate: float
    passed: bool
    decision: str
    dimensions: list[CutoverDimension]
    hard_cap: float | None
    hard_cap_reasons: list[str]
    blockers: list[str]
    next_actions: list[str]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dimensions"] = [asdict(item) for item in self.dimensions]
        return payload


def score_cutover_certification(payload: Mapping[str, Any], *, gate: float = CUTOVER_GATE) -> CutoverScoreResult:
    """Score a cutover certification payload.

    The function accepts intentionally simple dicts so fixture reports and live
    runtime reports can use the same deterministic gate.
    """

    dimension_scores = {
        "inventory_coverage": _inventory_score(_section(payload, "inventory")),
        "package_integrity": _package_integrity_score(_section(payload, "package_integrity")),
        "vector_provenance": _vector_score(_section(payload, "vector_provenance")),
        "search_parity": _average_score(_section(payload, "search_parity"), default_key="strata"),
        "preview_dto_library_stats": _average_score(_section(payload, "preview_dto_library_stats"), default_key="checks"),
        "chat_context_sources": _chat_score(_section(payload, "chat_context_sources")),
        "dual_fallback_independence": _dual_score(_section(payload, "dual_fallback_independence")),
        "safety_no_leak": _safety_score(_section(payload, "safety_no_leak")),
    }

    dimensions = [
        CutoverDimension(
            key=key,
            weight=weight,
            score=score,
            weighted=score * weight,
            evidence=_section(payload, DIMENSION_SOURCE_SECTIONS[key]),
        )
        for key, weight in DIMENSION_WEIGHTS.items()
        for score in [dimension_scores[key]]
    ]
    raw_weighted_score = sum(item.weighted for item in dimensions)

    hard_cap, hard_cap_reasons = _hard_cap(payload, dimension_scores)
    final_score = min(raw_weighted_score, hard_cap) if hard_cap is not None else raw_weighted_score
    blockers = _blockers(payload, dimension_scores, hard_cap_reasons)
    passed = final_score >= gate and not blockers
    weakest = min(dimensions, key=lambda item: item.score)
    next_actions = [] if passed else _next_actions(weakest.key, blockers)
    decision = "go_ready_waiting_for_go" if passed else "no_go_continue_repairs"

    return CutoverScoreResult(
        score=round(final_score, 4),
        raw_weighted_score=round(raw_weighted_score, 4),
        gate=gate,
        passed=passed,
        decision=decision,
        dimensions=dimensions,
        hard_cap=hard_cap,
        hard_cap_reasons=hard_cap_reasons,
        blockers=blockers,
        next_actions=next_actions,
    )


def _section(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _inventory_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    canonical = _positive_number(section.get("canonical_rows"), fallback=_positive_number(section.get("total_rows")))
    if canonical <= 0:
        return 0.0
    matched = _positive_number(section.get("matched_canonical_rows"))
    accepted = _positive_number(section.get("accepted_exclusion_rows"))
    return _clamp((matched + accepted) / canonical)


def _package_integrity_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    expected = _positive_number(section.get("expected_packages"))
    if expected <= 0:
        return 0.0
    complete = _positive_number(section.get("complete_packages"))
    orphaned = _positive_number(section.get("orphaned_rows"))
    return _clamp((complete / expected) * (1.0 - min(orphaned / max(expected, 1.0), 1.0)))


def _vector_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    expected = _positive_number(section.get("expected_visual_points"))
    active_points = _positive_number(section.get("active_qdrant_points"))
    model_ok = bool(section.get("model_ok", False))
    dimension_ok = bool(section.get("dimension_ok", False))
    collection_ok = bool(section.get("collection_ok", False))
    runtime_score = sum([model_ok, dimension_ok, collection_ok]) / 3.0
    if expected <= 0:
        return runtime_score * 0.5
    coverage = min(active_points / expected, 1.0)
    return _clamp(0.45 * runtime_score + 0.55 * coverage)


def _average_score(section: Mapping[str, Any], *, default_key: str) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    checks = section.get(default_key)
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        return 0.0
    scores: list[float] = []
    for item in checks:
        if not isinstance(item, Mapping):
            continue
        item_score = _explicit_score(item)
        if item_score is None:
            item_score = 1.0 if item.get("passed") is True or item.get("ok") is True else 0.0
        scores.append(item_score)
    return _clamp(sum(scores) / len(scores)) if scores else 0.0


def _chat_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    checks = [
        section.get("answers_cite_sources"),
        section.get("source_card_persistence_ok"),
        section.get("context_sources_grouping_ok"),
        section.get("preview_links_ok"),
        section.get("citation_path_ok"),
    ]
    present = [item for item in checks if item is not None]
    if not present:
        return 0.0
    return sum(1.0 for item in present if bool(item)) / len(present)


def _dual_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    native_success = _bounded_number(section.get("kh_native_success_rate"))
    fallback_rate = _bounded_number(section.get("fallback_rate"))
    return _clamp(native_success * (1.0 - fallback_rate))


def _safety_score(section: Mapping[str, Any]) -> float:
    explicit = _explicit_score(section)
    if explicit is not None:
        return explicit
    leak_count = _positive_number(section.get("leak_count"))
    public_errors_safe = section.get("public_errors_safe", True)
    if leak_count > 0 or public_errors_safe is False:
        return 0.0
    return 1.0


def _hard_cap(payload: Mapping[str, Any], dimension_scores: Mapping[str, float]) -> tuple[float | None, list[str]]:
    caps: list[tuple[float, str]] = []
    inventory = _section(payload, "inventory")
    chat = _section(payload, "chat_context_sources")
    imports = _section(payload, "import")
    search = _section(payload, "search_parity")
    safety = _section(payload, "safety_no_leak")

    if _positive_number(safety.get("leak_count")) > 0 or safety.get("public_errors_safe") is False:
        caps.append((0.88, "no_leak_failure"))
    if not isinstance(payload.get("safety_no_leak"), Mapping):
        caps.append((0.88, "safety_no_leak_missing"))
    elif safety.get("checks_complete") is not True or dimension_scores.get("safety_no_leak", 0.0) < 1.0:
        caps.append((0.88, "safety_no_leak_incomplete_or_failing"))
    if _positive_number(inventory.get("unclassified_rows")) > 0:
        caps.append((0.84, "unclassified_canonical_rows"))
    if chat.get("source_card_persistence_ok") is False or chat.get("citation_path_ok") is False:
        caps.append((0.88, "chat_source_or_citation_path_broken"))
    for item in search.get("strata", []) if isinstance(search.get("strata"), list) else []:
        if not isinstance(item, Mapping):
            continue
        threshold = _bounded_number(item.get("threshold"), fallback=0.8)
        score = _explicit_score(item)
        if item.get("critical") is True and (score is None or score < threshold):
            caps.append((0.88, f"critical_stratum_below_threshold:{item.get('name', 'unknown')}"))
    if imports.get("mutation_performed") is True and imports.get("manifest_written") is not True:
        caps.append((0.80, "import_mutation_without_manifest"))
    if _public_surface_has_failed_critical_check(_section(payload, "preview_dto_library_stats")):
        caps.append((0.88, "critical_public_surface_check_failed"))
    if dimension_scores.get("preview_dto_library_stats", 0.0) <= 0.0:
        caps.append((0.88, "kh_public_dto_surfaces_unavailable"))

    if not caps:
        return None, []
    cap = min(value for value, _reason in caps)
    return cap, [reason for _value, reason in caps]


def _blockers(
    payload: Mapping[str, Any],
    dimension_scores: Mapping[str, float],
    hard_cap_reasons: Sequence[str],
) -> list[str]:
    blockers = list(hard_cap_reasons)
    imports = _section(payload, "import")
    if imports.get("granular_import_available") is False:
        blockers.append("no_granular_kh_visual_package_import")
    if imports.get("vector_reuse_available") is False:
        blockers.append("no_verified_chroma_vector_reuse_path")
    if "safety_no_leak" not in payload or dimension_scores.get("safety_no_leak", 0.0) < 1.0:
        blockers.append("safety_no_leak_below_gate")
    if dimension_scores.get("inventory_coverage", 0.0) < 0.89:
        blockers.append("inventory_coverage_below_gate")
    if dimension_scores.get("search_parity", 0.0) < 0.89:
        blockers.append("search_parity_below_gate")
    if dimension_scores.get("chat_context_sources", 0.0) < 0.89:
        blockers.append("chat_context_sources_below_gate")
    return sorted(set(blockers))


def _next_actions(weakest_key: str, blockers: Sequence[str]) -> list[str]:
    actions_by_dimension = {
        "inventory_coverage": "Create a KH-owned DanteDash visual package import that preserves source_sha256 and dante_image_id.",
        "package_integrity": "Promote linked image/card/decoupage/video package metadata into the KH manifest contract.",
        "vector_provenance": "Backfill only missing Voyage multimodal 1024 visual vectors through KH-owned ingest or a verified vector-reuse path.",
        "search_parity": "Run the fixed query suite against KH-native retrieval and repair missing strata before relying on fallback.",
        "preview_dto_library_stats": "Expose KH item, preview, stats, and listing DTOs compatible with DanteDash routes.",
        "chat_context_sources": "Wire KH-native retrieval into chat source cards and persisted context sources before cutover.",
        "dual_fallback_independence": "Reduce Chroma fallback dependence in dual mode and rerun telemetry.",
        "safety_no_leak": "Fix public payload redaction before any cutover attempt.",
    }
    actions = [actions_by_dimension.get(weakest_key, "Repair the weakest cutover dimension and rerun certification.")]
    if "no_granular_kh_visual_package_import" in blockers:
        actions.append("Add or expose an official KH import surface for DanteDash package manifests instead of direct Qdrant writes.")
    if "no_verified_chroma_vector_reuse_path" in blockers:
        actions.append("Either verify a safe vector-copy path or accept a targeted Voyage backfill with cost and manifest evidence.")
    if "safety_no_leak_below_gate" in blockers:
        actions.append("Fix public report/output redaction and rerun the no-leak scan before any cutover recommendation.")
    return actions


def _explicit_score(section: Mapping[str, Any]) -> float | None:
    if "score" not in section:
        return None
    return _bounded_number(section.get("score"))


def _public_surface_has_failed_critical_check(section: Mapping[str, Any]) -> bool:
    checks = section.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)):
        return True
    for item in checks:
        if not isinstance(item, Mapping):
            return True
        if item.get("critical") is False:
            continue
        if item.get("passed") is False or item.get("ok") is False:
            return True
    return False


def _positive_number(value: Any, *, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < 0:
        return fallback
    return number


def _bounded_number(value: Any, *, fallback: float = 0.0) -> float:
    return _clamp(_positive_number(value, fallback=fallback))


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)
