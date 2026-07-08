from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dantedash_kh_parity_eval.py"


def test_parity_eval_scores_certification_envelope_and_sanitizes_output(tmp_path: Path) -> None:
    payload = {
        "scoring_payload": {
            "inventory": {"canonical_rows": 1, "matched_canonical_rows": 1, "unclassified_rows": 0},
            "package_integrity": {"expected_packages": 1, "complete_packages": 1, "orphaned_rows": 0},
            "vector_provenance": {
                "expected_visual_points": 1,
                "active_qdrant_points": 1,
                "model_ok": True,
                "dimension_ok": True,
                "collection_ok": True,
                "debug_path": "/Users/vidigal/private",
            },
            "search_parity": {"strata": [{"name": "explicit", "score": 1.0, "threshold": 0.8, "critical": True}]},
            "preview_dto_library_stats": {"checks": [{"name": "preview", "passed": True}]},
            "chat_context_sources": {
                "answers_cite_sources": True,
                "source_card_persistence_ok": True,
                "context_sources_grouping_ok": True,
                "preview_links_ok": True,
                "citation_path_ok": True,
            },
            "dual_fallback_independence": {"kh_native_success_rate": 1.0, "fallback_rate": 0.0},
            "safety_no_leak": {"leak_count": 0, "public_errors_safe": True, "checks_complete": True},
            "import": {"granular_import_available": True, "vector_reuse_available": True, "mutation_performed": False},
        }
    }
    input_path = tmp_path / "certification.json"
    output_path = tmp_path / "score.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--certification-input",
            str(input_path),
            "--output-json",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    stdout_payload = json.loads(result.stdout)
    file_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload["passed"] is True
    assert file_payload["passed"] is True
    assert "/Users/" not in result.stdout
    assert "/Users/" not in output_path.read_text(encoding="utf-8")


def test_parity_eval_malformed_certification_input_fails_closed(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--certification-input", str(input_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["score"] == 0.0
    assert "certification_input_must_be_object" in payload["blockers"]
