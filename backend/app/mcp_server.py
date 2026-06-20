"""MCP wrapper for the Dante multimodal RAG sidecar."""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable, Iterator
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_API_BASE_URL = "http://127.0.0.1:8035"
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_PREVIEW_MAX_BYTES = 2 * 1024 * 1024
MAX_TOP_K = 50

mcp = FastMCP("dante-multimodal-rag", json_response=True)


class SidecarError(RuntimeError):
    """A concise, MCP-safe sidecar error."""


class DanteMultimodalMcpClient:
    def __init__(
        self,
        *,
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: httpx.Client | None = None,
        preview_max_bytes: int = DEFAULT_PREVIEW_MAX_BYTES,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.preview_max_bytes = preview_max_bytes
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self.api_base_url,
            timeout=timeout_s,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def stats(self) -> dict[str, Any]:
        data = self._request_json("GET", "/api/stats")
        return {
            "ok": True,
            "status": "ok",
            "api_base_url": self.api_base_url,
            "total": data.get("total", 0),
            "by_modality": data.get("by_modality", {}),
        }

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        _validate_query(query)
        _validate_top_k(top_k)
        payload = {
            "query": query,
            "top_k": top_k,
            "modality_filter": _normalize_modality_filter(modality_filter),
        }
        data = self._request_json("POST", "/api/search", json=payload)
        results = [self._normalize_result(row) for row in data.get("results") or []]
        return {
            "ok": True,
            "query": query,
            "top_k": top_k,
            "returned": len(results),
            "results": results,
        }

    def chat(
        self,
        *,
        question: str,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        chat_model: str = "deepseek-v4-pro",
    ) -> dict[str, Any]:
        _validate_query(question)
        _validate_top_k(top_k)
        payload = {
            "question": question,
            "top_k": top_k,
            "modality_filter": _normalize_modality_filter(modality_filter),
            "chat_model": chat_model,
        }
        tokens: list[str] = []
        sources_payload: dict[str, Any] = {"sources": [], "visual_attachments": 0}

        try:
            with self._http.stream(
                "POST",
                "/api/chat",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    text = response.read().decode("utf-8", errors="replace")
                    raise SidecarError(_http_error_message(response.status_code, text))
                for event, data in _iter_sse_events(response.iter_lines()):
                    if event == "message":
                        token = json.loads(data)
                        if isinstance(token, str):
                            tokens.append(token)
                    elif event == "sources":
                        parsed = json.loads(data)
                        if isinstance(parsed, dict):
                            sources_payload = parsed
                    elif event == "error":
                        parsed = json.loads(data)
                        message = parsed.get("message") if isinstance(parsed, dict) else data
                        raise SidecarError(f"Chat stream failed: {message}")
        except httpx.TimeoutException as exc:
            raise SidecarError("Sidecar request timed out") from exc
        except httpx.RequestError as exc:
            raise SidecarError(f"Sidecar request failed: {exc.__class__.__name__}") from exc

        sources = [
            self._normalize_result(row)
            for row in sources_payload.get("sources") or []
        ]
        return {
            "ok": True,
            "provider_status": "ok",
            "answer": "".join(tokens),
            "sources": sources,
            "visual_attachments": int(sources_payload.get("visual_attachments") or 0),
        }

    def get_item(
        self,
        *,
        file_id: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._get_item_data(file_id=file_id, node_id=node_id)
        return {"ok": True, "item": self._normalize_item(data)}

    def preview(self, *, file_id: str, mode: Literal["url", "base64"] = "url") -> dict[str, Any]:
        if not file_id.strip():
            raise SidecarError("file_id is required")
        if mode not in {"url", "base64"}:
            raise SidecarError("mode must be 'url' or 'base64'")

        item = self._normalize_item(self._get_item_data(file_id=file_id, node_id=None))
        preview_url = item.get("preview_url")
        if not preview_url:
            raise SidecarError(f"Item has no preview available: {file_id}")
        absolute_url = self._absolute_url(preview_url)

        if mode == "url":
            return {
                "ok": True,
                "mode": "url",
                "file_id": file_id,
                "preview_url": absolute_url,
                "item": _preview_item_summary(item),
            }

        metadata = item.get("metadata") or {}
        if item.get("modality") != "image" and not metadata.get("preview_image_file_id"):
            raise SidecarError("base64 preview is only supported for image-backed items")

        data, media_type = self._fetch_capped_bytes(absolute_url)
        if not media_type.startswith("image/"):
            raise SidecarError(f"Preview is not an image payload: {media_type}")
        return {
            "ok": True,
            "mode": "base64",
            "file_id": file_id,
            "preview_url": absolute_url,
            "media_type": media_type,
            "byte_count": len(data),
            "base64": base64.b64encode(data).decode("ascii"),
            "item": _preview_item_summary(item),
        }

    def _get_item_data(
        self,
        *,
        file_id: str | None,
        node_id: str | None,
    ) -> dict[str, Any]:
        if bool(file_id) == bool(node_id):
            raise SidecarError("Pass exactly one of file_id or node_id")
        params = {"file_id": file_id} if file_id else {"node_id": node_id}
        return self._request_json("GET", "/api/items/lookup", params=params)

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise SidecarError("Sidecar request timed out") from exc
        except httpx.RequestError as exc:
            raise SidecarError(f"Sidecar request failed: {exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            raise SidecarError(_http_error_message(response.status_code, response.text))
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise SidecarError("Sidecar returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise SidecarError("Sidecar returned an unexpected JSON payload")
        return data

    def _fetch_capped_bytes(self, url: str) -> tuple[bytes, str]:
        try:
            with self._http.stream("GET", url) as response:
                if response.status_code >= 400:
                    text = response.read().decode("utf-8", errors="replace")
                    raise SidecarError(_http_error_message(response.status_code, text))
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.preview_max_bytes:
                    raise SidecarError(
                        f"Preview payload exceeds cap ({content_length} > {self.preview_max_bytes} bytes)"
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.preview_max_bytes:
                        raise SidecarError(
                            f"Preview payload exceeds cap ({total} > {self.preview_max_bytes} bytes)"
                        )
                    chunks.append(chunk)
                media_type = response.headers.get("content-type", "application/octet-stream")
                return b"".join(chunks), media_type.split(";")[0].strip().lower()
        except httpx.TimeoutException as exc:
            raise SidecarError("Sidecar request timed out") from exc
        except httpx.RequestError as exc:
            raise SidecarError(f"Sidecar request failed: {exc.__class__.__name__}") from exc

    def _absolute_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.api_base_url}/{url.lstrip('/')}"

    def _normalize_result(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "node_id": row.get("node_id", ""),
            "file_id": row.get("file_id", ""),
            "score": row.get("score", 0.0),
            "modality": row.get("modality", "unknown"),
            "display_name": row.get("display_name", ""),
            "snippet": row.get("snippet", ""),
            "preview_url": None,
            "metadata": row.get("metadata") or {},
        }
        preview_url = row.get("preview_url")
        if preview_url:
            normalized["preview_url"] = self._absolute_url(str(preview_url))
        return normalized

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        out = dict(item)
        preview_url = out.get("preview_url")
        if preview_url:
            out["preview_url"] = self._absolute_url(str(preview_url))
        return out


def client_from_env() -> DanteMultimodalMcpClient:
    return DanteMultimodalMcpClient(
        api_base_url=os.getenv("DANTE_MULTIMODAL_API_BASE_URL", DEFAULT_API_BASE_URL),
        timeout_s=float(os.getenv("DANTE_MULTIMODAL_API_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
        preview_max_bytes=int(
            os.getenv("DANTE_MULTIMODAL_PREVIEW_MAX_BYTES", str(DEFAULT_PREVIEW_MAX_BYTES))
        ),
    )


def _run_tool(operation: Callable[[DanteMultimodalMcpClient], dict[str, Any]]) -> dict[str, Any]:
    client = client_from_env()
    try:
        return operation(client)
    except SidecarError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        client.close()


@mcp.tool()
def stats() -> dict[str, Any]:
    """Return live Dante multimodal KB status and modality counts."""
    return _run_tool(lambda client: client.stats())


@mcp.tool()
def search(
    query: str,
    top_k: int = 5,
    modality_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Search the Dante multimodal KB with a text query."""
    return _run_tool(
        lambda client: client.search(
            query=query,
            top_k=top_k,
            modality_filter=modality_filter,
        )
    )


@mcp.tool()
def chat(
    question: str,
    top_k: int = 5,
    modality_filter: list[str] | None = None,
    chat_model: str = "deepseek-v4-pro",
) -> dict[str, Any]:
    """Ask a grounded RAG question over the Dante multimodal KB."""
    return _run_tool(
        lambda client: client.chat(
            question=question,
            top_k=top_k,
            modality_filter=modality_filter,
            chat_model=chat_model,
        )
    )


@mcp.tool()
def get_item(file_id: str | None = None, node_id: str | None = None) -> dict[str, Any]:
    """Fetch one Dante multimodal item by file_id or node_id."""
    return _run_tool(lambda client: client.get_item(file_id=file_id, node_id=node_id))


@mcp.tool()
def preview(file_id: str, mode: Literal["url", "base64"] = "url") -> dict[str, Any]:
    """Return an inspectable preview URL or capped base64 image preview."""
    return _run_tool(lambda client: client.preview(file_id=file_id, mode=mode))


def _iter_sse_events(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    event = "message"
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        yield event, "\n".join(data_lines)


def _http_error_message(status_code: int, text: str) -> str:
    detail = text[:300]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        detail = str(parsed.get("detail") or parsed.get("message") or detail)
    return f"Sidecar HTTP {status_code}: {detail}"


def _normalize_modality_filter(modality_filter: list[str] | None) -> list[str] | None:
    if not modality_filter:
        return None
    values = [value.strip() for value in modality_filter if value.strip()]
    return values or None


def _validate_query(value: str) -> None:
    if not value.strip():
        raise SidecarError("query is required")


def _validate_top_k(value: int) -> None:
    if value < 1 or value > MAX_TOP_K:
        raise SidecarError(f"top_k must be between 1 and {MAX_TOP_K}")


def _preview_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_id": item.get("file_id"),
        "original_name": item.get("original_name"),
        "modality": item.get("modality"),
        "preview_url": item.get("preview_url"),
    }


def main() -> None:
    transport = os.getenv("DANTE_MULTIMODAL_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
