from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dante_visual.manifest import VisualAsset
from app.dante_visual.vector_ingest import collect_existing_source_hashes, ingest_visual_vectors, node_id_for


class FakeCollection:
    def __init__(self, metadatas: list[dict[str, Any]] | None = None) -> None:
        self.metadatas = metadatas or []

    def get(self, **_kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return {"metadatas": self.metadatas}


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def embed_many_bytes(self, items: list[tuple[bytes, str]], *, input_type: str) -> list[list[float]]:
        assert input_type == "document"
        self.calls.append(len(items))
        return [[1.0, 2.0, 3.0] for _ in items]


class FakeVectorStore:
    def __init__(self) -> None:
        self.nodes = []

    def add(self, nodes: list[Any]) -> None:
        self.nodes.extend(nodes)


class FakeKB:
    def __init__(self, metadatas: list[dict[str, Any]] | None = None) -> None:
        self.collection = FakeCollection(metadatas)
        self.embedder = FakeEmbedder()
        self.vector_store = FakeVectorStore()


def asset(row: int, sha: str, group: str, index: int, byte_count: int = 3) -> VisualAsset:
    file_name = f"{group}-{index:03d}.jpg"
    return VisualAsset(
        row_number=row,
        image_id=file_name.removesuffix(".jpg"),
        old_relative_path=f"film-stills/{group}/{file_name}",
        new_relative_path=f"film-stills/{group}/{file_name}",
        previous_relative_path=f"film-stills/{group}/{file_name}",
        sha256=sha,
        bytes=byte_count,
        category="film-stills",
        group=group,
        batch_or_note="",
        width=16,
        height=9,
        file_name=file_name,
        file_stem=file_name.removesuffix(".jpg"),
    )


def write_asset(root: Path, item: VisualAsset, content: bytes = b"jpg") -> None:
    path = root / item.new_relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_collect_existing_source_hashes_filters_dante_dataset() -> None:
    kb = FakeKB(
        [
            {"dataset_id": "dante-visual-reference-assets", "source_sha256": "a" * 64},
            {"dataset_id": "other", "source_sha256": "b" * 64},
            {"source_sha256": "c" * 64},
        ]
    )

    assert collect_existing_source_hashes(kb) == {"a" * 64}


def test_ingest_visual_vectors_skips_existing_and_duplicate_hashes(tmp_path: Path) -> None:
    existing_sha = "a" * 64
    new_sha = "b" * 64
    kb = FakeKB([{"dataset_id": "dante-visual-reference-assets", "source_sha256": existing_sha}])
    asset_root = tmp_path / "source-assets"
    assets = [
        asset(2, existing_sha, "aftersun-2022", 1),
        asset(3, new_sha, "aftersun-2022", 2),
        asset(4, new_sha, "aftersun-2022", 3),
    ]
    for item in assets:
        write_asset(asset_root, item)

    result = ingest_visual_vectors(
        kb,
        assets,
        asset_root=asset_root,
        manifest_run_dir=tmp_path / "run",
        run_id="vector-test",
        batch_size=2,
    )

    assert result["summary"]["embedded"] == 1
    assert result["summary"]["skipped_existing"] == 1
    assert result["summary"]["skipped_duplicate_in_run"] == 1
    assert kb.embedder.calls == [1]
    assert len(kb.vector_store.nodes) == 1
    assert kb.vector_store.nodes[0].node_id == node_id_for(assets[1])
    manifest = Path(result["manifest_path"]).read_text()
    assert "skipped_existing" in manifest
    assert "skipped_duplicate_in_run" in manifest
    assert json.loads(Path(result["summary_path"]).read_text())["failed"] == 0
