from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import docling_kh_lightrag_cag_harness as subject


def write_docling_run(root: Path, name: str, rows: list[dict]) -> Path:
    run_dir = root / name
    run_dir.mkdir(parents=True)
    summary = {
        "run_id": name,
        "schema_version": "docling_cinema_batch.v1",
        "total_files": len(rows),
        "by_status": {"converted": sum(1 for row in rows if row.get("status") == "converted")},
    }
    (run_dir / "docling-cinema-batch-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with (run_dir / "docling-cinema-batch-output-index.jsonl").open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows, 1):
            output_relative = row.get("output_relative_path", f"outputs/{name}-{index}")
            output_dir = run_dir / output_relative
            output_dir.mkdir(parents=True, exist_ok=True)
            output_files = row.get("output_files", {f"{name}-{index}.md": "# Fixture\n"})
            for filename, content in output_files.items():
                path = output_dir / filename
                if isinstance(content, bytes):
                    path.write_bytes(content)
                else:
                    path.write_text(str(content), encoding="utf-8")
            payload = {
                "bytes": 1000 + index,
                "docling_level": row.get("docling_level", "C"),
                "error": "",
                "is_large": False,
                "output_relative_path": output_relative,
                "page_count": row.get("page_count", 10),
                "row_number": index,
                "sampled_text_chars": 500,
                "selection_reason": "fixture",
                "source_relative_path": row["source_relative_path"],
                "source_root_label": "cinema",
                "source_sha256": row.get("source_sha256", ""),
                "status": row.get("status", "converted"),
                "text_probe_status": "healthy",
                "topic_folder": row.get("topic_folder", "cinematography"),
            }
            for key, value in row.items():
                payload.setdefault(key, value)
            handle.write(json.dumps(payload) + "\n")
    return run_dir


def write_overlay(root: Path, *, include_unknown: bool = False) -> Path:
    run_dir = root / "overlay"
    run_dir.mkdir(parents=True, exist_ok=True)
    pages = [
        {
            "label": "manual",
            "page": 10,
            "overlay_level": "full_B_enriched",
            "selected_output": str((root / "full/page-0010").resolve()),
            "metrics": {"pictures": 2, "classification_annotations": 1},
        },
        {
            "label": "manual",
            "page": 11,
            "overlay_level": "base_only_due_to_visual_timeout",
            "selected_output": str((root / "base/page-0011").resolve()),
            "metrics": {"pictures": 0, "classification_annotations": 0},
        },
    ]
    by_overlay_level = {"full_B_enriched": 1, "base_only_due_to_visual_timeout": 1}
    if include_unknown:
        pages.append(
            {
                "label": "manual",
                "page": 12,
                "overlay_level": "future_overlay_level",
                "selected_output": str((root / "unknown/page-0012").resolve()),
                "metrics": {"pictures": 1, "classification_annotations": 0},
            }
        )
        by_overlay_level["future_overlay_level"] = 1
    summary = {
        "run_id": "overlay",
        "total_overlay_pages": len(pages),
        "by_overlay_level": by_overlay_level,
    }
    manifest = {"pages": pages}
    (run_dir / "overlay-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_dir / "overlay-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def build_config(tmp_path: Path, *, expected_total: int = 4) -> subject.HarnessConfig:
    runs = tmp_path / "runs"
    full = write_docling_run(
        runs,
        "full",
        [
            {"source_relative_path": "cinematography/book-a.pdf", "source_sha256": "a" * 64},
            {"source_relative_path": "editing/book-b.pdf", "source_sha256": "b" * 64, "topic_folder": "editing"},
        ],
    )
    pending = write_docling_run(
        runs,
        "pending",
        [{"source_relative_path": "lighting/book-c.pdf", "source_sha256": "c" * 64, "topic_folder": "lighting"}],
    )
    retry = write_docling_run(
        runs,
        "retry",
        [{"source_relative_path": "camera/book-d.pdf", "source_sha256": "d" * 64, "topic_folder": "camera"}],
    )
    overlay = write_overlay(runs)
    return subject.HarnessConfig(
        run_id="fixture-run",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=expected_total,
        qwen_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_all_certifies_complete_fixture_without_mutation(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is True
    assert result["certification"]["mutation_performed"] is False
    assert (config.run_dir / "p1-package-contract.json").exists()
    assert (config.run_dir / "phase-ledger.json").exists()
    assert (config.run_dir / "docling-normalized-output.jsonl").exists()
    assert (config.run_dir / "package-crosswalk.jsonl").exists()
    assert (config.run_dir / "cag-pack-candidates.jsonl").exists()
    phases = [phase["phase"] for phase in result["ledger"]["phases"]]
    assert phases == ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
    p7 = next(phase for phase in result["ledger"]["phases"] if phase["phase"] == "P7")
    assert p7["counts"]["pre_certification_phases"] == 8
    assert p7["counts"]["phase_artifacts_checked"] >= 7
    proof = json.loads((config.run_dir / "p0-docling-proof.json").read_text(encoding="utf-8"))
    assert proof["converted_total"] == 4
    assert proof["docling_conversion_invoked"] is False
    contract = json.loads((config.run_dir / "p1-package-contract.json").read_text(encoding="utf-8"))
    assert contract["visual_analysis"]["qwen_vision_model"] == "qwen-3.7-max"
    assert contract["docling_conversion_invoked"] is False
    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    assert "docling_document" in {row["artifact_layer"] for row in normalized}
    assert "docling_output_file" in {row["artifact_layer"] for row in normalized}


def test_real_certification_declares_legacy_rollout_provenance_without_governed_schema(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    result = subject.run_all(config)

    certification = result["certification"]
    persisted = json.loads((config.run_dir / "p0-p8-certification.json").read_text(encoding="utf-8"))
    assert certification["rollout_provenance"] == "legacy_p0p8_v1"
    assert "rollout_schema_version" not in certification
    assert persisted == certification


def test_overlay_base_only_timeout_is_preserved_as_partial(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    base_only = next(row for row in rows if row.get("overlay_level") == "base_only_due_to_visual_timeout")
    enriched = next(row for row in rows if row.get("overlay_level") == "full_B_enriched")
    assert base_only["quality_status"] == "partial"
    assert enriched["quality_status"] == "enriched"
    assert str((tmp_path / "runs").resolve()) not in json.dumps(rows)


def test_unknown_overlay_level_is_not_promoted_to_enriched(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    write_overlay(tmp_path / "runs", include_unknown=True)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    unknown = next(row for row in rows if row.get("overlay_level") == "future_overlay_level")
    assert unknown["quality_status"] == "unknown"


def test_expected_total_mismatch_blocks_certification(tmp_path: Path) -> None:
    config = build_config(tmp_path, expected_total=5)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert any("P0:converted_total_mismatch" in blocker for blocker in result["certification"]["blockers"])
    assert not (config.run_dir / "kh-multimodal-candidates.jsonl").exists()
    skipped = [phase for phase in result["ledger"]["phases"] if phase["status"] == "skipped"]
    assert {phase["phase"] for phase in skipped} == {"P1", "P2", "P3", "P4", "P5", "P6", "P7"}


def test_missing_input_file_writes_blocked_certification(tmp_path: Path) -> None:
    config = subject.HarnessConfig(
        run_id="missing-input",
        artifact_root=tmp_path / "artifacts",
        full_run=tmp_path / "missing-full",
        pending_run=tmp_path / "missing-pending",
        retry_run=tmp_path / "missing-retry",
        overlay_run=tmp_path / "missing-overlay",
        expected_total=1,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert any("P0:FileNotFoundError" in blocker for blocker in result["certification"]["blockers"])
    assert (config.run_dir / "p0-p8-certification.json").exists()
    assert (config.run_dir / "phase-ledger.json").exists()
    assert str(tmp_path.resolve()) not in (config.run_dir / "p0-p8-certification.json").read_text(encoding="utf-8")


def test_non_qwen_provider_blocks_before_downstream(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    bad_config = subject.HarnessConfig(**{**config.__dict__, "visual_provider": "gemini"})

    result = subject.run_all(bad_config)

    assert result["certification"]["ok"] is False
    assert any("P1:visual_provider_not_qwen:gemini" in blocker for blocker in result["certification"]["blockers"])
    assert (bad_config.run_dir / "p1-package-contract.json").exists()
    assert not (bad_config.run_dir / "kh-multimodal-candidates.jsonl").exists()


def test_missing_success_hash_blocks_certification(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    full = write_docling_run(
        runs,
        "full",
        [{"source_relative_path": "cinematography/book-a.pdf"}],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    config = subject.HarnessConfig(
        run_id="missing-hash",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=1,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert any("P0:missing_success_hashes:1" in blocker for blocker in result["certification"]["blockers"])


def test_malformed_success_source_identity_blocks_certification(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    full = write_docling_run(
        runs,
        "full",
        [
            {
                "source_relative_path": "",
                "source_sha256": "not-a-sha",
            }
        ],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    config = subject.HarnessConfig(
        run_id="malformed-source",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=1,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert any("P0:malformed_success_source_identity:1" in blocker for blocker in result["certification"]["blockers"])
    assert not (config.run_dir / "kh-multimodal-candidates.jsonl").exists()


def test_duplicate_success_hash_blocks_certification(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    duplicate_hash = "a" * 64
    full = write_docling_run(
        runs,
        "full",
        [
            {"source_relative_path": "cinematography/book-a.pdf", "source_sha256": duplicate_hash},
            {"source_relative_path": "cinematography/book-b.pdf", "source_sha256": duplicate_hash},
        ],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    config = subject.HarnessConfig(
        run_id="duplicate-hash",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=2,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert any("P0:duplicate_success_hashes:1" in blocker for blocker in result["certification"]["blockers"])


@pytest.mark.parametrize(
    ("status", "quality_status", "kh_status", "has_lightrag"),
    [
        ("converted", "usable", "candidate", True),
        ("validation_warning", "needs_review", "candidate", True),
        ("needs_review", "needs_review", "candidate", True),
        ("failed", "blocked", "blocked", False),
        ("weird", "unknown", "blocked", False),
    ],
)
def test_normalized_status_mapping(tmp_path: Path, status: str, quality_status: str, kh_status: str, has_lightrag: bool) -> None:
    row = {
        "source_relative_path": f"cinematography/book-{status}.pdf",
        "source_sha256": "a" * 64,
        "status": status,
    }
    record = subject._normalized_docling_record("run", row)
    assert record["quality_status"] == quality_status

    config = subject.HarnessConfig(run_id=f"status-{status}", artifact_root=tmp_path / "artifacts")
    kh_candidates, _ = subject.build_kh_multimodal_candidates(config, [record])
    assert kh_candidates[0]["status"] == kh_status

    lightrag_candidates, _ = subject.build_lightrag_graph_candidates(config, [record])
    assert bool(lightrag_candidates) is has_lightrag


def test_public_artifacts_redact_sensitive_keys_and_leak_samples(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    fake_openai_key = "sk-" + "test-secret"
    fake_project_key = "sk-proj-" + "123456789"
    fake_bearer = "Bearer " + "abc.def.ghi"
    full = write_docling_run(
        runs,
        "full",
        [
            {
                "source_relative_path": "cinematography/book-a.pdf",
                "source_sha256": "a" * 64,
                "api_key": fake_openai_key,
                "operator_note": f"{fake_bearer} {fake_project_key} {tmp_path.resolve()}/private-file",
                f"{tmp_path.resolve()}/private/key": "path-key",
                fake_bearer: "bearer-key",
            }
        ],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    config = subject.HarnessConfig(
        run_id="redaction",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=1,
    )

    subject.run_all(config)

    proof_text = (config.run_dir / "p0-docling-proof.json").read_text(encoding="utf-8")
    assert fake_openai_key not in proof_text
    assert fake_project_key not in proof_text
    assert "abc.def.ghi" not in proof_text
    assert str(tmp_path.resolve()) not in proof_text
    proof = json.loads(proof_text)
    row = proof["runs"][0]["rows"][0]
    assert row["api_key"] == "<redacted:secret>"
    assert all(str(tmp_path.resolve()) not in key for key in row)
    assert all("Bearer" not in key for key in row)
    fake_leak_key = "sk-" + "test"
    leak_samples = subject.find_public_leaks({"note": f"api_key={fake_leak_key} {fake_bearer} {tmp_path.resolve()}/private"})
    assert leak_samples
    assert fake_leak_key not in json.dumps(leak_samples)
    assert "abc.def.ghi" not in json.dumps(leak_samples)
    assert str(tmp_path.resolve()) not in json.dumps(leak_samples)


def test_certify_run_blocks_missing_inputs_and_public_leaks(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    phase = subject.PhaseResult(phase="P0", name="fixture", status="complete")

    certification, result_phase = subject.certify_run(
        config,
        [phase],
        [],
        [{"package_key": "pkg", "local_path": str(tmp_path.resolve())}],
        [],
    )

    assert certification["ok"] is False
    assert "missing_normalized_docling_records" in certification["blockers"]
    assert "missing_cag_candidates" in certification["blockers"]
    assert "public_leak_detected" in certification["blockers"]
    assert result_phase.status == "blocked"


def test_kh_candidates_use_qwen_primary_and_do_not_mutate(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "kh-multimodal-candidates.jsonl")
    assert rows
    assert {row["visual_analysis"]["provider"] for row in rows} == {"qwen"}
    assert {row["visual_analysis"]["fallback_provider"] for row in rows} == {"gemini"}
    assert {row["visual_analysis"]["qwen_vision_model"] for row in rows} == {"qwen-3.7-max"}
    assert {row["visual_analysis"]["endpoint_region"] for row in rows} == {"cn-beijing"}
    assert all(row["mutation_performed"] is False for row in rows)
    assert "workspace.cn-beijing" not in json.dumps(rows)


def test_output_file_layers_are_included_as_kh_candidates(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    subject.run_all(config)

    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    kh_rows = read_jsonl(config.run_dir / "kh-multimodal-candidates.jsonl")
    assert any(row["artifact_layer"] == "docling_output_file" for row in normalized)
    assert any(row["artifact_layer"] == "docling_output_file" for row in kh_rows)
    assert all("artifact_sha256" in row for row in normalized if row["artifact_layer"] == "docling_output_file")


def test_heavy_duplicate_renderings_are_not_hashed_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = tmp_path / "runs"
    full = write_docling_run(
        runs,
        "full",
        [
            {
                "source_relative_path": "cinematography/book-a.pdf",
                "source_sha256": "a" * 64,
                "output_files": {
                    "book.md": "# ok\n",
                    "book.html": "<html>heavy</html>",
                    "book.json": "{}",
                    "book.yaml": "title: heavy\n",
                },
            }
        ],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    original_sha256_file = subject.sha256_file

    def guarded_sha256_file(path: Path) -> str:
        if "outputs" in path.parts and path.suffix.lower() in {".html", ".json", ".yaml", ".yml"}:
            raise AssertionError(f"heavy file was hashed: {path}")
        return original_sha256_file(path)

    monkeypatch.setattr(subject, "sha256_file", guarded_sha256_file)
    config = subject.HarnessConfig(
        run_id="heavy-skip",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=1,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is True
    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    skipped = [row for row in normalized if row.get("skip_reason") == "heavy_duplicate_rendering_not_hashed"]
    assert {row["output_file_kind"] for row in skipped} == {"html", "structured_json", "structured_yaml"}
    assert all(row["artifact_sha256"] == "" for row in skipped)


def test_output_relative_path_cannot_escape_docling_run(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    full = write_docling_run(
        runs,
        "full",
        [
            {
                "source_relative_path": "cinematography/book-a.pdf",
                "source_sha256": "a" * 64,
                "output_relative_path": "../outside",
            }
        ],
    )
    pending = write_docling_run(runs, "pending", [])
    retry = write_docling_run(runs, "retry", [])
    overlay = write_overlay(runs)
    config = subject.HarnessConfig(
        run_id="path-traversal",
        artifact_root=tmp_path / "artifacts",
        full_run=full,
        pending_run=pending,
        retry_run=retry,
        overlay_run=overlay,
        expected_total=1,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    normalized = read_jsonl(config.run_dir / "docling-normalized-output.jsonl")
    blocked = next(row for row in normalized if row.get("blocked_reason") == "output_dir_outside_docling_run")
    assert blocked["quality_status"] == "blocked"
    assert str(tmp_path.resolve()) not in json.dumps(normalized)


def test_crosswalk_keeps_duplicate_labels_distinct_by_hash(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "package-crosswalk.jsonl")
    package_keys = {row["package_key"] for row in rows}
    assert "a" * 64 in package_keys
    assert "b" * 64 in package_keys
    assert len(package_keys) == len(rows)
    assert any(row["cag_pack_id"] for row in rows)


def test_cag_links_every_crosswalk_row_in_large_topic(tmp_path: Path) -> None:
    config = subject.HarnessConfig(run_id="large-topic", artifact_root=tmp_path / "artifacts")
    crosswalk = [
        {
            "schema_version": subject.CROSSWALK_SCHEMA_VERSION,
            "package_key": f"pkg-{index}",
            "public_label": "shared-topic",
            "layer": "docling_document",
            "source_sha256": f"{index:064x}",
            "kh_candidate_id": f"kh-{index}",
            "graph_document_id": f"graph-{index}",
            "cag_pack_id": "",
            "status": "linked",
            "provenance_hash": f"hash-{index}",
        }
        for index in range(60)
    ]

    cag, linked, phase = subject.build_cag_pack_candidates(config, crosswalk)

    assert phase.status == "complete"
    assert len(cag) == 1
    assert len(cag[0]["evidence_package_keys"]) == 60
    assert all(row["cag_pack_id"] == cag[0]["cag_pack_id"] for row in linked)


def test_cag_candidates_reference_packages_not_raw_text(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "cag-pack-candidates.jsonl")
    assert rows
    assert all(row["raw_source_text_included"] is False for row in rows)
    assert all(row["evidence_package_keys"] for row in rows)
    crosswalk = read_jsonl(config.run_dir / "package-crosswalk.jsonl")
    crosswalk_by_key = {row["package_key"]: row for row in crosswalk}
    for cag in rows:
        for package_key in cag["evidence_package_keys"]:
            assert crosswalk_by_key[package_key]["cag_pack_id"] == cag["cag_pack_id"]


def test_apply_mode_fails_closed(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    apply_config = subject.HarnessConfig(**{**config.__dict__, "apply": True})

    try:
        subject.run_all(apply_config)
    except ValueError as exc:
        assert str(exc) == "apply_mode_not_implemented_for_post_docling_harness"
    else:
        raise AssertionError("expected apply mode to fail closed")


def test_cli_run_all_returns_zero_for_certified_fixture(tmp_path: Path, capsys) -> None:
    config = build_config(tmp_path)

    rc = subject.main(
        [
            "--run-id",
            config.run_id,
            "--artifact-root",
            str(config.artifact_root),
            "--full-run",
            str(config.full_run),
            "--pending-run",
            str(config.pending_run),
            "--retry-run",
            str(config.retry_run),
            "--overlay-run",
            str(config.overlay_run),
            "--expected-total",
            "4",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out
