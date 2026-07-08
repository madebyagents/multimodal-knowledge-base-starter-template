from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import docling_black_label_package as subject


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_source_run(tmp_path: Path, *, protected_text: bool = False, missing_parent_image: bool = False) -> tuple[Path, Path]:
    run_dir = tmp_path / "p0p8" / "certified-run"
    run_dir.mkdir(parents=True)
    markdown = tmp_path / "outputs" / "same-label.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text(
        "# Montage Principles\n\n"
        + ("This file contains a full chapter copied transcript.\n" if protected_text else "Collision, rhythm, and continuity notes.\n"),
        encoding="utf-8",
    )
    source_a = "a" * 64
    source_b = "b" * 64
    image_hash = "c" * 64
    table_hash = "d" * 64
    normalized = [
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "doc-a",
            "package_key": source_a,
            "public_label": "same-label",
            "artifact_layer": "docling_document",
            "status": "converted",
            "overlay_level": "none",
            "source_pdf_id": "same-label",
            "source_relative_path": "editing/same-label.pdf",
            "source_sha256": source_a,
            "docling_run_id": "fixture",
            "topic_folder": "editing",
            "quality_status": "usable",
            "provenance_hash": "prov-a",
        },
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "doc-b",
            "package_key": source_b,
            "public_label": "same-label",
            "artifact_layer": "docling_document",
            "status": "converted",
            "overlay_level": "none",
            "source_pdf_id": "same-label",
            "source_relative_path": "cinematography/same-label.pdf",
            "source_sha256": source_b,
            "docling_run_id": "fixture",
            "topic_folder": "cinematography",
            "quality_status": "usable",
            "provenance_hash": "prov-b",
        },
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "file-md",
            "package_key": f"{source_a}:file:md",
            "public_label": "same-label:markdown",
            "artifact_layer": "docling_output_file",
            "status": "available",
            "overlay_level": "none",
            "source_pdf_id": "same-label",
            "source_relative_path": "editing/same-label.pdf",
            "source_sha256": source_a,
            "output_file_kind": "markdown",
            "output_relative_path": str(markdown),
            "artifact_sha256": "e" * 64,
            "quality_status": "usable",
            "provenance_hash": "prov-md",
        },
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "image-a",
            "package_key": f"{source_a}:file:image",
            "public_label": "same-label:image",
            "artifact_layer": "docling_extracted_image",
            "status": "available",
            "overlay_level": "none",
            "source_pdf_id": "same-label",
            "source_relative_path": "editing/same-label.pdf",
            "source_sha256": "" if missing_parent_image else source_a,
            "output_file_kind": "image",
            "output_relative_path": "logs/docling-runs/fixture/image.png",
            "artifact_sha256": image_hash,
            "quality_status": "usable",
            "provenance_hash": "prov-image",
        },
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "table-a",
            "package_key": f"{source_a}:file:table",
            "public_label": "same-label:table",
            "artifact_layer": "docling_table",
            "status": "available",
            "overlay_level": "none",
            "source_pdf_id": "same-label",
            "source_relative_path": "editing/same-label.pdf",
            "source_sha256": source_a,
            "output_file_kind": "table",
            "artifact_sha256": table_hash,
            "quality_status": "usable",
            "provenance_hash": "prov-table",
        },
        {
            "schema_version": "docling_normalized_output.v1",
            "record_id": "overlay-a",
            "package_key": "overlay:manual:0007",
            "public_label": "manual:page-0007",
            "artifact_layer": "docling_overlay_page",
            "status": "full_B_enriched",
            "overlay_level": "full_B_enriched",
            "source_pdf_id": "manual",
            "source_relative_path": "",
            "source_sha256": "",
            "page": 7,
            "quality_status": "enriched",
            "provenance_hash": "prov-overlay",
        },
    ]
    crosswalk = [
        {
            "schema_version": "package_crosswalk.v1",
            "package_key": row["package_key"],
            "public_label": row["public_label"],
            "layer": row["artifact_layer"],
            "source_sha256": row.get("source_sha256", ""),
            "kh_candidate_id": f"kh-{row['record_id']}",
            "graph_document_id": f"graph-{row['record_id']}" if row["artifact_layer"] == "docling_document" else "",
            "cag_pack_id": f"cag-{row['record_id']}",
            "status": "linked",
            "provenance_hash": f"x-{row['record_id']}",
        }
        for row in normalized
    ]
    cag = [
        {
            "schema_version": "cag_pack_candidate.v1",
            "cag_pack_id": "cag-fixture",
            "topic": "editing",
            "status": "available",
            "evidence_package_keys": [row["package_key"] for row in normalized],
            "raw_source_text_included": False,
            "crosswalk_hash": "hash",
        }
    ]
    cert = {
        "schema_version": "p0_p8_certification.v1",
        "run_id": "certified-run",
        "ok": True,
        "dry_run": True,
        "mutation_performed": False,
        "counts": {"normalized_records": len(normalized), "crosswalk_rows": len(crosswalk), "cag_candidates": 1, "leaks": 0},
        "blockers": [],
    }
    (run_dir / "p0-p8-certification.json").write_text(json.dumps(cert), encoding="utf-8")
    write_jsonl(run_dir / "docling-normalized-output.jsonl", normalized)
    write_jsonl(run_dir / "package-crosswalk.jsonl", crosswalk)
    write_jsonl(run_dir / "cag-pack-candidates.jsonl", cag)
    return run_dir, markdown


def build_config(tmp_path: Path, source_run: Path) -> subject.BlackLabelConfig:
    return subject.BlackLabelConfig(
        run_id="black-label-fixture",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
        qwen_base_url="https://workspace.cn-beijing.aliyuncs.com/compatible-mode/v1",
    )


def test_run_all_certifies_fixture_and_writes_black_label_artifacts(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is True
    assert result["certification"]["mutation_performed"] is False
    expected = {
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
    registry = read_jsonl(config.run_dir / "black-label-asset-registry.jsonl")
    assert len([row for row in registry if row["artifact_kind"] == "pdf"]) == 2
    assert len({row["pdf_package_id"] for row in registry if row["artifact_kind"] == "pdf"}) == 2
    assert len([row for row in registry if row["artifact_kind"] == "image"]) == 1
    assert all("image_package_id" in row for row in registry if row["artifact_kind"] == "image")


def test_cards_cover_all_black_label_roles_and_do_not_embed_raw_text(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)

    subject.run_all(config)

    cards = read_jsonl(config.run_dir / "black-label-card-manifest.jsonl")
    assert subject.CARD_ROLES <= {card["card_role"] for card in cards}
    assert all(card["raw_source_text_included"] is False for card in cards)
    assert all(card["package_ids"] for card in cards)
    assert all(card["estimated_chars"] <= config.max_card_chars for card in cards)


def test_qwen_visual_queue_is_dry_run_and_redacts_provider_details(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "visual-enrichment-queue.jsonl")
    assert rows
    assert {row["provider"] for row in rows} == {"qwen"}
    assert {row["fallback_provider"] for row in rows} == {"gemini"}
    assert {row["model"] for row in rows} == {"qwen-3.7-max"}
    assert all(row["provider_call_performed"] is False for row in rows)
    assert all(row["mutation_performed"] is False for row in rows)
    assert "workspace.cn-beijing" not in json.dumps(rows)


def test_protected_text_blocks_card_and_lightrag_apply_row(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, protected_text=True)
    config = build_config(tmp_path, source_run)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is True
    assert result["certification"]["counts"]["rights_blocked_cards"] == 1
    cards = read_jsonl(config.run_dir / "black-label-card-manifest.jsonl")
    blocked_cards = [card for card in cards if card["card_role"] == "concept_card"]
    assert blocked_cards
    assert blocked_cards[0]["rights_status"] == "blocked"
    lightrag_rows = read_jsonl(config.run_dir / "lightrag-card-apply-plan.jsonl")
    blocked = [row for row in lightrag_rows if row["card_id"] == blocked_cards[0]["card_id"]]
    assert blocked[0]["apply_status"] == "blocked"
    assert blocked[0]["blocked_reason"] == "rights_status_not_clear"


def test_missing_parent_image_is_registered_as_blocked_but_still_linkable(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, missing_parent_image=True)
    config = build_config(tmp_path, source_run)

    subject.run_all(config)

    registry = read_jsonl(config.run_dir / "black-label-asset-registry.jsonl")
    image = next(row for row in registry if row["artifact_kind"] == "image")
    assert image["image_package_id"]
    assert image["status"] == "blocked"


def test_cag_manifest_references_cards_graphs_and_visuals_without_raw_text(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)

    subject.run_all(config)

    rows = read_jsonl(config.run_dir / "cag-pack-manifest.jsonl")
    assert rows
    assert any(row["status"] == "available" for row in rows)
    assert all(row["raw_source_text_included"] is False for row in rows)
    assert all(row["evidence_card_ids"] for row in rows)
    assert any(row["graph_refs"] for row in rows)


def test_public_outputs_do_not_leak_absolute_paths_or_secrets(tmp_path: Path) -> None:
    source_run, markdown = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    markdown.write_text(f"# Secret\napi_key=sk-testsecret {tmp_path.resolve()}/private\n", encoding="utf-8")

    subject.run_all(config)

    payload = {
        "registry": read_jsonl(config.run_dir / "black-label-asset-registry.jsonl"),
        "cards": read_jsonl(config.run_dir / "black-label-card-manifest.jsonl"),
        "cert": json.loads((config.run_dir / "black-label-certification.json").read_text(encoding="utf-8")),
    }
    serialized = json.dumps(payload)
    assert str(tmp_path.resolve()) not in serialized
    assert "sk-testsecret" not in serialized
    assert not subject.find_public_leaks(payload)


def test_apply_mode_fails_closed(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = subject.BlackLabelConfig(run_id="apply", artifact_root=tmp_path / "artifacts", source_run=source_run, apply=True)

    with pytest.raises(ValueError, match="apply_mode_not_implemented_for_black_label_docling"):
        subject.run_all(config)


def test_cli_run_all_returns_zero_for_certified_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source_run, _ = make_source_run(tmp_path)

    rc = subject.main(
        [
            "--run-id",
            "cli-fixture",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--source-run",
            str(source_run),
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out


class FakeLightRAGClient:
    def __init__(
        self,
        *,
        failed: int = 0,
        recover_query: bool = True,
        existing_sources: set[str] | None = None,
        index_error: bool = False,
        insert_failure_call: int | None = None,
    ) -> None:
        self.failed = failed
        self.recover_query = recover_query
        self.existing_sources = existing_sources or set()
        self.index_error = index_error
        self.insert_failure_call = insert_failure_call
        self.insert_calls = 0
        self.inserted_texts: list[str] = []
        self.inserted_sources: list[str] = []

    def health(self) -> dict:
        return {"status": "healthy"}

    def status_counts(self) -> dict:
        total = 100 + len(self.inserted_texts)
        return {"status_counts": {"all": total, "processed": total - self.failed, "failed": self.failed, "pending": 0, "preprocessed": 0, "processing": 0}}

    def pipeline_status(self) -> dict:
        return {"busy": False, "request_pending": False}

    def insert_texts(self, texts: list[str], file_sources: list[str]) -> dict:
        self.insert_calls += 1
        if self.insert_failure_call == self.insert_calls:
            return {"status": "failure", "message": "simulated failure"}
        self.inserted_texts.extend(texts)
        self.inserted_sources.extend(file_sources)
        return {"status": "success", "message": "ok"}

    def paginated_documents(self, *, page: int, page_size: int = 200, status_filter: str | None = None) -> dict:
        if self.index_error:
            raise RuntimeError("index unavailable")
        all_documents = [{"id": f"existing-{index}", "file_path": source} for index, source in enumerate(sorted(self.existing_sources), 1)]
        start = max(0, page - 1) * page_size
        end = start + page_size
        documents = all_documents[start:end]
        return {"documents": documents, "pagination": {"has_next": end < len(all_documents)}}

    def wait_until_settled(self, *, interval_s: float, timeout_s: float, min_total_count: int | None = None) -> dict:
        return {"settled": True, "busy": False, "request_pending": False, "total_count": min_total_count or 101}

    def query(self, query: str, **kwargs: object) -> dict:
        if not self.recover_query:
            return {"response": "no relevant context", "references": []}
        retrievable_sources = self.inserted_sources + sorted(self.existing_sources)
        source = next((item for item in retrievable_sources if item.removesuffix(".md").split("/")[-1] in query), retrievable_sources[0])
        if source in self.inserted_sources:
            text = self.inserted_texts[self.inserted_sources.index(source)]
        else:
            text = f"Existing recovered source {source}"
        marker = source.removesuffix(".md").split("/")[-1]
        return {
            "response": f"Recovered {marker}",
            "references": [{"file_path": source, "content": [text]}],
        }


def test_lightrag_sample_apply_uses_one_curated_card_and_writes_ledger(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    apply_config = subject.BlackLabelConfig(
        run_id="sample-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=black_label_run,
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(apply_config, client=fake)

    assert ledger["ok"] is True
    assert ledger["mutation_performed"] is True
    assert ledger["blockers"] == []
    assert len(fake.inserted_texts) == 1
    assert "# Black Label Docling Card" in fake.inserted_texts[0]
    assert "Package refs:" in fake.inserted_texts[0]
    assert "Collision, rhythm, and continuity notes" not in fake.inserted_texts[0]
    assert fake.inserted_sources[0].startswith("black-label-docling/one_document_sample/card_source_card_")
    written = json.loads((black_label_run / subject.LIGHTRAG_SAMPLE_LEDGER).read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert written["stage"] == "one_document_sample"


def test_lightrag_topic_stage_recovery_is_bounded_and_verifies_existing_sources(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="five-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="five_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )
    cards = read_jsonl(black_label_run / "black-label-card-manifest.jsonl")
    plan_rows = read_jsonl(black_label_run / "lightrag-card-apply-plan.jsonl")
    selected = subject._select_lightrag_stage_candidates(
        "topic_cluster_sample",
        plan_rows,
        {card["card_id"]: card for card in cards},
        exclude_card_ids=subject._lightrag_prior_stage_card_ids(black_label_run, "topic_cluster_sample"),
    )
    existing_sources = {str(candidate["file_source"]) for candidate in selected[:3]}
    fake = FakeLightRAGClient(existing_sources=existing_sources)

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="topic-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="topic_cluster_sample",
            lightrag_batch_max_cards=2,
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=fake,
    )

    assert ledger["ok"] is True
    assert ledger["selected_count"] <= subject.LIGHTRAG_STAGE_LIMITS["topic_cluster_sample"]
    assert ledger["sent_count"] == max(0, ledger["selected_count"] - len(existing_sources))
    assert len(ledger["query_recovery"]) <= subject.LIGHTRAG_QUERY_RECOVERY_LIMITS["topic_cluster_sample"]
    assert any(row["source_already_present"] for row in ledger["query_recovery"])
    assert all("response" not in row for row in ledger["query_recovery"])
    assert all("reference_count" in row for row in ledger["query_recovery"])
    assert ledger["blockers"] == []


def test_full_corpus_stage_blocks_without_refreshed_certification_gate(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    for stage in ("one_document_sample", "five_document_sample", "topic_cluster_sample"):
        subject.apply_lightrag_stage(
            subject.BlackLabelConfig(
                run_id=f"{stage}-apply",
                artifact_root=tmp_path / "artifacts",
                black_label_run=black_label_run,
                lightrag_stage=stage,
                lightrag_poll_interval_s=0.0,
                lightrag_poll_timeout_s=1.0,
            ),
            client=FakeLightRAGClient(),
        )

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="full-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="full_corpus_after_certification",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert "full_corpus_apply_not_certified" in ledger["blockers"]


def test_full_corpus_stage_blocks_when_existing_document_index_fails_after_refresh(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    for stage in ("one_document_sample", "five_document_sample", "topic_cluster_sample"):
        subject.apply_lightrag_stage(
            subject.BlackLabelConfig(
                run_id=f"{stage}-apply",
                artifact_root=tmp_path / "artifacts",
                black_label_run=black_label_run,
                lightrag_stage=stage,
                lightrag_poll_interval_s=0.0,
                lightrag_poll_timeout_s=1.0,
            ),
            client=FakeLightRAGClient(),
        )
    subject.refresh_black_label_certification(
        subject.BlackLabelConfig(
            run_id="refresh",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
        )
    )
    fake = FakeLightRAGClient(index_error=True)

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="full-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="full_corpus_after_certification",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert fake.inserted_texts == []
    assert ledger["blockers"][0].startswith("lightrag_document_index_error:")


def test_stage_ledger_preserves_partial_mutation_when_later_batch_fails(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )
    fake = FakeLightRAGClient(insert_failure_call=2)

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="five-apply",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="five_document_sample",
            lightrag_batch_max_cards=1,
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is True
    assert ledger["sent_count"] == 1
    assert fake.inserted_texts
    written = json.loads((black_label_run / subject.LIGHTRAG_STAGE_LEDGER_FILES["five_document_sample"]).read_text(encoding="utf-8"))
    assert written["mutation_performed"] is True
    assert written["sent_count"] == 1


def test_lightrag_sample_apply_blocks_when_preflight_has_failed_docs(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    apply_config = subject.BlackLabelConfig(run_id="sample-apply", artifact_root=tmp_path / "artifacts", source_run=config.run_dir)
    fake = FakeLightRAGClient(failed=1)

    ledger = subject.apply_lightrag_sample(apply_config, client=fake)

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert "failed_documents_present:1" in ledger["blockers"]
    assert fake.inserted_texts == []


def test_lightrag_sample_apply_blocks_when_query_does_not_recover_card(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    apply_config = subject.BlackLabelConfig(run_id="sample-apply", artifact_root=tmp_path / "artifacts", source_run=config.run_dir)
    fake = FakeLightRAGClient(recover_query=False)

    ledger = subject.apply_lightrag_sample(apply_config, client=fake)

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is True
    assert ledger["blockers"][0].startswith("lightrag_query_recovery_failed:")


def test_lightrag_five_stage_blocks_without_first_card_prerequisite(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    apply_config = subject.BlackLabelConfig(
        run_id="five-apply",
        artifact_root=tmp_path / "artifacts",
        black_label_run=config.run_dir,
        lightrag_stage="five_document_sample",
    )
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(apply_config, client=fake)

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert ledger["blockers"] == ["missing_prerequisite_ledger:one_document_sample"]
    assert fake.inserted_texts == []


def test_lightrag_five_stage_applies_bounded_cards_after_first_card_prerequisite(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    first = subject.BlackLabelConfig(
        run_id="first-apply",
        artifact_root=tmp_path / "artifacts",
        black_label_run=black_label_run,
        lightrag_stage="one_document_sample",
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    subject.apply_lightrag_stage(first, client=FakeLightRAGClient())
    cards = read_jsonl(black_label_run / "black-label-card-manifest.jsonl")
    plan_rows = read_jsonl(black_label_run / "lightrag-card-apply-plan.jsonl")
    selected = subject._select_lightrag_stage_candidates(
        "five_document_sample",
        plan_rows,
        {card["card_id"]: card for card in cards},
        exclude_card_ids=subject._lightrag_prior_stage_card_ids(black_label_run, "five_document_sample"),
    )
    duplicate_source = str(selected[0]["file_source"])
    five = subject.BlackLabelConfig(
        run_id="five-apply",
        artifact_root=tmp_path / "artifacts",
        black_label_run=black_label_run,
        lightrag_stage="five_document_sample",
        lightrag_batch_max_cards=2,
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    fake = FakeLightRAGClient(existing_sources={duplicate_source})

    ledger = subject.apply_lightrag_stage(five, client=fake)

    assert ledger["ok"] is True
    assert ledger["stage"] == "five_document_sample"
    assert ledger["selected_count"] == 5
    assert ledger["sent_count"] == 4
    assert len(ledger["batch_manifest"]) >= 3
    assert len(fake.inserted_texts) == 4
    assert ledger["skipped_sources"] == [duplicate_source]
    written = json.loads((black_label_run / subject.LIGHTRAG_STAGE_LEDGER_FILES["five_document_sample"]).read_text(encoding="utf-8"))
    assert written["ok"] is True


def test_refresh_certification_reads_lightrag_stage_ledgers(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    apply_config = subject.BlackLabelConfig(
        run_id="first-apply",
        artifact_root=tmp_path / "artifacts",
        black_label_run=config.run_dir,
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    subject.apply_lightrag_stage(apply_config, client=FakeLightRAGClient())

    refreshed = subject.refresh_black_label_certification(
        subject.BlackLabelConfig(run_id="refresh", artifact_root=tmp_path / "artifacts", source_run=source_run, black_label_run=config.run_dir)
    )

    cert = refreshed["certification"]
    assert cert["rollout_gates"]["gate_1_lightrag_one_card_sample"] == "pass"
    assert cert["rollout_gates"]["gate_2_lightrag_five_source_sample"] == "pending_live_operator_gate"
    assert cert["lightrag_stage_ledgers"]["one_document_sample"]["ok"] is True


def test_cli_staged_apply_requires_black_label_run_not_source_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = subject.main(["apply-lightrag-stage", "--source-run", str(tmp_path / "black-label-run")])

    assert rc == 2
    out = capsys.readouterr().out
    assert "use_black_label_run_for_staged_apply" in out

    rc = subject.main(["apply-lightrag-stage"])

    assert rc == 2
    out = capsys.readouterr().out
    assert "use_black_label_run_for_staged_apply" in out
