from __future__ import annotations

import hashlib
import json
import shutil
import threading
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


def result_hash(path: Path) -> str:
    payload = read_jsonl(path) if path.suffix == ".jsonl" else json.loads(path.read_text(encoding="utf-8"))
    return subject.stable_hash(payload)


def legacy_source_certification_hash(source_run: Path) -> str:
    certification = json.loads((source_run / "p0-p8-certification.json").read_text(encoding="utf-8"))
    if certification.get("rollout_schema_version") or certification.get("rollout_provenance") not in {
        None,
        "",
        subject.LEGACY_ROLLOUT_PROVENANCE,
    }:
        return ""
    return subject.stable_hash(certification)


def legacy_source_bundle_hash(source_run: Path) -> str:
    if not legacy_source_certification_hash(source_run):
        return ""
    source = subject.load_source_bundle(
        subject.BlackLabelConfig(run_id="binding-only", source_run=source_run)
    )
    return str(source.binding["source_bundle_hash"])


def make_source_run(
    tmp_path: Path,
    *,
    protected_text: bool = False,
    missing_parent_image: bool = False,
    governed_p1_authorized: bool | None = True,
    legacy_provenance_marker: bool = True,
) -> tuple[Path, Path]:
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
            "artifact_sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
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
    if governed_p1_authorized is None and legacy_provenance_marker:
        cert["rollout_provenance"] = subject.LEGACY_ROLLOUT_PROVENANCE
    if governed_p1_authorized is not None:
        cert["rollout_schema_version"] = subject.GOVERNED_ROLLOUT_SCHEMA_VERSION
        cert["rollout_provenance"] = subject.GOVERNED_ROLLOUT_PROVENANCE
        cert["governed_p1_authorization"] = {
            "authorized": governed_p1_authorized,
            "separately_reviewed": governed_p1_authorized,
            "controller_ready": governed_p1_authorized,
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
        legacy_source_certification_hash=legacy_source_certification_hash(source_run),
        legacy_source_bundle_hash=legacy_source_bundle_hash(source_run),
    )


def extend_source_run_for_five_source_gate(
    source_run: Path,
    *,
    total_sources: int = 6,
    include_hashless_records: bool = True,
) -> None:
    normalized_path = source_run / "docling-normalized-output.jsonl"
    crosswalk_path = source_run / "package-crosswalk.jsonl"
    certification_path = source_run / "p0-p8-certification.json"
    normalized = read_jsonl(normalized_path)
    crosswalk = read_jsonl(crosswalk_path)
    if not include_hashless_records:
        normalized = [row for row in normalized if row.get("source_sha256")]
        retained_package_keys = {str(row["package_key"]) for row in normalized}
        crosswalk = [row for row in crosswalk if str(row.get("package_key") or "") in retained_package_keys]
    for index in range(3, total_sources + 1):
        source_hash = f"{index:064x}"
        record_id = f"doc-{index}"
        normalized.append(
            {
                "schema_version": "docling_normalized_output.v1",
                "record_id": record_id,
                "package_key": source_hash,
                "public_label": f"fixture-source-{index}",
                "artifact_layer": "docling_document",
                "status": "converted",
                "overlay_level": "none",
                "source_pdf_id": f"fixture-source-{index}",
                "source_relative_path": f"editing/fixture-source-{index}.pdf",
                "source_sha256": source_hash,
                "docling_run_id": "fixture",
                "topic_folder": "editing",
                "quality_status": "usable",
                "provenance_hash": f"prov-{index}",
            }
        )
        crosswalk.append(
            {
                "schema_version": "package_crosswalk.v1",
                "package_key": source_hash,
                "public_label": f"fixture-source-{index}",
                "layer": "docling_document",
                "source_sha256": source_hash,
                "kh_candidate_id": f"kh-{record_id}",
                "graph_document_id": f"graph-{record_id}",
                "cag_pack_id": f"cag-{record_id}",
                "status": "linked",
                "provenance_hash": f"x-{record_id}",
            }
        )
    write_jsonl(normalized_path, normalized)
    write_jsonl(crosswalk_path, crosswalk)
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["counts"]["normalized_records"] = len(normalized)
    certification["counts"]["crosswalk_rows"] = len(crosswalk)
    certification_path.write_text(json.dumps(certification), encoding="utf-8")


def test_build_run_id_uses_timestamp_and_random_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = iter(("0123456789abcdef", "fedcba9876543210"))
    monkeypatch.setattr(subject.time, "strftime", lambda *_args, **_kwargs: "20260808T120000Z")
    monkeypatch.setattr(subject.secrets, "token_hex", lambda _size: next(tokens))

    first = subject.build_run_id()
    second = subject.build_run_id()

    assert first == "docling-black-label-20260808T120000Z-0123456789abcdef"
    assert second == "docling-black-label-20260808T120000Z-fedcba9876543210"
    assert first != second


def test_run_all_certifies_fixture_and_writes_black_label_artifacts(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)

    result = subject.run_all(config)

    assert result["certification"]["ok"] is True
    assert result["certification"]["mutation_performed"] is False
    assert result["certification"]["source_p0_p8_certification_hash"] == result_hash(
        source_run / "p0-p8-certification.json"
    )
    assert result["certification"]["source_rollout_schema_version"] == subject.GOVERNED_ROLLOUT_SCHEMA_VERSION
    assert result["certification"]["source_rollout_provenance"] == subject.GOVERNED_ROLLOUT_PROVENANCE
    assert result["certification"]["source_governed_p1_authorization"] == {
        "provenance_valid": True,
        "required": True,
        "authorized": True,
        "separately_reviewed": True,
        "controller_ready": True,
    }
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


def test_run_all_refuses_duplicate_run_id_without_modifying_existing_artifacts(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    before = {
        path.relative_to(config.run_dir): path.read_bytes()
        for path in config.run_dir.rglob("*")
        if path.is_file()
    }

    with pytest.raises(FileExistsError, match="black_label_run_already_exists"):
        subject.run_all(config)

    after = {
        path.relative_to(config.run_dir): path.read_bytes()
        for path in config.run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("limit_pdfs", 0, "black_label_limit_pdfs_invalid"),
        ("limit_pdfs", -1, "black_label_limit_pdfs_invalid"),
        ("max_card_chars", 0, "black_label_max_card_chars_invalid"),
        ("text_read_chars", 0, "black_label_text_read_chars_invalid"),
        ("eval_threshold", 0, "black_label_eval_threshold_invalid"),
    ],
)
def test_run_all_rejects_invalid_generation_config_before_creating_run(
    tmp_path: Path,
    field: str,
    value: int,
    blocker: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = subject.replace(build_config(tmp_path, source_run), **{field: value})

    with pytest.raises(ValueError, match=blocker):
        subject.run_all(config)

    assert not config.run_dir.exists()


def test_cli_reports_invalid_generation_config_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = subject.main(
        [
            "run-all",
            "--run-id",
            "invalid-cli-config",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--max-card-chars",
            "0",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload == {"ok": False, "blockers": ["black_label_max_card_chars_invalid"]}
    assert not (tmp_path / "artifacts" / "invalid-cli-config").exists()


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
    markdown.write_text(f"# Secret\napi_key=sk-testsecret {tmp_path.resolve()}/private\n", encoding="utf-8")
    normalized_path = source_run / "docling-normalized-output.jsonl"
    normalized = read_jsonl(normalized_path)
    next(row for row in normalized if row.get("record_id") == "file-md")["artifact_sha256"] = hashlib.sha256(
        markdown.read_bytes()
    ).hexdigest()
    write_jsonl(normalized_path, normalized)
    config = build_config(tmp_path, source_run)

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
        self.fence_requests: list[dict] = []
        self._fence_lock = threading.Lock()
        self._used_fence_tokens: set[str] = set()

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

    def mutation_fencing_capability(self) -> dict:
        return {
            "available": True,
            "service_enforced": True,
            "single_use": True,
            "binding_fields": [
                "black_label_certification_hash",
                "stage",
                "input_bindings_hash",
                "batch_id",
                "ordered_payload_hashes",
                "file_sources",
                "expires_at_epoch",
                "nonce",
            ],
        }

    def insert_texts_once(
        self,
        texts: list[str],
        file_sources: list[str],
        *,
        fence_request: dict,
    ) -> dict:
        token = str(fence_request.get("fence_token") or "")
        with self._fence_lock:
            if not token or token in self._used_fence_tokens:
                return {"status": "failure", "message": "fence_reused"}
            self._used_fence_tokens.add(token)
            self.fence_requests.append(dict(fence_request))
            response = self.insert_texts(texts, file_sources)
        if response.get("status") == "failure":
            return response
        return {
            **response,
            "fence_receipt": {
                "schema_version": subject.LIGHTRAG_FENCE_RECEIPT_SCHEMA_VERSION,
                "accepted": True,
                "single_use_enforced": True,
                "fence_token": token,
                "binding_hash": fence_request.get("binding_hash"),
            },
        }

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


def test_governed_p0_bundle_without_p1_authorization_packages_but_blocks_certification_and_apply(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=False)
    config = build_config(tmp_path, source_run)

    source = subject.load_source_bundle(config)
    result = subject.run_all(config)
    fake = FakeLightRAGClient()
    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="governed-sample-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
        ),
        client=fake,
    )

    assert source.certification["ok"] is True
    assert result["certification"]["ok"] is False
    assert "governed_p1_controller_not_authorized" in result["certification"]["blockers"]
    assert result["certification"]["source_rollout_schema_version"] == subject.GOVERNED_ROLLOUT_SCHEMA_VERSION
    assert result["certification"]["source_rollout_provenance"] == subject.GOVERNED_ROLLOUT_PROVENANCE
    assert result["certification"]["source_governed_p1_authorization"] == {
        "provenance_valid": True,
        "required": True,
        "authorized": False,
        "separately_reviewed": False,
        "controller_ready": False,
    }
    assert "governed_p1_controller_not_authorized" in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0
    assert fake.inserted_texts == []


def test_direct_governed_black_label_certification_blocks_staged_apply_without_p1_authorization(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("source_rollout_schema_version")
    certification.pop("source_rollout_provenance")
    certification.pop("source_governed_p1_authorization")
    certification["rollout_schema_version"] = subject.GOVERNED_ROLLOUT_SCHEMA_VERSION
    certification["rollout_provenance"] = subject.GOVERNED_ROLLOUT_PROVENANCE
    certification["governed_p1_authorization"] = {
        "authorized": False,
        "separately_reviewed": False,
        "controller_ready": False,
    }
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="direct-governed-sample-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
        ),
        client=fake,
    )

    assert "governed_p1_controller_not_authorized" in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_missing_governed_source_schema_does_not_downgrade_to_legacy_apply(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=False)
    source_certification_path = source_run / "p0-p8-certification.json"
    source_certification = json.loads(source_certification_path.read_text(encoding="utf-8"))
    source_certification.pop("rollout_schema_version")
    source_certification_path.write_text(json.dumps(source_certification), encoding="utf-8")
    config = build_config(tmp_path, source_run)

    result = subject.run_all(config)
    fake = FakeLightRAGClient()
    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="missing-governed-schema-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
        ),
        client=fake,
    )

    assert result["certification"]["ok"] is False
    assert result["certification"]["source_governed_p1_authorization"]["required"] is True
    assert result["certification"]["source_rollout_provenance"] == subject.GOVERNED_ROLLOUT_PROVENANCE
    assert subject.GOVERNED_P1_PROVENANCE_BLOCKER in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


@pytest.mark.parametrize(
    ("schema", "provenance"),
    [
        ("unrecognized.v2", subject.GOVERNED_ROLLOUT_PROVENANCE),
        (subject.GOVERNED_ROLLOUT_SCHEMA_VERSION, subject.LEGACY_ROLLOUT_PROVENANCE),
        ("", subject.GOVERNED_ROLLOUT_PROVENANCE),
    ],
)
def test_unknown_or_mismatched_source_provenance_blocks_true_authorization_before_apply(
    tmp_path: Path,
    schema: str,
    provenance: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    certification_path = source_run / "p0-p8-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["rollout_schema_version"] = schema
    certification["rollout_provenance"] = provenance
    certification["governed_p1_authorization"] = {
        "authorized": True,
        "separately_reviewed": True,
        "controller_ready": True,
    }
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    config = build_config(tmp_path, source_run)

    result = subject.run_all(config)
    fake = FakeLightRAGClient()
    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="unknown-provenance-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
        ),
        client=fake,
    )

    assert result["certification"]["ok"] is False
    assert result["certification"]["source_governed_p1_authorization"]["provenance_valid"] is False
    assert subject.GOVERNED_P1_PROVENANCE_BLOCKER in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


@pytest.mark.parametrize("tamper_target", ["cards", "plan"])
def test_first_lightrag_stage_blocks_post_certification_input_tamper(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    filename = "black-label-card-manifest.jsonl" if tamper_target == "cards" else "lightrag-card-apply-plan.jsonl"
    path = config.run_dir / filename
    rows = read_jsonl(path)
    rows[0]["tamper_marker"] = True
    write_jsonl(path, rows)
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-stage-tamper",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert "certified_input_bindings_mismatch" in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_legacy_binding_migration_verifies_gate_one_and_allows_gate_two_progression(tmp_path: Path) -> None:
    source_run, _ = make_source_run(
        tmp_path,
        governed_p1_authorized=None,
        legacy_provenance_marker=False,
    )
    extend_source_run_for_five_source_gate(source_run)
    config = build_config(tmp_path, source_run)
    legacy_hash = config.legacy_source_certification_hash
    legacy_bundle_hash = config.legacy_source_bundle_hash
    subject.run_all(config)
    black_label_run = config.run_dir
    gate_one = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        ),
        client=FakeLightRAGClient(),
    )
    certification_path = black_label_run / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    expected_bindings = certification.pop("certified_input_bindings")
    for legacy_missing_field in (
        "source_p0_p8_certification_hash",
        "source_rollout_schema_version",
        "source_rollout_provenance",
        "source_governed_p1_authorization",
        "source_legacy_attestation",
    ):
        certification.pop(legacy_missing_field, None)
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    gate_one_path = black_label_run / subject.LIGHTRAG_SAMPLE_LEDGER
    legacy_gate_one = json.loads(gate_one_path.read_text(encoding="utf-8"))
    legacy_gate_one.pop("input_bindings")
    for card in legacy_gate_one["selected_cards"]:
        card.pop("source_hash", None)
    gate_one_path.write_text(json.dumps(legacy_gate_one), encoding="utf-8")
    legacy_certification_bytes = certification_path.read_bytes()
    legacy_gate_one_bytes = gate_one_path.read_bytes()
    existing_sources = {str(card["file_source"]) for card in gate_one["selected_cards"]}

    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="binding-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        ),
        client=FakeLightRAGClient(existing_sources=existing_sources),
    )

    assert migration["ok"] is True
    assert migration["mutation_performed"] is False
    assert migration["migrated_stages"] == ["one_document_sample"]
    assert migration["certified_input_bindings"] == expected_bindings
    assert certification_path.read_bytes() == legacy_certification_bytes
    assert gate_one_path.read_bytes() == legacy_gate_one_bytes
    migration_sidecar = json.loads(
        (black_label_run / subject.LIGHTRAG_BINDING_MIGRATION_FILE).read_text(encoding="utf-8")
    )
    assert migration_sidecar["certified_input_bindings"] == expected_bindings
    assert migration_sidecar["mutation_replayed"] is False
    assert migration_sidecar["source_legacy_attestation"]["source_p0_p8_certification_hash"] == legacy_hash
    assert migration_sidecar["migrated_stage_ledgers"][0]["ledger_sha256"] == subject.p0p8.sha256_file(
        gate_one_path
    )
    sidecar_path = black_label_run / subject.LIGHTRAG_BINDING_MIGRATION_FILE
    sidecar_bytes = sidecar_path.read_bytes()
    retry = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="binding-migration-retry",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        ),
        client=FakeLightRAGClient(existing_sources=existing_sources),
    )
    replay_client = FakeLightRAGClient()
    replay = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply-replay",
            artifact_root=tmp_path / "artifacts",
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
        ),
        client=replay_client,
    )
    assert retry["ok"] is True
    assert sidecar_path.read_bytes() == sidecar_bytes
    assert replay["blockers"] == ["existing_stage_ledger_blocks_replay:one_document_sample"]
    assert replay_client.insert_calls == 0
    assert gate_one_path.read_bytes() == legacy_gate_one_bytes

    refreshed = subject.refresh_black_label_certification(
        subject.BlackLabelConfig(
            run_id="refresh",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        )
    )
    assert json.loads(certification_path.read_text(encoding="utf-8"))["certified_input_bindings"] == expected_bindings
    refreshed_certification = json.loads(certification_path.read_text(encoding="utf-8"))
    assert refreshed_certification["legacy_binding_migration"]["sidecar_sha256"] == subject.p0p8.sha256_file(
        sidecar_path
    )
    assert gate_one_path.read_bytes() == legacy_gate_one_bytes
    gate_two = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="five-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="five_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        ),
        client=FakeLightRAGClient(),
    )

    assert refreshed["certification"]["rollout_gates"]["gate_1_lightrag_one_card_sample"] == "pass"
    assert gate_two["ok"] is True
    assert gate_two["selected_count"] == 4
    assert gate_two["sent_count"] == 4

    second_refresh = subject.refresh_black_label_certification(
        subject.BlackLabelConfig(
            run_id="second-refresh",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        )
    )
    second_refresh_certification = json.loads(certification_path.read_text(encoding="utf-8"))
    assert second_refresh_certification["legacy_binding_migration"]["sidecar_sha256"] == subject.p0p8.sha256_file(
        sidecar_path
    )
    assert second_refresh["certification"]["rollout_gates"]["gate_2_lightrag_five_source_sample"] == "pass"
    gate_three = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="topic-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="topic_cluster_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
            legacy_source_certification_hash=legacy_hash,
            legacy_source_bundle_hash=legacy_bundle_hash,
        ),
        client=FakeLightRAGClient(),
    )
    assert gate_three["ok"] is True


@pytest.mark.parametrize(
    ("tamper_target", "expected_binding"),
    [
        ("cards", "black_label_card_manifest_hash"),
        ("plan", "lightrag_apply_plan_hash"),
    ],
)
def test_legacy_binding_migration_rejects_noncanonical_inputs(
    tmp_path: Path,
    tamper_target: str,
    expected_binding: str,
) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=None)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("certified_input_bindings")
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    artifact_path = config.run_dir / (
        "black-label-card-manifest.jsonl" if tamper_target == "cards" else "lightrag-card-apply-plan.jsonl"
    )
    rows = read_jsonl(artifact_path)
    rows[0]["tampered_after_certification"] = True
    write_jsonl(artifact_path, rows)

    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="binding-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        )
    )

    assert migration["ok"] is False
    assert f"legacy_binding_canonical_mismatch:{expected_binding}" in migration["blockers"]
    assert migration["mutation_performed"] is False
    assert "certified_input_bindings" not in json.loads(certification_path.read_text(encoding="utf-8"))
    assert not (config.run_dir / subject.LIGHTRAG_BINDING_MIGRATION_FILE).exists()


def test_legacy_binding_migration_does_not_infer_legacy_after_governed_fields_are_removed(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=True)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("certified_input_bindings")
    certification.pop("source_p0_p8_certification_hash", None)
    for key in ("source_rollout_schema_version", "source_rollout_provenance", "source_governed_p1_authorization"):
        certification.pop(key, None)
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    source_certification_path = source_run / "p0-p8-certification.json"
    source_certification = json.loads(source_certification_path.read_text(encoding="utf-8"))
    for key in ("rollout_schema_version", "rollout_provenance", "governed_p1_authorization"):
        source_certification.pop(key, None)
    source_certification_path.write_text(json.dumps(source_certification), encoding="utf-8")

    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="binding-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
        )
    )

    assert migration["ok"] is False
    assert subject.GOVERNED_P1_PROVENANCE_BLOCKER in migration["blockers"]
    assert migration["mutation_performed"] is False
    assert not (config.run_dir / subject.LIGHTRAG_BINDING_MIGRATION_FILE).exists()


def test_legacy_provenance_marker_requires_explicit_source_hash_attestation(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=None)
    config = subject.BlackLabelConfig(
        run_id="unattested-legacy",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
    )

    result = subject.run_all(config)

    assert result["certification"]["ok"] is False
    assert subject.GOVERNED_P1_AUTHORIZATION_BLOCKER in result["certification"]["blockers"]
    assert result["certification"]["source_legacy_attestation"] is None


def test_governed_source_relabelled_as_legacy_cannot_migrate_without_hash_attestation(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=False)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    source_certification_path = source_run / "p0-p8-certification.json"
    source_certification = json.loads(source_certification_path.read_text(encoding="utf-8"))
    source_certification.pop("rollout_schema_version", None)
    source_certification.pop("governed_p1_authorization", None)
    source_certification["rollout_provenance"] = subject.LEGACY_ROLLOUT_PROVENANCE
    source_certification_path.write_text(json.dumps(source_certification), encoding="utf-8")
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["ok"] = True
    certification["blockers"] = []
    certification.pop("certified_input_bindings", None)
    for key in (
        "source_p0_p8_certification_hash",
        "source_rollout_schema_version",
        "source_rollout_provenance",
        "source_governed_p1_authorization",
        "source_legacy_attestation",
    ):
        certification.pop(key, None)
    certification_path.write_text(json.dumps(certification), encoding="utf-8")

    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="downgrade-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
        )
    )

    assert migration["ok"] is False
    assert subject.GOVERNED_P1_AUTHORIZATION_BLOCKER in migration["blockers"]
    assert migration["mutation_performed"] is False
    assert not (config.run_dir / subject.LIGHTRAG_BINDING_MIGRATION_FILE).exists()


def test_governed_source_cannot_be_relabelled_as_legacy_even_with_its_exact_hash(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=False)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    source_certification_path = source_run / "p0-p8-certification.json"
    source_certification = json.loads(source_certification_path.read_text(encoding="utf-8"))
    current_source_hash = subject.stable_hash(source_certification)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["ok"] = True
    certification["blockers"] = []
    certification["source_p0_p8_certification_hash"] = current_source_hash
    certification["source_rollout_schema_version"] = ""
    certification["source_rollout_provenance"] = subject.LEGACY_ROLLOUT_PROVENANCE
    certification["source_governed_p1_authorization"] = {
        "provenance_valid": True,
        "required": True,
        "authorized": True,
        "separately_reviewed": True,
        "controller_ready": True,
    }
    certification["source_legacy_attestation"] = None
    certification["certified_input_bindings"]["source_p0_p8_certification_hash"] = current_source_hash
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="downgrade-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
            legacy_source_certification_hash=current_source_hash,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert subject.GOVERNED_P1_AUTHORIZATION_BLOCKER in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_unrelated_authorized_source_cannot_rebind_an_existing_black_label_plan(tmp_path: Path) -> None:
    source_a, _ = make_source_run(tmp_path / "source-a", governed_p1_authorized=False)
    config_a = build_config(tmp_path / "source-a", source_a)
    subject.run_all(config_a)
    source_b, _ = make_source_run(
        tmp_path / "source-b",
        protected_text=True,
        governed_p1_authorized=None,
    )
    source_b_certification = json.loads((source_b / "p0-p8-certification.json").read_text(encoding="utf-8"))
    source_b_hash = subject.stable_hash(source_b_certification)
    source_b_bundle = subject.load_source_bundle(
        subject.BlackLabelConfig(run_id="source-b-binding", source_run=source_b)
    )
    source_b_bundle_hash = str(source_b_bundle.binding["source_bundle_hash"])
    source_schema, source_provenance, source_authorization, source_attestation = (
        subject._source_rollout_authorization(
            source_b_certification,
            source_bundle_binding=source_b_bundle.binding,
            legacy_source_certification_hash=source_b_hash,
            legacy_source_bundle_hash=source_b_bundle_hash,
        )
    )
    certification_path = config_a.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["ok"] = True
    certification["blockers"] = []
    certification["source_p0_p8_certification_hash"] = source_b_hash
    certification["source_rollout_schema_version"] = source_schema
    certification["source_rollout_provenance"] = source_provenance
    certification["source_governed_p1_authorization"] = source_authorization
    certification["source_legacy_attestation"] = source_attestation
    certification["source_bundle_binding"] = source_b_bundle.binding
    certification["certified_input_bindings"]["source_p0_p8_certification_hash"] = source_b_hash
    certification["certified_input_bindings"]["source_bundle_hash"] = source_b_bundle_hash
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="unrelated-source-apply",
            artifact_root=config_a.artifact_root,
            source_run=source_b,
            black_label_run=config_a.run_dir,
            lightrag_stage="one_document_sample",
            legacy_source_certification_hash=source_b_hash,
            legacy_source_bundle_hash=source_b_bundle_hash,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert any(blocker.startswith("black_label_source_canonical_mismatch:") for blocker in ledger["blockers"])
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


@pytest.mark.parametrize("malicious_run_id", ["absolute", "../../outside-rebuild"])
def test_legacy_binding_rebuild_ignores_untrusted_certification_run_id(
    tmp_path: Path,
    malicious_run_id: str,
) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=None)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    outside = tmp_path / "outside-rebuild"
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("certified_input_bindings")
    certification["run_id"] = str(outside) if malicious_run_id == "absolute" else malicious_run_id
    certification_path.write_text(json.dumps(certification), encoding="utf-8")

    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="safe-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        )
    )

    assert migration["ok"] is True
    assert not outside.exists()
    assert not list(tmp_path.rglob("outside-rebuild"))


@pytest.mark.parametrize(
    ("target", "blocker_prefix"),
    [
        ("_regenerated_lightrag_input_bindings", "legacy_binding_canonical_regeneration_error:"),
        ("_verified_legacy_stage_ledger_records", "legacy_binding_live_recovery_error:"),
    ],
)
def test_legacy_binding_migration_sanitizes_internal_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    blocker_prefix: str,
) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=None)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("certified_input_bindings")
    certification_path.write_text(json.dumps(certification), encoding="utf-8")

    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(f"private failure at {tmp_path}")

    monkeypatch.setattr(subject, target, explode)
    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="failing-migration",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        )
    )

    assert migration["ok"] is False
    assert migration["blockers"][0].startswith(blocker_prefix)
    assert str(tmp_path) not in migration["blockers"][0]
    assert migration["mutation_performed"] is False
    assert not (config.run_dir / subject.LIGHTRAG_BINDING_MIGRATION_FILE).exists()


def test_minimal_source_certification_cannot_be_hash_attested_for_apply(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    source_certification_path = source_run / "p0-p8-certification.json"
    source_certification = {"ok": True}
    source_certification_path.write_text(json.dumps(source_certification), encoding="utf-8")
    source_hash = subject.stable_hash(source_certification)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification["ok"] = True
    certification["blockers"] = []
    certification["source_p0_p8_certification_hash"] = source_hash
    certification["source_rollout_schema_version"] = ""
    certification["source_rollout_provenance"] = subject.LEGACY_ROLLOUT_PROVENANCE
    certification["source_governed_p1_authorization"] = {
        "provenance_valid": True,
        "required": True,
        "authorized": True,
        "separately_reviewed": True,
        "controller_ready": True,
    }
    certification["source_legacy_attestation"] = None
    certification["certified_input_bindings"]["source_p0_p8_certification_hash"] = source_hash
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="minimal-certification-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            lightrag_stage="one_document_sample",
            legacy_source_certification_hash=source_hash,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert "source_p0_p8_certification_schema_invalid" in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_legacy_binding_sidecar_write_failure_is_sanitized_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_run, _ = make_source_run(tmp_path, governed_p1_authorized=None)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    certification.pop("certified_input_bindings")
    certification_path.write_text(json.dumps(certification), encoding="utf-8")
    original_write_json = subject._write_json

    def fail_sidecar(path: Path, payload: object) -> None:
        if path.name == subject.LIGHTRAG_BINDING_MIGRATION_FILE:
            raise OSError(f"private sidecar path: {path}")
        original_write_json(path, payload)

    monkeypatch.setattr(subject, "_write_json", fail_sidecar)
    migration = subject.migrate_legacy_lightrag_bindings(
        subject.BlackLabelConfig(
            run_id="sidecar-write-failure",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=config.run_dir,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        )
    )

    assert migration["ok"] is False
    assert migration["blockers"] == ["legacy_binding_sidecar_write_error:OSError"]
    assert str(tmp_path) not in migration["blockers"][0]
    assert not (config.run_dir / subject.LIGHTRAG_BINDING_MIGRATION_FILE).exists()
    assert not list(config.run_dir.glob(f".{subject.LIGHTRAG_BINDING_MIGRATION_FILE}.tmp-*"))


def test_lightrag_sample_apply_uses_one_curated_card_and_writes_ledger(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    apply_config = subject.BlackLabelConfig(
        run_id="sample-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
        black_label_run=black_label_run,
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(apply_config, client=fake)

    assert ledger["ok"] is True, ledger
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
    assert written["input_bindings"] == {
        "source_p0_p8_certification_hash": result_hash(source_run / "p0-p8-certification.json"),
        "source_bundle_hash": subject.load_source_bundle(config).binding["source_bundle_hash"],
        "black_label_card_manifest_hash": result_hash(black_label_run / "black-label-card-manifest.jsonl"),
        "lightrag_apply_plan_hash": result_hash(black_label_run / "lightrag-card-apply-plan.jsonl"),
    }


@pytest.mark.parametrize("tamper_target", ["cards", "plan", "source_certification"])
def test_lightrag_five_stage_blocks_stale_gate_one_bindings_before_insert(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    first = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )
    assert first["ok"] is True

    if tamper_target == "source_certification":
        path = source_run / "p0-p8-certification.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tamper_marker"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        filename = "black-label-card-manifest.jsonl" if tamper_target == "cards" else "lightrag-card-apply-plan.jsonl"
        path = black_label_run / filename
        rows = read_jsonl(path)
        rows[0]["tamper_marker"] = True
        write_jsonl(path, rows)

    fake = FakeLightRAGClient()
    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="five-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="five_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert any("input_bindings" in blocker or "certification_hash_mismatch" in blocker for blocker in ledger["blockers"])
    assert fake.insert_calls == 0
    assert fake.inserted_texts == []


def test_lightrag_stage_replay_preserves_applied_ledger_and_blocks_before_insert(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    apply_config = subject.BlackLabelConfig(
        run_id="first-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
        black_label_run=config.run_dir,
        lightrag_stage="one_document_sample",
        lightrag_poll_interval_s=0.0,
        lightrag_poll_timeout_s=1.0,
    )
    first = subject.apply_lightrag_stage(apply_config, client=FakeLightRAGClient())
    ledger_path = config.run_dir / subject.LIGHTRAG_SAMPLE_LEDGER
    before = ledger_path.read_bytes()
    fake = FakeLightRAGClient()

    replay = subject.apply_lightrag_stage(apply_config, client=fake)

    assert first["ok"] is True
    assert replay["ok"] is False
    assert replay["blockers"] == ["existing_stage_ledger_blocks_replay:one_document_sample"]
    assert fake.insert_calls == 0
    assert ledger_path.read_bytes() == before


def test_lightrag_topic_stage_recovery_is_bounded_and_verifies_existing_sources(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    extend_source_run_for_five_source_gate(source_run)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
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
            source_run=source_run,
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
            source_run=source_run,
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
                source_run=source_run,
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
            source_run=source_run,
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
    extend_source_run_for_five_source_gate(source_run)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    for stage in ("one_document_sample", "five_document_sample", "topic_cluster_sample"):
        subject.apply_lightrag_stage(
            subject.BlackLabelConfig(
                run_id=f"{stage}-apply",
                artifact_root=tmp_path / "artifacts",
                source_run=source_run,
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
            source_run=source_run,
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
    extend_source_run_for_five_source_gate(source_run)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
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
            source_run=source_run,
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
    apply_config = subject.BlackLabelConfig(
        run_id="sample-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
        black_label_run=config.run_dir,
    )
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
    apply_config = subject.BlackLabelConfig(
        run_id="sample-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
        black_label_run=config.run_dir,
    )
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
        source_run=source_run,
        black_label_run=config.run_dir,
        lightrag_stage="five_document_sample",
    )
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(apply_config, client=fake)

    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert ledger["blockers"] == ["missing_prerequisite_ledger:one_document_sample"]
    assert fake.inserted_texts == []


def test_lightrag_five_stage_blocks_before_insert_with_only_four_distinct_sources(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    extend_source_run_for_five_source_gate(source_run, total_sources=4, include_hashless_records=False)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="first-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="one_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=FakeLightRAGClient(),
    )
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="five-apply",
            artifact_root=tmp_path / "artifacts",
            source_run=source_run,
            black_label_run=black_label_run,
            lightrag_stage="five_document_sample",
            lightrag_poll_interval_s=0.0,
            lightrag_poll_timeout_s=1.0,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["blockers"] == ["five_document_cumulative_source_count_mismatch:4!=5"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0
    assert fake.inserted_texts == []


def test_lightrag_five_stage_applies_bounded_cards_after_first_card_prerequisite(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    extend_source_run_for_five_source_gate(source_run)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    black_label_run = config.run_dir
    first = subject.BlackLabelConfig(
        run_id="first-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
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
        prior_source_keys=subject._lightrag_prior_stage_source_keys(black_label_run, "five_document_sample"),
    )
    duplicate_source = str(selected[0]["file_source"])
    five = subject.BlackLabelConfig(
        run_id="five-apply",
        artifact_root=tmp_path / "artifacts",
        source_run=source_run,
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
    assert len(selected) == 4
    assert ledger["selected_count"] == 4
    assert ledger["sent_count"] == 3
    assert len(ledger["batch_manifest"]) >= 2
    assert len(fake.inserted_texts) == 3
    prior_sources = subject._lightrag_prior_stage_source_keys(black_label_run, "five_document_sample")
    selected_sources = {str(card["source_hash"] or card["source_pdf_id"]) for card in ledger["selected_cards"]}
    assert len(prior_sources | selected_sources) == subject.LIGHTRAG_STAGE_LIMITS["five_document_sample"]
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
        source_run=source_run,
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


@pytest.mark.parametrize("tamper_target", ["normalized", "crosswalk", "cag", "markdown"])
def test_legacy_bundle_attestation_blocks_consumed_artifact_tamper_before_insert(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    source_run, markdown = make_source_run(tmp_path, governed_p1_authorized=None)
    config = build_config(tmp_path, source_run)
    paths = {
        "normalized": source_run / "docling-normalized-output.jsonl",
        "crosswalk": source_run / "package-crosswalk.jsonl",
        "cag": source_run / "cag-pack-candidates.jsonl",
    }
    if tamper_target in paths:
        rows = read_jsonl(paths[tamper_target])
        rows[0]["public_label" if tamper_target != "cag" else "topic"] = "attacker-marker"
        write_jsonl(paths[tamper_target], rows)
    else:
        markdown.write_text("# Attacker marker\nRights-safe looking replacement.\n", encoding="utf-8")
        normalized_path = paths["normalized"]
        normalized = read_jsonl(normalized_path)
        text_row = next(row for row in normalized if row.get("record_id") == "file-md")
        text_row["artifact_sha256"] = hashlib.sha256(markdown.read_bytes()).hexdigest()
        write_jsonl(normalized_path, normalized)

    result = subject.run_all(config)
    fake = FakeLightRAGClient()
    ledger = subject.apply_lightrag_stage(
        subject.BlackLabelConfig(
            run_id="tampered-legacy-apply",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
            legacy_source_certification_hash=config.legacy_source_certification_hash,
            legacy_source_bundle_hash=config.legacy_source_bundle_hash,
        ),
        client=fake,
    )

    assert result["certification"]["ok"] is False
    assert subject.GOVERNED_P1_AUTHORIZATION_BLOCKER in result["certification"]["blockers"]
    assert ledger["ok"] is False
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


@pytest.mark.parametrize("tamper_target", ["count", "schema"])
def test_source_bundle_rejects_certified_count_or_schema_mismatch(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    if tamper_target == "count":
        path = source_run / "p0-p8-certification.json"
        certification = json.loads(path.read_text(encoding="utf-8"))
        certification["counts"]["normalized_records"] += 1
        path.write_text(json.dumps(certification), encoding="utf-8")
        expected = "source_bundle_count_mismatch:normalized_records"
    else:
        path = source_run / "docling-normalized-output.jsonl"
        rows = read_jsonl(path)
        rows[0]["schema_version"] = "attacker.v1"
        write_jsonl(path, rows)
        expected = "source_bundle_schema_mismatch:normalized"

    with pytest.raises(ValueError, match=expected):
        subject.load_source_bundle(subject.BlackLabelConfig(run_id="invalid-bundle", source_run=source_run))


def test_text_snapshot_rejects_path_swap_after_single_descriptor_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_run, markdown = make_source_run(tmp_path, protected_text=True)
    original_size = markdown.stat().st_size
    replacement = tmp_path / "clean-replacement.md"
    prefix = b"# Clean Heading\n"
    replacement.write_bytes(prefix + (b"x" * (original_size - len(prefix))))
    real_open = subject.os.open

    def swap_after_open(path: object, flags: int, *args: object) -> int:
        descriptor = real_open(path, flags, *args)
        if Path(path) == markdown:
            replacement.replace(markdown)
        return descriptor

    monkeypatch.setattr(subject.os, "open", swap_after_open)

    with pytest.raises(ValueError, match="source_text_artifact_path_changed_during_snapshot"):
        subject.load_source_bundle(subject.BlackLabelConfig(run_id="path-swap", source_run=source_run))


def test_apply_and_refresh_use_certified_generation_recipe(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    extend_source_run_for_five_source_gate(source_run)
    config = subject.replace(
        build_config(tmp_path, source_run),
        limit_pdfs=1,
        max_card_chars=1200,
        text_read_chars=20,
        eval_threshold=0.9876,
    )
    subject.run_all(config)
    original = json.loads((config.run_dir / "black-label-certification.json").read_text(encoding="utf-8"))
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="default-apply",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )
    refreshed = subject.refresh_black_label_certification(
        subject.BlackLabelConfig(
            run_id="default-refresh",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        )
    )

    assert ledger["ok"] is True
    assert fake.insert_calls == 1
    assert refreshed["certification"]["generation_recipe"] == original["generation_recipe"]
    assert refreshed["certification"]["generation_recipe_hash"] == original["generation_recipe_hash"]
    assert refreshed["certification"]["generation_recipe"]["eval_threshold"] == 0.9876
    assert refreshed["certification"]["quality_bar"]["target_eval_threshold"] == 0.9876


@pytest.mark.parametrize("legacy_recipe_mode", ["v1", "missing"])
def test_legacy_recipe_preserves_certified_eval_threshold_on_apply_and_refresh(
    tmp_path: Path,
    legacy_recipe_mode: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = subject.replace(build_config(tmp_path, source_run), eval_threshold=0.9876)
    subject.run_all(config)
    path = config.run_dir / "black-label-certification.json"
    certification = json.loads(path.read_text(encoding="utf-8"))
    if legacy_recipe_mode == "v1":
        certification["generation_recipe"].pop("eval_threshold")
        certification["generation_recipe"]["schema_version"] = (
            subject.LEGACY_BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION
        )
        certification["generation_recipe_hash"] = subject.stable_hash(
            certification["generation_recipe"]
        )
    else:
        certification.pop("generation_recipe")
        certification.pop("generation_recipe_hash")
    path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id=f"legacy-recipe-{legacy_recipe_mode}",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )
    refreshed = subject.refresh_black_label_certification(
        subject.BlackLabelConfig(
            run_id=f"legacy-refresh-{legacy_recipe_mode}",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        )
    )

    assert ledger["ok"] is True, ledger
    assert fake.insert_calls == 1
    assert (
        refreshed["certification"]["generation_recipe"]["schema_version"]
        == subject.BLACK_LABEL_GENERATION_RECIPE_SCHEMA_VERSION
    )
    assert refreshed["certification"]["generation_recipe"]["eval_threshold"] == 0.9876
    assert refreshed["certification"]["quality_bar"]["target_eval_threshold"] == 0.9876


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "black_label_generation_recipe.v999"),
        ("max_card_chars", "unbounded"),
    ],
)
def test_invalid_certified_generation_recipe_blocks_before_insert(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    path = config.run_dir / "black-label-certification.json"
    certification = json.loads(path.read_text(encoding="utf-8"))
    certification["generation_recipe"][field] = value
    certification["generation_recipe_hash"] = subject.stable_hash(certification["generation_recipe"])
    path.write_text(json.dumps(certification), encoding="utf-8")
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="invalid-recipe",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )

    assert "black_label_generation_recipe_invalid" in ledger["blockers"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_legacy_sample_apply_accepts_black_label_source_run_alias(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    fake = FakeLightRAGClient()

    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="legacy-alias",
            artifact_root=config.artifact_root,
            source_run=config.run_dir,
            source_root=source_run.parent,
        ),
        client=fake,
    )

    assert ledger["ok"] is True, ledger
    assert ledger["blockers"] == []
    assert fake.insert_calls == 1


def test_apply_fails_closed_when_client_lacks_service_enforced_fencing(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    fake = FakeLightRAGClient()
    fake.mutation_fencing_capability = None  # type: ignore[method-assign]
    fake.insert_texts_once = None  # type: ignore[method-assign]

    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="no-fence",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )

    assert ledger["blockers"] == ["lightrag_service_enforced_fencing_unavailable"]
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_invalid_fence_receipt_records_uncertain_mutation_and_blocks_replay(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)

    class MissingReceiptClient(FakeLightRAGClient):
        def insert_texts_once(self, texts: list[str], file_sources: list[str], *, fence_request: dict) -> dict:
            del fence_request
            return self.insert_texts(texts, file_sources)

    fake = MissingReceiptClient()
    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="missing-receipt",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )

    assert ledger["blockers"][0].startswith("lightrag_fence_receipt_invalid:")
    assert ledger["mutation_performed"] is True
    assert fake.insert_calls == 1
    assert (config.run_dir / f".{subject.LIGHTRAG_SAMPLE_LEDGER}.claim").exists()


def test_same_host_concurrent_apply_allows_only_one_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    fake = FakeLightRAGClient()
    barrier = threading.Barrier(2)
    original_write_exclusive = subject._write_exclusive_json

    def synchronized_claim(path: Path, payload: dict) -> None:
        barrier.wait(timeout=5)
        original_write_exclusive(path, payload)

    monkeypatch.setattr(subject, "_write_exclusive_json", synchronized_claim)
    apply_config = subject.BlackLabelConfig(
        run_id="concurrent-apply",
        artifact_root=config.artifact_root,
        source_run=source_run,
        black_label_run=config.run_dir,
    )
    results: list[dict] = []

    threads = [
        threading.Thread(target=lambda: results.append(subject.apply_lightrag_sample(apply_config, client=fake)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 2
    assert sum(result["ok"] is True for result in results) == 1
    assert fake.insert_calls == 1
    assert any("existing_stage_claim_blocks_apply:one_document_sample" in result["blockers"] for result in results)


def test_remote_fence_prevents_replay_across_independent_workspace_copies(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    copy_a = tmp_path / "copy-a"
    copy_b = tmp_path / "copy-b"
    shutil.copytree(config.run_dir, copy_a)
    shutil.copytree(config.run_dir, copy_b)
    fake = FakeLightRAGClient()
    results: list[dict] = []

    def apply_copy(run_dir: Path) -> None:
        results.append(
            subject.apply_lightrag_sample(
                subject.BlackLabelConfig(
                    run_id="distributed-apply",
                    artifact_root=config.artifact_root,
                    source_run=source_run,
                    black_label_run=run_dir,
                ),
                client=fake,
            )
        )

    threads = [threading.Thread(target=apply_copy, args=(run_dir,)) for run_dir in (copy_a, copy_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 2
    assert sum(result["ok"] is True for result in results) == 1
    assert fake.insert_calls == 1


def test_remote_fence_identity_is_stable_across_independently_generated_runs(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    first_config = build_config(tmp_path, source_run)
    second_config = subject.replace(first_config, run_id="black-label-fixture-second")
    subject.run_all(first_config)
    subject.run_all(second_config)
    fake = FakeLightRAGClient()

    first = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="independent-first",
            artifact_root=first_config.artifact_root,
            source_run=source_run,
            black_label_run=first_config.run_dir,
        ),
        client=fake,
    )
    second = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="independent-second",
            artifact_root=second_config.artifact_root,
            source_run=source_run,
            black_label_run=second_config.run_dir,
        ),
        client=fake,
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["blockers"][0].startswith("lightrag_insert_failure:")
    assert fake.insert_calls == 1
    first_certification = json.loads(
        (first_config.run_dir / "black-label-certification.json").read_text(encoding="utf-8")
    )
    second_certification = json.loads(
        (second_config.run_dir / "black-label-certification.json").read_text(encoding="utf-8")
    )
    assert subject.stable_hash(first_certification) != subject.stable_hash(second_certification)


def test_certification_change_after_preflight_blocks_before_remote_mutation(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)
    certification_path = config.run_dir / "black-label-certification.json"

    class CertificationMutatingClient(FakeLightRAGClient):
        def health(self) -> dict:
            certification = json.loads(certification_path.read_text(encoding="utf-8"))
            certification["attacker_nonce"] = "changed-after-claim"
            certification_path.write_text(json.dumps(certification), encoding="utf-8")
            return super().health()

    fake = CertificationMutatingClient()
    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="certification-toctou",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["blockers"] == [
        "ValueError:black_label_certification_changed_before_fence"
    ]
    assert ledger["mutation_attempted"] is False
    assert ledger["mutation_performed"] is False
    assert fake.insert_calls == 0


def test_post_commit_timeout_records_uncertain_attempt_and_retains_claim(tmp_path: Path) -> None:
    source_run, _ = make_source_run(tmp_path)
    config = build_config(tmp_path, source_run)
    subject.run_all(config)

    class CommitThenTimeoutClient(FakeLightRAGClient):
        def insert_texts_once(
            self,
            texts: list[str],
            file_sources: list[str],
            *,
            fence_request: dict,
        ) -> dict:
            super().insert_texts_once(texts, file_sources, fence_request=fence_request)
            raise TimeoutError("response_lost_after_commit")

    fake = CommitThenTimeoutClient()
    ledger = subject.apply_lightrag_sample(
        subject.BlackLabelConfig(
            run_id="post-commit-timeout",
            artifact_root=config.artifact_root,
            source_run=source_run,
            black_label_run=config.run_dir,
        ),
        client=fake,
    )

    assert ledger["ok"] is False
    assert ledger["blockers"] == ["TimeoutError:response_lost_after_commit"]
    assert ledger["mutation_attempted"] is True
    assert ledger["mutation_performed"] is False
    assert ledger["mutation_state"] == "uncertain"
    assert fake.insert_calls == 1
    assert (config.run_dir / f".{subject.LIGHTRAG_SAMPLE_LEDGER}.claim").exists()
