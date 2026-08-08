from __future__ import annotations

import base64

import httpx
import pytest

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


def item_payload(
    *,
    file_id: str = "img-a",
    modality: str = "image",
    preview_url: str | None = "/api/preview/img-a",
    metadata: dict | None = None,
) -> dict:
    return {
        "file_id": file_id,
        "original_name": "A",
        "modality": modality,
        "upload_time": "2026-06-14T00:00:00",
        "node_ids": ["node-a"],
        "preview_url": preview_url,
        "metadata": {"id": file_id, "modality": modality, **(metadata or {})},
        "nodes": [],
    }


def test_preview_url_mode_returns_absolute_local_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/items/lookup"
        assert request.url.params["file_id"] == "img-a"
        return httpx.Response(200, json=item_payload())

    client = make_client(handler)

    result = client.preview(file_id="img-a")

    assert result["ok"] is True
    assert result["mode"] == "url"
    assert result["preview_url"] == "http://sidecar.test/api/preview/img-a"
    assert "base64" not in result


def test_preview_base64_mode_returns_capped_image_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/items/lookup":
            return httpx.Response(200, json=item_payload())
        if request.url.path == "/api/preview/img-a":
            return httpx.Response(200, content=b"jpg", headers={"content-type": "image/jpeg"})
        raise AssertionError(request.url.path)

    client = make_client(handler)

    result = client.preview(file_id="img-a", mode="base64")

    assert result["ok"] is True
    assert result["media_type"] == "image/jpeg"
    assert result["byte_count"] == 3
    assert result["base64"] == base64.b64encode(b"jpg").decode("ascii")


def test_preview_base64_allows_text_visual_bundle_linked_to_image() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/items/lookup":
            return httpx.Response(
                200,
                json=item_payload(
                    file_id="card-a",
                    modality="text",
                    preview_url="/api/preview/img-a",
                    metadata={"preview_image_file_id": "img-a"},
                ),
            )
        if request.url.path == "/api/preview/img-a":
            return httpx.Response(200, content=b"jpg", headers={"content-type": "image/jpeg"})
        raise AssertionError(request.url.path)

    client = make_client(handler)

    result = client.preview(file_id="card-a", mode="base64")

    assert result["ok"] is True
    assert result["preview_url"] == "http://sidecar.test/api/preview/img-a"


def test_preview_base64_rejects_non_image_backed_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=item_payload(
                file_id="pdf-a",
                modality="pdf",
                preview_url="/api/preview/pdf-a/pdf-page/1",
            ),
        )

    client = make_client(handler)

    with pytest.raises(SidecarError, match="image-backed"):
        client.preview(file_id="pdf-a", mode="base64")


def test_preview_base64_refuses_oversized_payload_by_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/items/lookup":
            return httpx.Response(200, json=item_payload())
        if request.url.path == "/api/preview/img-a":
            return httpx.Response(
                200,
                content=b"too large",
                headers={"content-type": "image/jpeg", "content-length": "9"},
            )
        raise AssertionError(request.url.path)

    client = make_client(handler, preview_max_bytes=4)

    with pytest.raises(SidecarError, match="exceeds cap"):
        client.preview(file_id="img-a", mode="base64")


def test_preview_missing_item_surfaces_not_found() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "No item with file_id=missing"})

    client = make_client(handler)

    with pytest.raises(SidecarError, match="HTTP 404"):
        client.preview(file_id="missing")
