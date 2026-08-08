from __future__ import annotations

from app.kb_cutover_score import score_cutover_certification


def _passing_payload() -> dict:
    return {
        "inventory": {"canonical_rows": 100, "matched_canonical_rows": 100, "unclassified_rows": 0},
        "package_integrity": {"expected_packages": 50, "complete_packages": 50, "orphaned_rows": 0},
        "vector_provenance": {
            "expected_visual_points": 50,
            "active_qdrant_points": 50,
            "model_ok": True,
            "dimension_ok": True,
            "collection_ok": True,
        },
        "search_parity": {
            "strata": [
                {"name": "explicit", "score": 1.0, "threshold": 0.8, "critical": True},
                {"name": "semantic", "score": 1.0, "threshold": 0.8, "critical": True},
            ]
        },
        "preview_dto_library_stats": {
            "checks": [
                {"name": "stats", "passed": True},
                {"name": "preview", "passed": True},
                {"name": "library", "passed": True},
            ]
        },
        "chat_context_sources": {
            "answers_cite_sources": True,
            "source_card_persistence_ok": True,
            "context_sources_grouping_ok": True,
            "preview_links_ok": True,
            "citation_path_ok": True,
        },
        "dual_fallback_independence": {"kh_native_success_rate": 1.0, "fallback_rate": 0.0},
        "safety_no_leak": {"leak_count": 0, "public_errors_safe": True, "checks_complete": True},
        "import": {
            "mutation_performed": False,
            "granular_import_available": True,
            "vector_reuse_available": True,
        },
    }


def test_cutover_score_perfect_fixture_passes_gate() -> None:
    result = score_cutover_certification(_passing_payload())

    assert result.score == 1.0
    assert result.passed is True
    assert result.decision == "go_ready_waiting_for_go"
    assert result.hard_cap is None
    assert result.next_actions == []


def test_no_leak_failure_caps_below_gate() -> None:
    payload = _passing_payload()
    payload["safety_no_leak"] = {"leak_count": 1, "public_errors_safe": True, "checks_complete": True}

    result = score_cutover_certification(payload)

    assert result.score == 0.88
    assert result.passed is False
    assert "no_leak_failure" in result.hard_cap_reasons


def test_missing_no_leak_evidence_caps_below_gate() -> None:
    payload = _passing_payload()
    payload.pop("safety_no_leak")

    result = score_cutover_certification(payload)

    assert result.score == 0.88
    assert result.passed is False
    assert "safety_no_leak_missing" in result.hard_cap_reasons
    assert "safety_no_leak_below_gate" in result.blockers


def test_unclassified_rows_cap_to_084() -> None:
    payload = _passing_payload()
    payload["inventory"]["unclassified_rows"] = 1

    result = score_cutover_certification(payload)

    assert result.score == 0.84
    assert result.passed is False
    assert "unclassified_canonical_rows" in result.hard_cap_reasons


def test_failed_public_surface_check_caps_below_gate() -> None:
    payload = _passing_payload()
    payload["preview_dto_library_stats"]["checks"][1]["passed"] = False

    result = score_cutover_certification(payload)

    assert result.score == 0.88
    assert result.passed is False
    assert "critical_public_surface_check_failed" in result.hard_cap_reasons


def test_critical_search_stratum_caps_below_gate() -> None:
    payload = _passing_payload()
    payload["search_parity"]["strata"][0]["score"] = 0.5

    result = score_cutover_certification(payload)

    assert result.score == 0.88
    assert result.passed is False
    assert "critical_stratum_below_threshold:explicit" in result.hard_cap_reasons


def test_import_mutation_without_manifest_caps_to_080() -> None:
    payload = _passing_payload()
    payload["import"] = {
        "mutation_performed": True,
        "manifest_written": False,
        "granular_import_available": True,
        "vector_reuse_available": True,
    }

    result = score_cutover_certification(payload)

    assert result.score == 0.8
    assert result.passed is False
    assert "import_mutation_without_manifest" in result.hard_cap_reasons


def test_current_style_payload_reports_missing_import_and_vector_reuse_blockers() -> None:
    payload = _passing_payload()
    payload["inventory"] = {"canonical_rows": 100, "matched_canonical_rows": 0, "unclassified_rows": 0}
    payload["search_parity"] = {"strata": [{"name": "explicit", "score": 0.0, "critical": True}]}
    payload["chat_context_sources"]["source_card_persistence_ok"] = False
    payload["import"] = {
        "mutation_performed": False,
        "granular_import_available": False,
        "vector_reuse_available": False,
    }

    result = score_cutover_certification(payload)

    assert result.passed is False
    assert "no_granular_kh_visual_package_import" in result.blockers
    assert "no_verified_chroma_vector_reuse_path" in result.blockers
    assert "chat_source_or_citation_path_broken" in result.hard_cap_reasons
