from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.dante_visual import decoupage_ingest as subject
from app.dante_visual.decoupage_ingest import (
    DECOUPAGE_ARTIFACT_TYPE,
    DecoupageBundle,
    decoupage_node_id_for,
    image_node_id_for_source_hash,
    ingest_decoupage_bundles,
    promote_decoupage_run,
)
from app.dante_visual.manifest import VisualAsset


class FakeCollection:
    def __init__(self, *, existing_ids: set[str] | None = None, decoupage_ids: set[str] | None = None) -> None:
        self.existing_ids = existing_ids or set()
        self.decoupage_ids = decoupage_ids or set()
        self.deleted: list[str] = []
        self.upserts: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> dict[str, Any]:
        ids = kwargs.get("ids")
        if ids is not None:
            found = [node_id for node_id in ids if node_id in self.existing_ids or node_id in self.decoupage_ids]
            return {"ids": found, "metadatas": [{} for _ in found]}
        where = kwargs.get("where") or {}
        if where.get("artifact_type") == DECOUPAGE_ARTIFACT_TYPE:
            return {
                "ids": list(self.decoupage_ids),
                "metadatas": [
                    {"dataset_id": "dante-visual-reference-assets", "artifact_type": DECOUPAGE_ARTIFACT_TYPE}
                    for _ in self.decoupage_ids
                ],
            }
        return {"ids": [], "metadatas": []}

    def delete(self, ids: list[str]) -> None:
        self.deleted.extend(ids)
        for node_id in ids:
            self.decoupage_ids.discard(node_id)
            self.existing_ids.discard(node_id)

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        self.upserts.append({"ids": ids, "documents": documents, "metadatas": metadatas, "embeddings": embeddings})
        self.decoupage_ids.update(ids)


class FakeEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_text(self, text: str, *, input_type: str) -> list[float]:
        assert input_type == "document"
        self.texts.append(text)
        return [1.0, 2.0, 3.0]


class FakeVectorStore:
    def __init__(self) -> None:
        self.nodes: list[Any] = []

    def add(self, nodes: list[Any]) -> None:
        self.nodes.extend(nodes)


class FakeKB:
    def __init__(self, *, existing_ids: set[str] | None = None, decoupage_ids: set[str] | None = None) -> None:
        self.collection = FakeCollection(existing_ids=existing_ids, decoupage_ids=decoupage_ids)
        self.embedder = FakeEmbedder()
        self.vector_store = FakeVectorStore()


def asset(*, sha: str = "a" * 64) -> VisualAsset:
    return VisualAsset(
        row_number=2,
        image_id="aftersun-2022-001",
        old_relative_path="old/aftersun-2022-001.jpg",
        new_relative_path="film-stills/aftersun-2022/aftersun-2022-001.jpg",
        previous_relative_path="",
        sha256=sha,
        bytes=12345,
        category="film-stills",
        group="aftersun-2022",
        batch_or_note="test",
        width=1924,
        height=1040,
        file_name="aftersun-2022-001.jpg",
        file_stem="aftersun-2022-001",
    )


def sidecar_for(item: VisualAsset, *, sha: str | None = None) -> dict[str, Any]:
    source_sha = sha or item.sha256
    return {
        "asset_id": item.image_id,
        "lens": "solo",
        "one_line": "A cyan resort dining frame with foreground occlusion.",
        "decoupage_spine": {"key": "distance", "form": "wide", "angle": "observed"},
        "composition": {"blocking": "foreground silhouettes frame the room"},
        "camera_lens": {"shot_size": "wide"},
        "lighting": {"quality": "fluorescent cyan"},
        "color": {"palette": ["cyan", "amber"]},
        "art_direction": {"space": "holiday resort dining hall"},
        "costume": {"notes": "summer casual"},
        "performance": {"notes": "background social drift"},
        "registers": {"technical": "controlled occlusion"},
        "lineage": {"references": ["Aftersun"]},
        "distinction": {"verdict": "collection-worthy"},
        "grounding": {"visible": ["tables"], "inferred": ["resort"], "uncertain": [], "not_visible": []},
        "proactive_adjacencies": ["liminal hotel corridor"],
        "opinion": "Worth indexing for cyan-night social distance.",
        "provenance": {"confidence_overall": 0.91},
        "markdown_handoff": "# Aftersun decoupage\n\nCyan resort light with emotional distance.",
        "_dante_binding": {
            "image_id": item.image_id,
            "source_sha256": source_sha,
            "new_relative_path": item.new_relative_path,
            "provider": "gemini",
            "model": "gemini-3.1-pro-preview",
            "api_surface": "Gemini Developer API",
            "uses_vertex": False,
        },
    }


def write_source_run(tmp_path: Path, item: VisualAsset, payload: dict[str, Any]) -> Path:
    source_run_dir = tmp_path / "source-run"
    sidecar_path = source_run_dir / "sidecars" / f"{item.image_id}.json"
    markdown_path = source_run_dir / "markdown" / f"{item.image_id}.md"
    sidecar_path.parent.mkdir(parents=True)
    markdown_path.parent.mkdir(parents=True)
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(payload["markdown_handoff"] + "\n", encoding="utf-8")
    summary = {
        "final": True,
        "provider": "gemini",
        "api_surface": "Gemini Developer API",
        "uses_vertex": False,
        "model": "gemini-3.1-pro-preview",
        "target_count": 1,
        "ok_count": 1,
        "error_count": 0,
        "average_confidence_overall": 0.91,
        "threshold": 0.87,
        "pass": True,
        "results": [
            {
                "image_id": item.image_id,
                "status": "ok",
                "sidecar_json": str(sidecar_path),
                "sidecar_markdown": str(markdown_path),
                "error": "",
            }
        ],
    }
    (source_run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return source_run_dir


@pytest.fixture(autouse=True)
def small_expected_target_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject, "EXPECTED_TARGET_COUNT", 1)


def test_promote_decoupage_run_copies_then_skips_identical_files(tmp_path: Path) -> None:
    item = asset()
    payload = sidecar_for(item)
    source_run_dir = write_source_run(tmp_path, item, payload)
    analysis_root = tmp_path / "analysis-cards"
    run_dir = analysis_root / "decoupage" / "manifests" / "ingest-run"

    result = promote_decoupage_run(
        source_run_dir=source_run_dir,
        canonical_sidecars_root=analysis_root / "decoupage" / "sidecars",
        canonical_markdown_root=analysis_root / "decoupage" / "markdown",
        analysis_root=analysis_root,
        manifest_run_dir=run_dir,
        assets=[item],
        source_run_id="source-run",
        run_id="ingest-run",
    )

    assert result["summary"]["promoted"] == 1
    assert (analysis_root / "decoupage" / "sidecars" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json").exists()
    assert (run_dir / "decoupage-promotion-manifest.tsv").exists()

    rerun = promote_decoupage_run(
        source_run_dir=source_run_dir,
        canonical_sidecars_root=analysis_root / "decoupage" / "sidecars",
        canonical_markdown_root=analysis_root / "decoupage" / "markdown",
        analysis_root=analysis_root,
        manifest_run_dir=run_dir,
        assets=[item],
        source_run_id="source-run",
        run_id="ingest-run",
    )

    assert rerun["summary"]["already_same"] == 1


def test_promote_decoupage_run_backs_up_different_canonical_files(tmp_path: Path) -> None:
    item = asset()
    payload = sidecar_for(item)
    source_run_dir = write_source_run(tmp_path, item, payload)
    analysis_root = tmp_path / "analysis-cards"
    sidecar_target = analysis_root / "decoupage" / "sidecars" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json"
    markdown_target = analysis_root / "decoupage" / "markdown" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.md"
    sidecar_target.parent.mkdir(parents=True)
    markdown_target.parent.mkdir(parents=True)
    sidecar_target.write_text('{"old": true}\n', encoding="utf-8")
    markdown_target.write_text("old markdown\n", encoding="utf-8")

    result = promote_decoupage_run(
        source_run_dir=source_run_dir,
        canonical_sidecars_root=analysis_root / "decoupage" / "sidecars",
        canonical_markdown_root=analysis_root / "decoupage" / "markdown",
        analysis_root=analysis_root,
        manifest_run_dir=analysis_root / "decoupage" / "manifests" / "ingest-run",
        assets=[item],
        source_run_id="source-run",
        run_id="ingest-run",
    )

    assert result["summary"]["backed_up_replaced"] == 1
    manifest = (analysis_root / "decoupage" / "manifests" / "ingest-run" / "decoupage-promotion-manifest.tsv").read_text(
        encoding="utf-8"
    )
    assert "backed_up_replaced" in manifest
    assert list((analysis_root / "decoupage" / "manifests" / "ingest-run" / "backups").rglob("*.bak"))


def test_promote_decoupage_run_rejects_mismatched_binding(tmp_path: Path) -> None:
    item = asset()
    source_run_dir = write_source_run(tmp_path, item, sidecar_for(item, sha="b" * 64))
    analysis_root = tmp_path / "analysis-cards"

    result = promote_decoupage_run(
        source_run_dir=source_run_dir,
        canonical_sidecars_root=analysis_root / "decoupage" / "sidecars",
        canonical_markdown_root=analysis_root / "decoupage" / "markdown",
        analysis_root=analysis_root,
        manifest_run_dir=analysis_root / "decoupage" / "manifests" / "ingest-run",
        assets=[item],
        source_run_id="source-run",
        run_id="ingest-run",
    )

    assert result["summary"]["invalid_binding"] == 1
    assert not (analysis_root / "decoupage" / "sidecars").exists()


def test_validate_source_run_summary_rejects_truncated_results(tmp_path: Path) -> None:
    item = asset()
    source_run_dir = write_source_run(tmp_path, item, sidecar_for(item))
    summary_path = source_run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["results"] = []
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="results_count=0"):
        subject.validate_source_run_summary(source_run_dir, source_run_id="source-run")


def test_validate_source_run_summary_rejects_source_path_escape(tmp_path: Path) -> None:
    item = asset()
    source_run_dir = write_source_run(tmp_path, item, sidecar_for(item))
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    summary_path = source_run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["results"][0]["sidecar_json"] = str(outside)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="path escapes source run"):
        subject.validate_source_run_summary(source_run_dir, source_run_id="source-run")


def test_promote_decoupage_run_resolves_duplicate_image_id_by_binding_hash(tmp_path: Path) -> None:
    film_asset = asset(sha="a" * 64)
    duplicate_asset = VisualAsset(
        row_number=3,
        image_id=film_asset.image_id,
        old_relative_path="old/duplicate.jpg",
        new_relative_path="shotdeck-batches/batch-2026-05-02/aftersun-2022-001.jpg",
        previous_relative_path="",
        sha256="b" * 64,
        bytes=12345,
        category="shotdeck-batches",
        group="batch-2026-05-02",
        batch_or_note="test",
        width=1924,
        height=1040,
        file_name="aftersun-2022-001.jpg",
        file_stem="aftersun-2022-001",
    )
    source_run_dir = write_source_run(tmp_path, film_asset, sidecar_for(film_asset))
    analysis_root = tmp_path / "analysis-cards"

    result = promote_decoupage_run(
        source_run_dir=source_run_dir,
        canonical_sidecars_root=analysis_root / "decoupage" / "sidecars",
        canonical_markdown_root=analysis_root / "decoupage" / "markdown",
        analysis_root=analysis_root,
        manifest_run_dir=analysis_root / "decoupage" / "manifests" / "ingest-run",
        assets=[film_asset, duplicate_asset],
        source_run_id="source-run",
        run_id="ingest-run",
    )

    assert result["summary"]["promoted"] == 1
    assert (analysis_root / "decoupage" / "sidecars" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json").exists()
    assert not (analysis_root / "decoupage" / "sidecars" / "shotdeck-batches").exists()


def bundle(tmp_path: Path, *, sha: str = "a" * 64) -> DecoupageBundle:
    item = asset(sha=sha)
    payload = sidecar_for(item)
    sidecar_path = tmp_path / "analysis-cards" / "decoupage" / "sidecars" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json"
    markdown_path = tmp_path / "analysis-cards" / "decoupage" / "markdown" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.md"
    sidecar_path.parent.mkdir(parents=True)
    markdown_path.parent.mkdir(parents=True)
    sidecar_path.write_text(json.dumps(payload), encoding="utf-8")
    markdown_path.write_text(payload["markdown_handoff"], encoding="utf-8")
    return DecoupageBundle(
        image_id=item.image_id,
        source_sha256=item.sha256,
        category=item.category,
        group=item.group,
        image_relative_path=item.new_relative_path,
        image_file_name=item.file_name,
        image_width=item.width,
        image_height=item.height,
        sidecar_json_path=sidecar_path,
        markdown_path=markdown_path,
        sidecar_json_relative_path="decoupage/sidecars/film-stills/aftersun-2022/aftersun-2022-001.json",
        markdown_relative_path="decoupage/markdown/film-stills/aftersun-2022/aftersun-2022-001.md",
        source_run_id="source-run",
        sidecar=payload,
        markdown=markdown_path.read_text(encoding="utf-8"),
    )


def test_ingest_decoupage_bundles_links_text_to_existing_image(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(existing_ids={image_node_id_for_source_hash(item.source_sha256)})

    result = ingest_decoupage_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="ingest-run",
        source_run_id="source-run",
    )

    assert result["summary"]["embedded"] == 1
    assert len(kb.vector_store.nodes) == 1
    node = kb.vector_store.nodes[0]
    assert node.node_id == decoupage_node_id_for(item.source_sha256)
    assert abs(sum(value * value for value in node.embedding) - 1.0) < 0.00001
    assert node.metadata["dataset_id"] == "dante-visual-reference-assets"
    assert node.metadata["artifact_type"] == DECOUPAGE_ARTIFACT_TYPE
    assert node.metadata["schema"] == "decoupage_sidecar"
    assert node.metadata["profile_id"] == "art_grade_decoupage_vision_analyst.gpt55_port.v1"
    assert node.metadata["provider"] == "gemini"
    assert node.metadata["model"] == "gemini-3.1-pro-preview"
    assert node.metadata["api_surface"] == "Gemini Developer API"
    assert node.metadata["run_id"] == "ingest-run"
    assert node.metadata["source_run_id"] == "source-run"
    assert node.metadata["dante_image_id"] == "aftersun-2022-001"
    assert node.metadata["category"] == "film-stills"
    assert node.metadata["group"] == "aftersun-2022"
    assert node.metadata["modality"] == "text"
    assert node.metadata["decoupage_json_sha256"]
    assert node.metadata["decoupage_markdown_sha256"]
    assert node.metadata["decoupage_json_path"].endswith(".json")
    assert node.metadata["decoupage_markdown_path"].endswith(".md")
    assert node.metadata["linked_image_file_id"] == image_node_id_for_source_hash(item.source_sha256)
    assert node.metadata["preview_image_file_id"] == image_node_id_for_source_hash(item.source_sha256)
    assert "Markdown handoff" in node.text
    assert "Cyan resort light" in node.text
    for field in subject.SEARCHABLE_FIELDS:
        assert f"- {field}:" in node.text


def test_ingest_decoupage_bundles_skips_existing_node(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(
        existing_ids={image_node_id_for_source_hash(item.source_sha256)},
        decoupage_ids={decoupage_node_id_for(item.source_sha256)},
    )

    result = ingest_decoupage_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="ingest-run",
        source_run_id="source-run",
    )

    assert result["summary"]["skipped_existing"] == 1
    assert kb.vector_store.nodes == []


def test_ingest_decoupage_bundles_reports_missing_linked_image(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB()

    result = ingest_decoupage_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="ingest-run",
        source_run_id="source-run",
    )

    assert result["summary"]["missing_linked_image"] == 1
    assert kb.vector_store.nodes == []


def test_ingest_decoupage_bundles_force_upserts_existing_decoupage_node(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(
        existing_ids={image_node_id_for_source_hash(item.source_sha256), "dante_visual_card_keep"},
        decoupage_ids={decoupage_node_id_for(item.source_sha256)},
    )

    result = ingest_decoupage_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="ingest-run",
        source_run_id="source-run",
        force=True,
    )

    assert result["summary"]["embedded"] == 1
    assert kb.collection.deleted == []
    assert kb.collection.upserts[0]["ids"] == [decoupage_node_id_for(item.source_sha256)]


def test_ingest_decoupage_bundles_force_does_not_delete_when_linked_image_missing(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(decoupage_ids={decoupage_node_id_for(item.source_sha256)})

    result = ingest_decoupage_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="ingest-run",
        source_run_id="source-run",
        force=True,
    )

    assert result["summary"]["missing_linked_image"] == 1
    assert kb.collection.deleted == []
    assert kb.vector_store.nodes == []
