from __future__ import annotations

import pytest

from app.kb import SearchResult
from app.kb_backends import KbBackendUnavailable, KbWriteDisabled, KnowledgeHubKbBackend
from app.kb_gateway import KbGateway


class FakeBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []
        self.cleared = False
        self.calls: list[str] = []
        self.kb = object()

    def count(self) -> int:
        self.calls.append("count")
        if self.fail:
            raise KbBackendUnavailable("unavailable")
        return 7

    def count_by_modality(self) -> dict[str, int]:
        self.calls.append("count_by_modality")
        if self.fail:
            raise KbBackendUnavailable("unavailable")
        return {"image": 3, "text": 4}

    def search_text(self, query: str, **_kwargs):
        self.calls.append(f"search_text:{query}")
        if self.fail:
            raise KbBackendUnavailable("unavailable")
        return [
            SearchResult(
                node_id="node-a",
                score=0.9,
                modality="text",
                metadata={"id": "file-a", "original_name": "A", "modality": "text"},
                snippet="alpha",
            )
        ]

    def search_image(self, image_path, **_kwargs):
        self.calls.append(f"search_image:{image_path}")
        if self.fail:
            raise KbBackendUnavailable("unavailable")
        return [
            SearchResult(
                node_id="image-node-a",
                score=0.91,
                modality="image",
                metadata={"id": "image-file-a", "original_name": "Image A", "modality": "image"},
                snippet="visual alpha",
            )
        ]

    def delete_by_file_id(self, file_id: str) -> int:
        self.deleted.append(file_id)
        return 1

    def clear(self) -> None:
        self.cleared = True


class FakeKnowledgeHubClient:
    def __init__(self) -> None:
        self.image_queries: list[tuple[str, int]] = []

    def dantedash_search_packages(self, _payload):
        return {
            "ok": True,
            "data": {
                "items": [
                    {
                        "node_id": "kh-a",
                        "title": "A",
                        "excerpt": "alpha",
                        "score": 0.9,
                        "metadata": {"id": "kh-a", "source_sha256": "sha-a", "file_path": "/Users/a/secret"},
                    },
                    {"id": "kh-b", "title": "B", "snippet": "beta", "score": 0.8},
                    {"id": "kh-c", "title": "C", "snippet": "gamma", "score": 0.7},
                ]
            },
        }

    def dantedash_search_packages_by_image(self, image_path, *, top_k=5):
        self.image_queries.append((str(image_path), top_k))
        return {
            "ok": True,
            "data": {
                "items": [
                    {
                        "node_id": "kh-image-a",
                        "title": "Image A",
                        "excerpt": "visual alpha",
                        "score": 0.91,
                        "metadata": {
                            "id": "kh-image-a",
                            "source_sha256": "sha-image-a",
                            "modality": "image",
                            "file_path": "/Users/vidigal/private-image.jpg",
                        },
                    },
                    {
                        "node_id": "kh-text-a",
                        "title": "Text A",
                        "excerpt": "text alpha",
                        "score": 0.7,
                        "metadata": {"id": "kh-text-a", "modality": "text"},
                    },
                ]
            },
        }

    def dantedash_package_stats(self):
        return {"ok": True, "data": {"total": 3, "by_modality": {"image": 1, "text": 2}}}

    def dantedash_package_items(self, *, limit=None, offset=0):
        del limit, offset
        return {"ok": True, "data": {"items": [{"file_id": "kh-a", "original_name": "A"}], "total": 1}}

    def dantedash_package_item(self, item_id, *, include_private=False):
        metadata = {"id": item_id, "source_sha256": "sha-a", "modality": "image", "original_name": "A"}
        if include_private:
            metadata["file_path"] = "/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets/a.jpg"
        return {
            "ok": True,
            "data": {
                "file_id": item_id,
                "original_name": "A",
                "modality": "image",
                "upload_time": "",
                "node_ids": [item_id],
                "metadata": metadata,
                "nodes": [{"node_id": item_id, "metadata": metadata, "snippet": "alpha"}],
            },
        }


class FailingImageQueryKnowledgeHubClient(FakeKnowledgeHubClient):
    def dantedash_search_packages_by_image(self, image_path, *, top_k=5):
        del image_path, top_k
        return {"ok": False, "error": "service_unavailable"}


class UnavailableStatusKnowledgeHubClient(FakeKnowledgeHubClient):
    def dantedash_search_packages(self, _payload):
        return {"ok": True, "data": {"status": "unavailable", "items": []}}

    def dantedash_search_packages_by_image(self, image_path, *, top_k=5):
        del image_path, top_k
        return {
            "ok": True,
            "data": {
                "status": "unavailable",
                "items": [],
                "visual_retrieval": {"status": "embedder_unavailable"},
            },
        }


class FlakyImageQueryKnowledgeHubClient(FakeKnowledgeHubClient):
    def __init__(self) -> None:
        super().__init__()
        self._failed_once = False

    def dantedash_search_packages_by_image(self, image_path, *, top_k=5):
        if not self._failed_once:
            self._failed_once = True
            self.image_queries.append((str(image_path), top_k))
            return {
                "ok": True,
                "data": {
                    "status": "unavailable",
                    "items": [],
                    "visual_retrieval": {"status": "embed_image_query_failed"},
                },
            }
        return super().dantedash_search_packages_by_image(image_path, top_k=top_k)


def test_invalid_gateway_mode_fails_closed() -> None:
    with pytest.raises(ValueError, match="Invalid DANTEDASH_KB_BACKEND"):
        KbGateway(mode="typo", chroma=FakeBackend(), knowledge_hub=FakeBackend())


def test_chroma_mode_uses_chroma_backend() -> None:
    chroma = FakeBackend()
    kh = FakeBackend(fail=True)
    gateway = KbGateway(mode="chroma", chroma=chroma, knowledge_hub=kh)

    assert gateway.count() == 7
    assert gateway.count_by_modality() == {"image": 3, "text": 4}
    assert gateway.search_text("corridor")[0].node_id == "node-a"
    assert kh.calls == []


def test_dual_mode_serves_chroma_and_shadows_kh() -> None:
    chroma = FakeBackend()
    kh = FakeBackend(fail=True)
    gateway = KbGateway(mode="dual", chroma=chroma, knowledge_hub=kh)

    assert gateway.search_text("aftersun")[0].metadata["id"] == "file-a"
    assert chroma.calls == ["search_text:aftersun"]
    assert kh.calls == ["search_text:aftersun"]


def test_knowledge_hub_mode_falls_back_to_chroma_when_enabled() -> None:
    chroma = FakeBackend()
    kh = FakeBackend(fail=True)
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=kh,
        chroma_fallback_enabled=True,
    )

    assert gateway.count() == 7
    assert chroma.calls == ["count"]
    assert kh.calls == ["count"]


def test_knowledge_hub_mode_serves_text_from_kh_without_chroma() -> None:
    chroma = FakeBackend()
    kh = FakeBackend()
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=kh,
        chroma_fallback_enabled=True,
    )

    assert gateway.search_text("barry lyndon")[0].metadata["id"] == "file-a"
    assert kh.calls == ["search_text:barry lyndon"]
    assert chroma.calls == []


def test_knowledge_hub_mode_serves_image_query_from_kh_without_chroma() -> None:
    chroma = FakeBackend()
    client = FakeKnowledgeHubClient()
    kh = KnowledgeHubKbBackend(client)
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=kh,
        chroma_fallback_enabled=False,
    )

    assert gateway.search_image("/tmp/query.jpg")[0].node_id == "kh-image-a"
    assert client.image_queries == [("/tmp/query.jpg", 5)]
    assert chroma.calls == []


def test_knowledge_hub_image_query_retries_transient_unavailable_status() -> None:
    client = FlakyImageQueryKnowledgeHubClient()
    kh = KnowledgeHubKbBackend(client)

    assert kh.search_image("/tmp/query.jpg")[0].node_id == "kh-image-a"
    assert client.image_queries == [("/tmp/query.jpg", 5), ("/tmp/query.jpg", 5)]


def test_knowledge_hub_mode_falls_back_to_chroma_for_image_query_when_enabled() -> None:
    chroma = FakeBackend()
    kh = KnowledgeHubKbBackend(FailingImageQueryKnowledgeHubClient())
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=kh,
        chroma_fallback_enabled=True,
    )

    assert gateway.search_image("/tmp/query.jpg")[0].node_id == "image-node-a"
    assert chroma.calls == ["search_image:/tmp/query.jpg"]


def test_knowledge_hub_mode_falls_back_when_kh_returns_unavailable_status() -> None:
    chroma = FakeBackend()
    kh = KnowledgeHubKbBackend(UnavailableStatusKnowledgeHubClient())
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=kh,
        chroma_fallback_enabled=True,
    )

    assert gateway.search_text("aftersun")[0].node_id == "node-a"
    assert gateway.search_image("/tmp/query.jpg")[0].node_id == "image-node-a"
    assert chroma.calls == ["search_text:aftersun", "search_image:/tmp/query.jpg"]


def test_knowledge_hub_mode_raises_when_unavailable_status_and_fallback_disabled() -> None:
    kh = KnowledgeHubKbBackend(UnavailableStatusKnowledgeHubClient())
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=FakeBackend(),
        knowledge_hub=kh,
        chroma_fallback_enabled=False,
    )

    with pytest.raises(KbBackendUnavailable):
        gateway.search_text("aftersun")
    with pytest.raises(KbBackendUnavailable):
        gateway.search_image("/tmp/query.jpg")


def test_knowledge_hub_mode_raises_for_image_query_when_fallback_disabled() -> None:
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=FakeBackend(),
        knowledge_hub=KnowledgeHubKbBackend(FailingImageQueryKnowledgeHubClient()),
        chroma_fallback_enabled=False,
    )

    with pytest.raises(KbBackendUnavailable):
        gateway.search_image("/tmp/query.jpg")


def test_knowledge_hub_mode_does_not_construct_chroma_until_needed() -> None:
    calls: list[str] = []

    def chroma_factory():
        calls.append("constructed")
        return FakeBackend()

    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma_factory,
        knowledge_hub=KnowledgeHubKbBackend(FakeKnowledgeHubClient()),
        chroma_fallback_enabled=False,
    )

    assert gateway.count() == 3
    assert gateway.search_text("barry")[0].node_id == "kh-a"
    assert calls == []


def test_gateway_status_is_public_safe_for_knowledge_hub_primary() -> None:
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=FakeBackend(),
        knowledge_hub=FakeBackend(),
        chroma_fallback_enabled=True,
    )

    status = gateway.status()

    assert status == {
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


@pytest.mark.parametrize(
    ("mode", "fallback_enabled", "expected"),
    [
        (
            "chroma",
            True,
            {
                "primary_backend": "chroma",
                "shadow_backend": None,
                "chroma_available_as_fallback": False,
                "writes_enabled": True,
                "image_query_search": "chroma",
            },
        ),
        (
            "dual",
            True,
            {
                "primary_backend": "chroma",
                "shadow_backend": "knowledge_hub",
                "chroma_available_as_fallback": False,
                "writes_enabled": True,
                "image_query_search": "chroma",
            },
        ),
        (
            "knowledge_hub",
            False,
            {
                "primary_backend": "knowledge_hub",
                "shadow_backend": None,
                "chroma_available_as_fallback": False,
                "writes_enabled": False,
                "image_query_search": "knowledge_hub",
            },
        ),
    ],
)
def test_gateway_status_modes(mode: str, fallback_enabled: bool, expected: dict[str, object]) -> None:
    gateway = KbGateway(
        mode=mode,
        chroma=FakeBackend(),
        knowledge_hub=FakeBackend(),
        chroma_fallback_enabled=fallback_enabled,
    )

    status = gateway.status()

    assert status["mode"] == mode
    assert status["primary_backend"] == expected["primary_backend"]
    assert status["shadow_backend"] == expected["shadow_backend"]
    assert status["chroma_available_as_fallback"] is expected["chroma_available_as_fallback"]
    assert status["writes_enabled"] is expected["writes_enabled"]
    assert status["surfaces"]["image_query_search"] == expected["image_query_search"]


def test_knowledge_hub_mode_raises_when_fallback_disabled() -> None:
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=FakeBackend(),
        knowledge_hub=FakeBackend(fail=True),
        chroma_fallback_enabled=False,
    )

    with pytest.raises(KbBackendUnavailable):
        gateway.count()


def test_knowledge_hub_mode_disables_writes() -> None:
    chroma = FakeBackend()
    gateway = KbGateway(
        mode="knowledge_hub",
        chroma=chroma,
        knowledge_hub=FakeBackend(),
    )

    with pytest.raises(KbWriteDisabled):
        gateway.delete_by_file_id("file-a")
    with pytest.raises(KbWriteDisabled):
        gateway.clear()
    assert chroma.deleted == []
    assert chroma.cleared is False


def test_knowledge_hub_backend_bounds_search_results_to_top_k() -> None:
    backend = KnowledgeHubKbBackend(FakeKnowledgeHubClient())

    results = backend.search_text("corridor", top_k=2)

    assert [result.node_id for result in results] == ["kh-a", "kh-b"]
    assert "file_path" not in results[0].metadata
    assert results[0].metadata["source_sha256"] == "sha-a"

    image_results = backend.search_image("/tmp/query.jpg", top_k=1)
    assert [result.node_id for result in image_results] == ["kh-image-a"]
    assert "file_path" not in image_results[0].metadata
    assert image_results[0].metadata["source_sha256"] == "sha-image-a"

    filtered_results = backend.search_image("/tmp/query.jpg", top_k=2, modality_filter=["image"])
    assert [result.node_id for result in filtered_results] == ["kh-image-a"]


def test_knowledge_hub_backend_serves_official_stats_and_listing() -> None:
    backend = KnowledgeHubKbBackend(FakeKnowledgeHubClient())

    assert backend.count() == 3
    assert backend.count_by_modality() == {"image": 1, "text": 2}
    items, total = backend.list_items()

    assert total == 1
    assert items[0]["file_id"] == "kh-a"
    assert backend.get_item(file_id="kh-a")["metadata"]["source_sha256"] == "sha-a"
