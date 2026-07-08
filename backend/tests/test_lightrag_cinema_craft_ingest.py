from __future__ import annotations

import json
from pathlib import Path

from app import lightrag_cinema_craft_ingest as subject


def build_source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    suite = root / "lightrag_cinema_craft_canon_deepening_suite"
    package = suite / "packages" / "01_round_03_canon_depth" / "001_bazin_realism"
    (package / "concept_cards").mkdir(parents=True)
    (package / "relation_cards").mkdir()
    (suite / "quarantine").mkdir(parents=True)
    (suite / "_manifest.json").write_text(
        json.dumps({"suite": "lightrag_cinema_craft_canon_deepening_suite", "rights_mode": "rights-safe"}),
        encoding="utf-8",
    )
    (suite / "package_registry.json").write_text(
        json.dumps(
            [
                {
                    "package_id": "001_bazin_realism",
                    "relative_path": "packages/01_round_03_canon_depth/001_bazin_realism",
                    "domain": "film theory",
                    "ingestion_priority": "P0",
                }
            ]
        ),
        encoding="utf-8",
    )
    (suite / "README.md").write_text("# Suite\n\nRights-safe concept summaries.", encoding="utf-8")
    (package / "concept_cards" / "01_core_mechanism.md").write_text(
        "# Core\n\nBazin realism preserves ambiguity and viewer attention.",
        encoding="utf-8",
    )
    (package / "concept_cards" / "02_duplicate.md").write_text(
        "# Core\n\nBazin realism preserves ambiguity and viewer attention.",
        encoding="utf-8",
    )
    (package / "relation_cards" / "01_relation_hint.md").write_text(
        "# Relation\n\nBazin contrasts with montage and translates to restraint.",
        encoding="utf-8",
    )
    (package / "agent_prompts.md").write_text("# Prompt\n\nInternal agent prompt.", encoding="utf-8")
    (suite / "quarantine" / "metadata_only_candidates.md").write_text("# Quarantine", encoding="utf-8")
    (suite / ".DS_Store").write_bytes(b"")
    return root


def test_inventory_classifies_selected_and_skipped_files(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)

    rows = subject.inventory_source(source_root)
    summary = subject.summarize_inventory(rows)

    assert summary["selected_files"] == 4
    assert summary["by_skip_reason"]["agent_prompt_skipped"] == 1
    assert summary["by_skip_reason"]["quarantine_path"] == 1
    selected_roles = {row.role for row in rows if row.selected}
    assert {"root_or_package_metadata", "concept_card", "relation_card"} <= selected_roles
    concept = next(row for row in rows if row.source_relative_path.endswith("01_core_mechanism.md"))
    assert concept.domain == "film theory"
    assert concept.priority == "P0"
    assert concept.sha256


def test_inventory_uses_direct_package_id_for_packages_without_round_folder(tmp_path: Path) -> None:
    root = tmp_path / "source"
    suite = root / "lightrag_cinema_craft_canon_enrichment_round_02"
    package = suite / "packages" / "02_pauline_kael_circles_and_squares_anti_auteur_package"
    package.mkdir(parents=True)
    (suite / "_manifest.json").write_text("{}", encoding="utf-8")
    (package / "INDEX.md").write_text("# Package index\n\nCritical debate package.", encoding="utf-8")

    rows = subject.inventory_source(root)

    row = next(item for item in rows if item.source_relative_path.endswith("INDEX.md"))
    assert row.package_id == "02_pauline_kael_circles_and_squares_anti_auteur_package"


def test_inventory_blocks_manual_review_rights_warnings(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    risky = (
        source_root
        / "lightrag_cinema_craft_canon_deepening_suite"
        / "packages"
        / "01_round_03_canon_depth"
        / "001_bazin_realism"
        / "concept_cards"
        / "03_risky.md"
    )
    risky.write_text("# Risk\n\nThis includes a full screenplay excerpt.", encoding="utf-8")

    rows = subject.inventory_source(source_root)

    row = next(item for item in rows if item.source_relative_path.endswith("03_risky.md"))
    assert row.selected is False
    assert row.skip_reason == "rights_warning_manual_review"
    assert row.rights_status == "manual_review"


def test_prepare_batches_dedupes_by_content_hash(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    report_dir = tmp_path / "report"
    rows = subject.inventory_source(source_root)

    items, batches = subject.prepare_batches(source_root, rows, report_dir, max_batch_chars=400, max_batch_items=2)

    assert len(items) == 3
    assert len(batches) >= 1
    selected_manifest = (report_dir / "selected-manifest.jsonl").read_text(encoding="utf-8")
    skipped_manifest = (report_dir / "skipped-manifest.jsonl").read_text(encoding="utf-8")
    assert "lcc-lightrag_cinema_craft_canon_deepening_suite" in selected_manifest
    assert "duplicate_sha256" in skipped_manifest
    assert "rights_posture: rights-safe metadata" in items[0].text
    assert '"rights_status"' in selected_manifest


def test_prepare_batches_can_limit_items_for_smoke_runs(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)

    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report", limit_items=1)

    assert len(items) == 1
    assert len(batches) == 1


def test_prepare_batches_skips_existing_hashes_and_file_sources(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    first_selected = next(row for row in rows if row.selected and row.sha256)
    second_selected = next(row for row in rows if row.selected and row.source_relative_path != first_selected.source_relative_path)
    existing_index = subject.ExistingDocumentIndex(
        source_hashes={first_selected.sha256 or ""},
        file_sources={second_selected.source_relative_path},
        document_ids={"doc-existing"},
    )

    items, _ = subject.prepare_batches(source_root, rows, tmp_path / "report", existing_index=existing_index)

    manifest = (tmp_path / "report" / "skipped-manifest.jsonl").read_text(encoding="utf-8")
    remaining_sources = {item.source_relative_path for item in items}
    assert first_selected.source_relative_path not in remaining_sources
    assert second_selected.source_relative_path not in remaining_sources
    assert "already_indexed_sha256" in manifest
    assert "already_indexed_file_source" in manifest


def test_inventory_skips_oversized_control_plane_files(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    suite = source_root / "lightrag_cinema_craft_canon_deepening_suite"
    (suite / "INDEX.md").write_text("# Index\n\n" + ("Large routing row.\n" * 700), encoding="utf-8")

    rows = subject.inventory_source(source_root)

    index = next(row for row in rows if row.source_relative_path.endswith("INDEX.md"))
    assert index.selected is False
    assert index.skip_reason == "oversized_control_plane_file"


def test_fetch_existing_document_index_extracts_hashes_and_sources() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def paginated_documents(self, *, page: int, page_size: int = 200, status_filter=None):
            self.calls += 1
            if page == 1:
                return {
                    "documents": [
                        {
                            "id": "doc-1",
                            "file_path": "suite/package/concept_cards/01.md",
                            "content_summary": "source_sha256: "
                            + "a" * 64
                            + "\nOriginal source SHA-256: `"
                            + "b" * 64
                            + "`",
                            "metadata": {"note": "manifest source sha256: " + "c" * 64},
                        }
                    ],
                    "pagination": {"has_next": True},
                }
            return {"documents": [], "pagination": {"has_next": False}}

    index = subject.fetch_existing_document_index(Client())  # type: ignore[arg-type]

    assert index.document_ids == {"doc-1"}
    assert index.file_sources == {"suite/package/concept_cards/01.md"}
    assert {"a" * 64, "b" * 64, "c" * 64} <= index.source_hashes


class FakeLightRAGClient:
    def __init__(self, *, base_url: str, timeout_s: float) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.insert_calls: list[tuple[list[str], list[str]]] = []
        self.settled_total: int | None = None
        self.reprocess_calls = 0

    def health(self):
        return {"status": "healthy"}

    def status_counts(self):
        total = self.settled_total or 10
        return {"status_counts": {"all": total, "processed": total, "failed": 0, "pending": 0, "processing": 0, "preprocessed": 0}}

    def pipeline_status(self):
        return {"busy": False, "request_pending": False}

    def insert_texts(self, texts, file_sources):
        self.insert_calls.append((texts, file_sources))
        return {"status": "success", "message": "accepted", "track_id": "track-1"}

    def reprocess_failed_documents(self):
        self.reprocess_calls += 1
        return {"status": "reprocessing_started", "message": "retrying", "track_id": ""}

    def failed_documents(self, *, limit: int = subject.FAILED_DOCUMENT_SNAPSHOT_LIMIT, page_size: int = 50):
        return []

    def wait_until_idle(self, *, interval_s: float, timeout_s: float):
        return {"busy": False, "request_pending": False, "latest_message": "done"}

    def wait_until_settled(self, *, interval_s: float, timeout_s: float, min_total_count=None):
        self.settled_total = min_total_count or 10
        return {
            "busy": False,
            "request_pending": False,
            "latest_message": "done",
            "settled": True,
            "timed_out": False,
            "active_count": 0,
            "total_count": min_total_count or 10,
            "min_total_count": min_total_count,
            "total_ready": True,
        }


def test_run_ingest_dry_run_does_not_send_batches(tmp_path: Path, monkeypatch) -> None:
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(items, batches, tmp_path / "report", run_id="run-a", apply=False)

    assert summary.ok is True
    assert summary.dry_run is True
    assert summary.batches_sent == 0


def test_run_ingest_apply_sends_batches_and_polls(tmp_path: Path, monkeypatch) -> None:
    instances: list[FakeLightRAGClient] = []

    class CapturingClient(FakeLightRAGClient):
        def __init__(self, *, base_url: str, timeout_s: float) -> None:
            super().__init__(base_url=base_url, timeout_s=timeout_s)
            instances.append(self)

    monkeypatch.setattr(subject, "LightRAGClient", CapturingClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
    )

    assert summary.ok is True
    assert summary.batches_sent == len(batches)
    assert instances[0].insert_calls
    assert (tmp_path / "report" / "ingest-summary.json").exists()


def test_run_ingest_apply_detects_new_failed_documents(tmp_path: Path, monkeypatch) -> None:
    class FailingPostflightClient(FakeLightRAGClient):
        def __init__(self, *, base_url: str, timeout_s: float) -> None:
            super().__init__(base_url=base_url, timeout_s=timeout_s)
            self.status_calls = 0

        def status_counts(self):
            self.status_calls += 1
            if self.status_calls == 1:
                return {"status_counts": {"all": 10, "processed": 10, "failed": 0, "pending": 0, "processing": 0, "preprocessed": 0}}
            return {"status_counts": {"all": 13, "processed": 12, "failed": 1, "pending": 0, "processing": 0, "preprocessed": 0}}

    monkeypatch.setattr(subject, "LightRAGClient", FailingPostflightClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
    )

    assert summary.ok is False
    assert summary.errors[-1]["error"] == "new_failed_documents"


def test_run_ingest_auto_reprocesses_new_failed_documents(tmp_path: Path, monkeypatch) -> None:
    instances: list[FakeLightRAGClient] = []

    class RecoveringPostflightClient(FakeLightRAGClient):
        def __init__(self, *, base_url: str, timeout_s: float) -> None:
            super().__init__(base_url=base_url, timeout_s=timeout_s)
            self.status_calls = 0
            instances.append(self)

        def status_counts(self):
            self.status_calls += 1
            if self.status_calls == 1:
                return {"status_counts": {"all": 10, "processed": 10, "failed": 0, "pending": 0, "processing": 0, "preprocessed": 0}}
            if self.status_calls == 2:
                return {"status_counts": {"all": 13, "processed": 12, "failed": 1, "pending": 0, "processing": 0, "preprocessed": 0}}
            return {"status_counts": {"all": 13, "processed": 13, "failed": 0, "pending": 0, "processing": 0, "preprocessed": 0}}

    monkeypatch.setattr(subject, "LightRAGClient", RecoveringPostflightClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
        auto_reprocess_failed_attempts=1,
    )

    assert summary.ok is True
    assert summary.errors == []
    assert instances[0].reprocess_calls == 1
    assert any(response.get("stage") == "reprocess_failed" for response in summary.responses)


def test_run_ingest_does_not_reprocess_provider_balance_failures(tmp_path: Path, monkeypatch) -> None:
    instances: list[FakeLightRAGClient] = []

    class ProviderBalanceFailureClient(FakeLightRAGClient):
        def __init__(self, *, base_url: str, timeout_s: float) -> None:
            super().__init__(base_url=base_url, timeout_s=timeout_s)
            self.status_calls = 0
            instances.append(self)

        def status_counts(self):
            self.status_calls += 1
            if self.status_calls == 1:
                return {
                    "status_counts": {
                        "all": 10,
                        "processed": 10,
                        "failed": 0,
                        "pending": 0,
                        "processing": 0,
                        "preprocessed": 0,
                    }
                }
            return {
                "status_counts": {
                    "all": 13,
                    "processed": 12,
                    "failed": 1,
                    "pending": 0,
                    "processing": 0,
                    "preprocessed": 0,
                }
            }

        def failed_documents(self, *, limit: int = subject.FAILED_DOCUMENT_SNAPSHOT_LIMIT, page_size: int = 50):
            return [
                {
                    "id": "doc-balance",
                    "file_path": "suite/package/concept_cards/01_core.md",
                    "error_msg": "APIStatusError: Error code: 402 - {'error': {'message': 'Insufficient Balance'}}",
                }
            ]

    monkeypatch.setattr(subject, "LightRAGClient", ProviderBalanceFailureClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
        auto_reprocess_failed_attempts=1,
    )

    assert summary.ok is False
    assert instances[0].reprocess_calls == 0
    assert summary.errors[-1]["error"] == "new_failed_documents"
    assert summary.errors[-1]["failed_error_class"] == "provider_insufficient_balance"
    assert summary.errors[-1]["retryable"] is False
    assert summary.errors[-1]["failed_document_sample"][0]["document_id"] == "doc-balance"


def test_run_ingest_rejects_existing_failed_documents_at_preflight(tmp_path: Path, monkeypatch) -> None:
    instances: list[FakeLightRAGClient] = []

    class ExistingFailedClient(FakeLightRAGClient):
        def __init__(self, *, base_url: str, timeout_s: float) -> None:
            super().__init__(base_url=base_url, timeout_s=timeout_s)
            instances.append(self)

        def status_counts(self):
            return {
                "status_counts": {
                    "all": 11,
                    "processed": 10,
                    "failed": 1,
                    "pending": 0,
                    "processing": 0,
                    "preprocessed": 0,
                }
            }

        def failed_documents(self, *, limit: int = subject.FAILED_DOCUMENT_SNAPSHOT_LIMIT, page_size: int = 50):
            return [
                {
                    "id": "doc-existing-failed",
                    "file_path": "suite/package/retrieval_eval.md",
                    "error_msg": "APIStatusError: Error code: 402 - Insufficient Balance",
                }
            ]

    monkeypatch.setattr(subject, "LightRAGClient", ExistingFailedClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
        auto_reprocess_failed_attempts=1,
    )

    assert summary.ok is False
    assert summary.batches_sent == 0
    assert instances[0].insert_calls == []
    assert instances[0].reprocess_calls == 0
    assert summary.errors[-1]["stage"] == "preflight"
    assert summary.errors[-1]["error"] == "failed_documents_present"
    assert summary.errors[-1]["failed_error_class"] == "provider_insufficient_balance"
    assert summary.errors[-1]["retryable"] is False


def test_run_ingest_rejects_active_preflight_backlog(tmp_path: Path, monkeypatch) -> None:
    class ActiveBacklogClient(FakeLightRAGClient):
        def status_counts(self):
            return {"status_counts": {"all": 10, "processed": 9, "failed": 0, "pending": 1, "processing": 0, "preprocessed": 0}}

    monkeypatch.setattr(subject, "LightRAGClient", ActiveBacklogClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(items, batches, tmp_path / "report", run_id="run-a", apply=True)

    assert summary.ok is False
    assert summary.batches_sent == 0
    assert summary.errors[-1]["error"] == "active_documents_present"


def test_run_ingest_marks_unsettled_timeout_as_failed(tmp_path: Path, monkeypatch) -> None:
    class TimeoutSettleClient(FakeLightRAGClient):
        def wait_until_settled(self, *, interval_s: float, timeout_s: float, min_total_count=None):
            return {
                "busy": False,
                "request_pending": False,
                "latest_message": "timed out with low total",
                "settled": False,
                "timed_out": True,
                "active_count": 0,
                "total_count": 10,
                "min_total_count": min_total_count,
                "total_ready": False,
            }

    monkeypatch.setattr(subject, "LightRAGClient", TimeoutSettleClient)
    source_root = build_source_root(tmp_path)
    rows = subject.inventory_source(source_root)
    items, batches = subject.prepare_batches(source_root, rows, tmp_path / "report")

    summary = subject.run_ingest(
        items,
        batches,
        tmp_path / "report",
        run_id="run-a",
        apply=True,
        poll_interval_s=0.001,
        poll_timeout_s=0.01,
    )

    assert summary.ok is False
    assert summary.errors[-1]["error"] == "pipeline_settle_timeout"


def test_collect_eval_queries_and_score_response(tmp_path: Path) -> None:
    source_root = build_source_root(tmp_path)
    eval_path = (
        source_root
        / "lightrag_cinema_craft_canon_deepening_suite"
        / "packages"
        / "01_round_03_canon_depth"
        / "001_bazin_realism"
        / "retrieval_eval.md"
    )
    eval_path.write_text(
        "| Type | Query | Expected retrieval |\n"
        "|---|---|---|\n"
        "| Canon | Which Bazin concept preserves ambiguity? | bazin + ambiguity + rights |\n",
        encoding="utf-8",
    )

    queries = subject.collect_eval_queries(source_root)
    query = next(item for item in queries if "Bazin concept" in item.query)
    result = subject.score_eval_response(
        query,
        {
            "response": "Bazin preserves ambiguity through realism and a rights-safe package route.",
            "references": [{"file_path": "packages/001_bazin_realism/concept_cards/01_core_mechanism.md"}],
        },
        latency_s=0.2,
    )

    assert query.expected_terms[:2] == ["bazin", "ambiguity"]
    assert result.usable is True
    assert result.reference_count == 1


def test_filter_rows_by_suite() -> None:
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(suite_id="lightrag_cinema_craft_canon_deepening_suite"),
        SimpleNamespace(suite_id="lightrag_cinema_craft_canon_enrichment_suite"),
        SimpleNamespace(suite_id="lightrag_cinema_craft_canon_enrichment_round_02"),
    ]

    # No filter -> unchanged.
    assert len(subject.filter_rows_by_suite(rows, None)) == 3
    assert len(subject.filter_rows_by_suite(rows, "  ")) == 3
    # Substring token matches both enrichment suites, excludes deepening.
    enriched = subject.filter_rows_by_suite(rows, "enrichment")
    assert {r.suite_id for r in enriched} == {
        "lightrag_cinema_craft_canon_enrichment_suite",
        "lightrag_cinema_craft_canon_enrichment_round_02",
    }
    # Comma-separated exact tokens.
    only_deep = subject.filter_rows_by_suite(rows, "canon_deepening_suite")
    assert [r.suite_id for r in only_deep] == ["lightrag_cinema_craft_canon_deepening_suite"]


NUMBERED_CARD = """---
id: "TEST-001"
slug: "bazin_realism"
domain: "film theory"
rights_mode: "metadata_summary_concept_cards_only"
retrieval_tags: ["lightrag", "film_theory"]
---

# Retrieval Evaluation

## Eval queries

1. What is the core mechanism of Bazin realism and how can it fix a weak scene?
2. How does Bazin realism translate into a commercial film without pastiche?

## Expected retrieval pattern

A strong answer should retrieve:

- this package's ingestion card
- at least one craft translation card
- relevant rights posture

## Failure modes

| Failure | Meaning | Fix |
|---|---|---|
| retrieves only manuals | weak node | add tags |
"""


def _write_card(root: Path, suite: str, package: str, body: str) -> None:
    card = root / suite / "packages" / package / "retrieval_eval.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(body, encoding="utf-8")


def test_parse_eval_card_numbered_format() -> None:
    queries = subject._parse_eval_card(NUMBERED_CARD, "suiteA/packages/001_bazin/retrieval_eval.md", "001_bazin")

    assert len(queries) == 2
    first = queries[0]
    assert "core mechanism of Bazin realism" in first.query
    assert first.expected_path_fragment == "001_bazin"
    assert first.domain == "film theory"
    assert first.rights_mode == "metadata_summary_concept_cards_only"
    assert "at least one craft translation card" in first.expected_qualities
    # Failure-mode table rows must not leak in as queries or qualities.
    assert all("retrieves only manuals" not in quality for quality in first.expected_qualities)


def test_collect_eval_queries_is_suite_stratified(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    _write_card(root, "lightrag_suite_a", "001_alpha", NUMBERED_CARD)
    _write_card(root, "lightrag_suite_a", "002_beta", NUMBERED_CARD.replace("Bazin realism", "Alpha Beta"))
    _write_card(root, "lightrag_suite_b", "001_gamma", NUMBERED_CARD.replace("Bazin realism", "Gamma Delta"))

    queries = subject.collect_eval_queries(root, include_sentinels=False, queries_per_card=1)
    suites = [q.source.split("/", 1)[0] for q in queries]

    assert set(suites) == {"lightrag_suite_a", "lightrag_suite_b"}
    # Round-robin interleaves suites: the second card sampled is from the other suite.
    assert suites[0] != suites[1]


def test_is_eval_infra_card_detects_scaffolding_packages() -> None:
    assert subject._is_eval_infra_card(
        "lightrag_cinema_craft_canon_deepening_suite/packages/04_retrieval_eval_suite/013_eval_failure_modes/retrieval_eval.md"
    )
    assert subject._is_eval_infra_card(
        "suite/packages/02_round_04_case_mechanics/091_retrieve_by_emotion_not_title_eval_pack/retrieval_eval.md"
    )
    assert not subject._is_eval_infra_card(
        "suite/packages/01_round_03_canon_depth/045_apocalypse_now/retrieval_eval.md"
    )


def test_is_meta_query_flags_graph_membership_questions() -> None:
    assert subject._is_meta_query("What does `Taxi Driver package` add to the LightRAG graph?")
    assert subject._is_meta_query("What does this add to the graph?")
    assert not subject._is_meta_query(
        "What is the core mechanism of Bazin realism and how can it fix a weak scene?"
    )


META_AND_CRAFT_CARD = """---
domain: "film theory"
---

# Retrieval Evaluation

## Eval queries

1. What does `Bazin package` add to the LightRAG graph?
2. What is the core mechanism of Bazin realism and how can it fix a weak scene?
"""

INFRA_SUITE_CARD = """---
domain: "retrieval evaluation / LightRAG"
---

# Retrieval Evaluation

## Eval queries

1. What is the core mechanism of Eval Failure Modes and how can it help a director?
"""

INFRA_PACK_CARD = """---
domain: "AI / retrieval case mechanic"
---

# Retrieval Evaluation

## Eval queries

1. What is the core mechanism of Retrieve By Emotion Not Title Eval Pack and how can it help?
"""


def test_collect_eval_queries_craft_only_excludes_infra_and_meta(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    suite = "lightrag_cinema_craft_canon_deepening_suite"
    _write_card(root, suite, "01_round_03_canon_depth/001_bazin", META_AND_CRAFT_CARD)
    _write_card(root, suite, "04_retrieval_eval_suite/013_eval_failure_modes", INFRA_SUITE_CARD)
    _write_card(
        root,
        suite,
        "02_round_04_case_mechanics/091_retrieve_by_emotion_not_title_eval_pack",
        INFRA_PACK_CARD,
    )

    craft = subject.collect_eval_queries(root, include_sentinels=False, queries_per_card=5)
    craft_text = [q.query for q in craft]
    # Eval-infrastructure cards are skipped entirely (by package path).
    assert not any("Eval Failure Modes" in q for q in craft_text)
    assert not any("Retrieve By Emotion" in q for q in craft_text)
    # Meta-graph query is dropped, but the card survives via its craft question.
    assert not any("add to the LightRAG graph" in q for q in craft_text)
    assert any("core mechanism of Bazin realism" in q for q in craft_text)

    legacy = subject.collect_eval_queries(
        root, include_sentinels=False, queries_per_card=5, craft_only=False
    )
    legacy_text = [q.query for q in legacy]
    # Legacy/uncalibrated set keeps the infra cards and the meta-graph query.
    assert any("add to the LightRAG graph" in q for q in legacy_text)
    assert any("Eval Failure Modes" in q for q in legacy_text)
    assert any("Retrieve By Emotion" in q for q in legacy_text)


def test_score_eval_response_blends_judge_precision_sanity() -> None:
    query = subject.EvalQuery(
        query="How does silence build threat?",
        expected_terms=[],
        source="suiteA/packages/047_no_country/retrieval_eval.md",
        expected_qualities=["names the silence mechanism"],
        expected_path_fragment="047_no_country",
        domain="sound design",
    )
    payload = {
        "response": "Silence functions as a structural threat mechanism, not a mood, in the No Country approach.",
        "references": [{"file_path": "packages/047_no_country/craft_translation_cards/04_sound.md"}],
    }

    def fake_judge(_query, _response):
        return subject.JudgeVerdict(score=0.8, rights_safe=True, reason="on topic")

    result = subject.score_eval_response(query, payload, latency_s=0.1, judge=fake_judge)

    assert result.judge_score == 0.8
    assert result.retrieval_precision == 1.0
    assert result.sanity_score == 1.0
    # 0.8*0.5 + 1.0*0.35 + 1.0*0.15 = 0.90
    assert result.score == 0.9
    assert result.usable is True
    assert result.rights_safe is True


def test_score_eval_response_applies_rights_penalty() -> None:
    query = subject.EvalQuery(
        query="How do I copy this style exactly?",
        expected_terms=[],
        source="suiteA/packages/001_x/retrieval_eval.md",
        expected_path_fragment="001_x",
    )
    payload = {
        "response": "Here is how to reproduce the copyrighted frames verbatim for your project right now.",
        "references": [{"file_path": "packages/001_x/concept_cards/01.md"}],
    }

    def unsafe_judge(_query, _response):
        return subject.JudgeVerdict(score=0.9, rights_safe=False, reason="imitation advice")

    result = subject.score_eval_response(query, payload, latency_s=0.1, judge=unsafe_judge)

    assert result.rights_safe is False
    # 0.9*0.5 + 1.0*0.35 + 1.0*0.15 - 0.35 = 0.60 -> below threshold
    assert result.score == 0.6
    assert result.usable is False


def test_retrieval_precision_fragment_domain_and_fallback() -> None:
    hit = subject.EvalQuery(query="q", expected_terms=[], source="s", expected_path_fragment="047_no_country", domain="sound")
    assert subject._retrieval_precision(hit, ["packages/047_no_country/04_sound.md"], 0.0) == 1.0
    assert subject._retrieval_precision(hit, ["packages/999_other/sound_card.md"], 0.0) == 0.5
    assert subject._retrieval_precision(hit, ["packages/999_other/01.md"], 0.0) == 0.0

    sentinel = subject.EvalQuery(query="q", expected_terms=["bazin"], source="s")
    assert subject._retrieval_precision(sentinel, ["any.md"], 0.75) == 0.75


def test_parse_judge_verdict_json_and_fallback() -> None:
    clean = subject._parse_judge_verdict('{"score": 0.83, "rights_safe": true, "reason": "good"}')
    assert clean.score == 0.83 and clean.rights_safe is True

    wrapped = subject._parse_judge_verdict('Sure!\n```json\n{"score": 1.0, "rights_safe": false}\n```\n')
    assert wrapped.score == 1.0 and wrapped.rights_safe is False

    loose = subject._parse_judge_verdict("I think the score is 0.4 and rights_safe: no")
    assert loose.score == 0.4 and loose.rights_safe is False


def test_run_eval_with_injected_judge(tmp_path: Path, monkeypatch) -> None:
    class QueryClient(FakeLightRAGClient):
        def query(self, query, **kwargs):
            return {
                "response": "A concrete, on-topic, rights-safe craft answer about the mechanism.",
                "references": [{"file_path": "packages/001_bazin/concept_cards/01_core_mechanism.md"}],
            }

    monkeypatch.setattr(subject, "LightRAGClient", QueryClient)

    queries = [
        subject.EvalQuery(
            query="What is the core mechanism?",
            expected_terms=[],
            source="suiteA/packages/001_bazin/retrieval_eval.md",
            expected_qualities=["names the mechanism"],
            expected_path_fragment="001_bazin",
        )
    ]

    def fake_judge(_query, _response):
        return subject.JudgeVerdict(score=0.95, rights_safe=True, reason="strong")

    report = subject.run_eval(queries, tmp_path / "eval", threshold=0.89, judge=fake_judge)

    assert report["judge_used"] is True
    assert report["query_count"] == 1
    assert report["mean_judge_score"] == 0.95
    assert report["mean_retrieval_precision"] == 1.0
    assert report["aggregate_score"] >= 0.89
    assert report["ok"] is True
    assert (tmp_path / "eval" / "eval-report.json").exists()
    assert "Precision" in (tmp_path / "eval" / "eval-report.md").read_text(encoding="utf-8")
