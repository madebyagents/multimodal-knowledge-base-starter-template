from __future__ import annotations

import json

import httpx
import pytest

from app import mcp_server
from app.mcp_server import DanteMultimodalMcpClient, SidecarError


def make_client(handler, *, preview_max_bytes: int = 32) -> DanteMultimodalMcpClient:
    return DanteMultimodalMcpClient(
        api_base_url="http://sidecar.test",
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://sidecar.test",
        ),
        preview_max_bytes=preview_max_bytes,
    )


def test_stats_returns_sidecar_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/stats"
        return httpx.Response(200, json={"total": 6281, "by_modality": {"image": 2094, "text": 4187}})

    client = make_client(handler)

    assert client.stats() == {
        "ok": True,
        "status": "ok",
        "api_base_url": "http://sidecar.test",
        "total": 6281,
        "by_modality": {"image": 2094, "text": 4187},
    }


def test_search_posts_query_and_normalizes_preview_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/search"
        assert json.loads(request.content) == {
            "query": "jungle dread",
            "top_k": 3,
            "modality_filter": ["text"],
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "node_id": "node-a",
                        "file_id": "file-a",
                        "score": 0.91,
                        "modality": "text",
                        "display_name": "A",
                        "snippet": "match",
                        "preview_url": "/api/preview/image-a",
                        "metadata": {"artifact_type": "visual_analysis_bundle"},
                    }
                ]
            },
        )

    client = make_client(handler)

    result = client.search(query="jungle dread", top_k=3, modality_filter=["text"])

    assert result["ok"] is True
    assert result["returned"] == 1
    assert result["results"][0]["preview_url"] == "http://sidecar.test/api/preview/image-a"


def test_search_rejects_invalid_top_k_before_http() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("HTTP should not be called")

    client = make_client(handler)

    with pytest.raises(SidecarError, match="top_k"):
        client.search(query="x", top_k=51)


def test_chat_aggregates_sse_tokens_and_sources() -> None:
    stream = (
        f"data: {json.dumps('Hello')}\n\n"
        f"data: {json.dumps(' world')}\n\n"
        "event: sources\n"
        'data: {"sources":[{"node_id":"node-a","file_id":"file-a","score":0.8,'
        '"modality":"text","display_name":"A","snippet":"s","preview_url":"/api/preview/img",'
        '"metadata":{}}],"visual_attachments":1}\n\n'
        "event: done\n"
        "data: {}\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})

    client = make_client(handler)

    result = client.chat(question="What mood?", top_k=5)

    assert result["ok"] is True
    assert result["answer"] == "Hello world"
    assert result["visual_attachments"] == 1
    assert result["sources"][0]["preview_url"] == "http://sidecar.test/api/preview/img"


def test_tool_wrapper_returns_structured_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def close(self) -> None:
            self.closed = True

        def search(self, **_kwargs):
            raise SidecarError("sidecar unavailable")

    monkeypatch.setattr(mcp_server, "client_from_env", lambda: FailingClient())

    assert mcp_server.search("anything") == {"ok": False, "error": "sidecar unavailable"}
