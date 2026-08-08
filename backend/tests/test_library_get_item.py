from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.kb import KnowledgeBase
from app.routes.library import get_item, kb_status


class FakeCollection:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("ids") == ["node-a"]:
            return {
                "ids": ["node-a"],
                "metadatas": [{"id": "file-a", "original_name": "A", "modality": "text"}],
            }
        if kwargs.get("where") == {"id": "file-a"}:
            return {
                "ids": ["node-a", "node-b"],
                "metadatas": [
                    {"id": "file-a", "original_name": "A", "modality": "text"},
                    {"id": "file-a", "original_name": "A", "modality": "text"},
                ],
                "documents": ["first snippet", "second snippet"],
            }
        return {"ids": [], "metadatas": [], "documents": []}


def test_kb_get_item_by_file_id_groups_nodes() -> None:
    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb.collection = FakeCollection()

    item = kb.get_item(file_id="file-a")

    assert item is not None
    assert item["file_id"] == "file-a"
    assert item["node_ids"] == ["node-a", "node-b"]
    assert item["nodes"][0]["snippet"] == "first snippet"
    assert kb.collection.calls[0]["where"] == {"id": "file-a"}


def test_kb_get_item_by_node_id_resolves_file_group() -> None:
    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb.collection = FakeCollection()

    item = kb.get_item(node_id="node-a")

    assert item is not None
    assert item["file_id"] == "file-a"
    assert item["matched_node_id"] == "node-a"
    assert kb.collection.calls[0]["ids"] == ["node-a"]
    assert kb.collection.calls[1]["where"] == {"id": "file-a"}


def test_library_get_item_sanitizes_file_paths_and_links_visual_preview() -> None:
    class FakeKB:
        def get_item(self, *, file_id=None, node_id=None):
            assert file_id == "card-a"
            assert node_id is None
            return {
                "file_id": "card-a",
                "original_name": "A visual analysis",
                "modality": "text",
                "upload_time": "2026-06-14T00:00:00",
                "node_ids": ["card-node-a"],
                "metadata": {
                    "id": "card-a",
                    "modality": "text",
                    "file_path": "/private/card.md",
                    "card_json_path": "/Users/vidigal/Dante/card.json",
                    "decoupage_markdown_path": "/Users/vidigal/Dante/decoupage.md",
                    "source_url": "http://internal.local/secret",
                    "preview_image_file_id": "dante_visual_img_a",
                },
                "nodes": [
                    {
                        "node_id": "card-node-a",
                        "snippet": "shot description",
                        "metadata": {
                            "id": "card-a",
                            "modality": "text",
                            "file_path": "/private/card.md",
                            "card_markdown_path": "/Users/vidigal/Dante/card.md",
                        },
                    }
                ],
            }

    response = get_item(file_id="card-a", kb=FakeKB())

    assert response.preview_url == "/api/preview/dante_visual_img_a"
    assert "file_path" not in response.metadata
    assert "card_json_path" not in response.metadata
    assert "decoupage_markdown_path" not in response.metadata
    assert "source_url" not in response.metadata
    assert "file_path" not in response.nodes[0].metadata
    assert "card_markdown_path" not in response.nodes[0].metadata


def test_library_get_item_missing_returns_404() -> None:
    class FakeKB:
        def get_item(self, *, file_id=None, node_id=None):
            return None

    with pytest.raises(HTTPException) as exc:
        get_item(node_id="missing-node", kb=FakeKB())

    assert exc.value.status_code == 404


def test_library_get_item_requires_exactly_one_identifier() -> None:
    class FakeKB:
        def get_item(self, *, file_id=None, node_id=None):  # pragma: no cover
            raise AssertionError("should not call KB")

    with pytest.raises(HTTPException) as exc:
        get_item(file_id="file-a", node_id="node-a", kb=FakeKB())

    assert exc.value.status_code == 400


def test_kb_status_route_returns_public_backend_status() -> None:
    class FakeKB:
        def status(self):
            return {
                "mode": "knowledge_hub",
                "primary_backend": "knowledge_hub",
                "shadow_backend": None,
                "chroma_fallback_enabled": True,
                "chroma_available_as_fallback": True,
                "writes_enabled": False,
                "surfaces": {
                    "text_search": "knowledge_hub",
                    "chat_sources": "knowledge_hub",
                    "stats": "knowledge_hub",
                    "library": "knowledge_hub",
                    "preview": "knowledge_hub",
                    "image_query_search": "knowledge_hub",
                },
            }

    response = kb_status(kb=FakeKB())

    assert response.mode == "knowledge_hub"
    assert response.surfaces["image_query_search"] == "knowledge_hub"
    assert response.writes_enabled is False
