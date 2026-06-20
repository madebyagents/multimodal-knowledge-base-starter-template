from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.kb import SearchResult
from app.routes import knowledge_hub


class FakeKB:
    def count(self) -> int:
        return 2

    def count_by_modality(self) -> dict[str, int]:
        return {"text": 1, "image": 1}

    def search_text(self, query: str, *, top_k: int, modality_filter=None) -> list[SearchResult]:
        assert query == "liminal corridor"
        assert top_k == 3
        assert modality_filter is None
        return [
            SearchResult(
                node_id="node-a",
                score=0.92,
                modality="text",
                snippet="A fluorescent liminal corridor.",
                metadata={
                    "id": "file-a",
                    "original_name": "Corridor card",
                    "modality": "text",
                    "file_path": "/Users/vidigal/secret.md",
                },
            )
        ]


class FakeClient:
    def __init__(self, *, kh_ok: bool = True) -> None:
        self.kh_ok = kh_ok

    def health(self):
        if not self.kh_ok:
            return {
                "ok": False,
                "surface": "knowledge_hub",
                "status": "unavailable",
                "status_code": None,
                "error": "service_unavailable",
            }
        return {"ok": True, "surface": "knowledge_hub", "status": "available", "data": {"status": "ok"}}

    def topology(self):
        return {
            "ok": True,
            "surface": "knowledge_hub",
            "status": "available",
            "data": {"memory_planes": {"rag_docs": {"storage": "postgres+qdrant"}}},
        }

    def kbs(self):
        return {
            "ok": True,
            "surface": "knowledge_hub",
            "status": "available",
            "data": {"items": [{"kb_slug": "film", "title": "Film"}]},
        }

    def actions_health(self):
        return {"ok": True, "surface": "actions_bridge", "status": "available", "data": {"status": "ok"}}

    def actions_topology(self):
        return {
            "ok": True,
            "surface": "actions_bridge",
            "status": "available",
            "data": {"allowed_paths": ["/health", "/retrieve", "/inbox/bundles"]},
        }

    def actions_openapi_operations(self):
        return {
            "ok": True,
            "surface": "actions_bridge",
            "status": "available",
            "data": {
                "operations": [
                    {"method": "GET", "path": "/health", "operation_id": "health", "summary": ""},
                    {"method": "POST", "path": "/retrieve", "operation_id": "retrieve", "summary": ""},
                ],
                "returned": 2,
            },
        }

    def retrieve(self, payload):
        assert payload["query"] == "liminal corridor"
        return {
            "ok": True,
            "surface": "knowledge_hub",
            "status": "available",
            "data": {
                "mode": "rag",
                "engine_version": "v2",
                "items": [
                    {
                        "id": "kh-a",
                        "title": "KH Corridor",
                        "snippet": "Knowledge Hub corridor hit",
                        "score": 0.81,
                        "kb_slug": "film",
                        "source_path": "/Users/vidigal/private.md",
                    }
                ],
            },
        }


class FakeSettings:
    knowledge_hub_strict_smoke = False
    knowledge_hub_base_url = "http://kh.test"
    knowledge_hub_actions_base_url = "http://actions.test"
    knowledge_hub_actions_bearer_token = None
    knowledge_hub_timeout_s = 4.0


def make_client(fake_client=None) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_hub.router, prefix="/api")
    app.dependency_overrides[knowledge_hub.get_kb_gateway] = lambda: FakeKB()
    app.dependency_overrides[knowledge_hub.get_settings] = lambda: FakeSettings()
    app.dependency_overrides[knowledge_hub.get_knowledge_hub_client] = lambda: fake_client or FakeClient()
    return TestClient(app)


def test_health_aggregates_surfaces_and_allows_partial_kh(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_hub,
        "_graph_status",
        lambda: {"ok": True, "surface": "graph", "status": "available", "data": {"ok": True}},
    )
    monkeypatch.setattr(
        knowledge_hub,
        "_vault_index_status",
        lambda: {"ok": True, "surface": "vault_index", "status": "available", "data": {"ok": True}},
    )

    with make_client(FakeClient(kh_ok=False)) as client:
        response = client.get("/api/knowledge-hub/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["surfaces"]["dantedash_kb"]["data"]["total"] == 2
    assert payload["surfaces"]["knowledge_hub"]["ok"] is False


def test_capabilities_exposes_only_read_only_actions() -> None:
    with make_client() as client:
        response = client.get("/api/knowledge-hub/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mutating_operations_exposed"] is False
    operations = payload["actions_bridge"]["openapi"]["data"]["operations"]
    assert {item["path"] for item in operations} == {"/health", "/retrieve"}
    assert "/inbox/bundles" not in str(payload)


def test_federated_search_groups_multimodal_and_knowledge_hub_results() -> None:
    with make_client() as client:
        response = client.post(
            "/api/knowledge-hub/federated-search",
            json={"query": "liminal corridor", "top_k": 3, "surfaces": ["multimodal", "knowledge_hub"]},
        )

    assert response.status_code == 200
    payload = response.json()
    groups = {group["surface"]: group for group in payload["groups"]}
    assert groups["multimodal"]["results"][0]["title"] == "Corridor card"
    assert groups["multimodal"]["results"][0]["metadata"].get("file_path") is None
    assert groups["knowledge_hub"]["results"][0]["title"] == "KH Corridor"
    assert "source_path" not in groups["knowledge_hub"]["results"][0]["metadata"]


def test_retrieve_proxies_bounded_read_only_payload() -> None:
    with make_client() as client:
        response = client.post(
            "/api/knowledge-hub/retrieve",
            json={"query": "liminal corridor", "mode": "rag", "explain_retrieval": True},
        )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["id"] == "kh-a"


def test_verified_obsidian_uri_only_returns_existing_vault_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Dante"
    existing = vault / "notes" / "exists.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# Exists\n", encoding="utf-8")
    monkeypatch.setenv("DANTE_OBSIDIAN_VAULT_ROOT", str(vault))
    monkeypatch.setenv("DANTE_OBSIDIAN_VAULT_NAME", "Dante")

    assert knowledge_hub._verified_obsidian_uri("notes/exists.md") == (
        "obsidian://open?vault=Dante&file=notes/exists.md"
    )
    assert knowledge_hub._verified_obsidian_uri("notes/missing.md") is None
    assert knowledge_hub._verified_obsidian_uri("../outside.md") is None
