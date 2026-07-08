from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dante_visual.card_ingest import (
    CARD_ARTIFACT_TYPE,
    VisualCardBundle,
    card_node_id_for,
    ingest_visual_card_bundles,
    node_id_for_source_hash,
)


class FakeCollection:
    def __init__(self, *, existing_ids: set[str] | None = None, card_ids: set[str] | None = None) -> None:
        self.existing_ids = existing_ids or set()
        self.card_ids = card_ids or set()
        self.deleted: list[str] = []

    def get(self, **kwargs: Any) -> dict[str, Any]:
        ids = kwargs.get("ids")
        if ids is not None:
            found = [node_id for node_id in ids if node_id in self.existing_ids or node_id in self.card_ids]
            return {"ids": found, "metadatas": [{} for _ in found]}
        where = kwargs.get("where") or {}
        if where.get("artifact_type") == CARD_ARTIFACT_TYPE:
            return {
                "ids": list(self.card_ids),
                "metadatas": [
                    {"dataset_id": "dante-visual-reference-assets", "artifact_type": CARD_ARTIFACT_TYPE}
                    for _ in self.card_ids
                ],
            }
        return {"ids": [], "metadatas": []}

    def delete(self, ids: list[str]) -> None:
        self.deleted.extend(ids)
        for node_id in ids:
            self.card_ids.discard(node_id)
            self.existing_ids.discard(node_id)


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
    def __init__(self, *, existing_ids: set[str] | None = None, card_ids: set[str] | None = None) -> None:
        self.collection = FakeCollection(existing_ids=existing_ids, card_ids=card_ids)
        self.embedder = FakeEmbedder()
        self.vector_store = FakeVectorStore()


def bundle(tmp_path: Path, *, sha: str = "a" * 64) -> VisualCardBundle:
    json_path = tmp_path / "cards" / "film-stills" / "aftersun-2022" / "aftersun-2022-001.json"
    md_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True)
    card = {
        "image_id": "aftersun-2022-001",
        "run_id": "visual-gemini-batch100",
        "source": {
            "sha256": sha,
            "category": "film-stills",
            "group": "aftersun-2022",
            "new_relative_path": "film-stills/aftersun-2022/aftersun-2022-001.jpg",
        },
        "asset": {"file_name": "aftersun-2022-001.jpg"},
        "normalized_analysis": {
            "subject": {"value": "communal resort dinner"},
            "lighting": {"value": "mixed color temperature"},
        },
        "editorial_judgment": {"score": 80, "tier": "reference", "recommendation": "keep"},
    }
    json_path.write_text(json.dumps(card), encoding="utf-8")
    md_path.write_text("# aftersun-2022-001\n\nMixed resort light.", encoding="utf-8")
    return VisualCardBundle(
        image_id="aftersun-2022-001",
        source_sha256=sha,
        category="film-stills",
        group="aftersun-2022",
        image_relative_path="film-stills/aftersun-2022/aftersun-2022-001.jpg",
        image_file_name="aftersun-2022-001.jpg",
        image_width=1924,
        image_height=1040,
        card_json_path=json_path,
        card_markdown_path=md_path,
        card_json_relative_path="cards/film-stills/aftersun-2022/aftersun-2022-001.json",
        card_markdown_relative_path="cards/film-stills/aftersun-2022/aftersun-2022-001.md",
        card_run_id="visual-gemini-batch100",
        card=card,
        markdown=md_path.read_text(encoding="utf-8"),
    )


def test_ingest_visual_card_bundles_links_text_to_existing_image(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(existing_ids={node_id_for_source_hash(item.source_sha256)})

    result = ingest_visual_card_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="card-ingest-test",
        source_run_id="visual-gemini-batch100",
    )

    assert result["summary"]["embedded"] == 1
    assert len(kb.vector_store.nodes) == 1
    node = kb.vector_store.nodes[0]
    assert node.node_id == card_node_id_for(item.source_sha256)
    assert node.metadata["preview_image_file_id"] == node_id_for_source_hash(item.source_sha256)
    assert node.metadata["card_json_relative_path"].endswith(".json")
    assert "communal resort dinner" in node.text
    assert "Compact JSON card" in node.text
    assert (tmp_path / "run" / "card-ingest-summary.json").exists()


def test_ingest_visual_card_bundles_skips_existing_card(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB(
        existing_ids={node_id_for_source_hash(item.source_sha256)},
        card_ids={card_node_id_for(item.source_sha256)},
    )

    result = ingest_visual_card_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="card-ingest-test",
        source_run_id="visual-gemini-batch100",
    )

    assert result["summary"]["embedded"] == 0
    assert result["summary"]["skipped_existing"] == 1
    assert kb.vector_store.nodes == []


def test_ingest_visual_card_bundles_reports_missing_linked_image(tmp_path: Path) -> None:
    item = bundle(tmp_path)
    kb = FakeKB()

    result = ingest_visual_card_bundles(
        kb,
        [item],
        manifest_run_dir=tmp_path / "run",
        run_id="card-ingest-test",
        source_run_id="visual-gemini-batch100",
    )

    assert result["summary"]["missing_linked_image"] == 1
    assert kb.vector_store.nodes == []
