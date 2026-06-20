"""Read-only KB backend adapters for DanteDash.

The first migration step keeps Chroma as the safe implementation while giving
routes a backend-neutral surface. Knowledge Hub support intentionally degrades
when its visual package APIs do not yet satisfy the DanteDash DTO contract.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .kb import KnowledgeBase, ProgressCallback, SearchResult, _noop
from .knowledge_hub_client import KnowledgeHubClient, sanitize_public_payload


class KbBackendUnavailable(RuntimeError):
    """Raised when a selected KB backend cannot serve a read request."""


class KbWriteDisabled(RuntimeError):
    """Raised when a write route is disabled for the selected backend mode."""


@dataclass(frozen=True)
class PreviewLookup:
    path: Path
    metadata: dict[str, Any]
    upload_dir: Path
    preview_path: Path | None = None


class KbBackend(Protocol):
    backend_id: str

    def count(self) -> int: ...

    def count_by_modality(self) -> dict[str, int]: ...

    def search_text(
        self,
        query: str,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]: ...

    def search_image(
        self,
        image_path: str | Path,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]: ...

    def list_items(self, *, limit: int | None = None, offset: int = 0) -> tuple[list[dict[str, Any]], int]: ...

    def get_item(self, *, file_id: str | None = None, node_id: str | None = None) -> dict[str, Any] | None: ...

    def lookup_preview(self, file_id: str, *, timestamp_s: float | None = None) -> PreviewLookup: ...


class ChromaKbBackend:
    backend_id = "chroma"

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def count(self) -> int:
        return self.kb.count()

    def count_by_modality(self) -> dict[str, int]:
        return self.kb.count_by_modality()

    def search_text(
        self,
        query: str,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        return self.kb.search_text(
            query,
            top_k=top_k,
            modality_filter=modality_filter,
            on_progress=on_progress,
        )

    def search_image(
        self,
        image_path: str | Path,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        return self.kb.search_image(
            image_path,
            top_k=top_k,
            modality_filter=modality_filter,
            on_progress=on_progress,
        )

    def list_items(self, *, limit: int | None = None, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        return self.kb.list_items(limit=limit, offset=offset)

    def get_item(self, *, file_id: str | None = None, node_id: str | None = None) -> dict[str, Any] | None:
        return self.kb.get_item(file_id=file_id, node_id=node_id)

    def lookup_preview(self, file_id: str, *, timestamp_s: float | None = None) -> PreviewLookup:
        data = self.kb.collection.get(where={"id": file_id}, include=["metadatas"])
        metas = data.get("metadatas") or []
        if not metas:
            raise KbBackendUnavailable("item_not_found")
        meta = dict(metas[0] or {})
        file_path = meta.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise KbBackendUnavailable("preview_file_missing")
        preview_path = _preview_path_from_meta(meta)
        if meta.get("modality") == "video" and timestamp_s is not None:
            preview_path = self._lookup_video_preview_path(file_id, timestamp_s) or preview_path
        return PreviewLookup(
            path=Path(file_path),
            metadata=meta,
            upload_dir=self.kb.upload_dir,
            preview_path=preview_path,
        )

    def _lookup_video_preview_path(self, file_id: str, timestamp_s: float) -> Path | None:
        data = self.kb.collection.get(where={"id": file_id}, include=["metadatas"])
        candidates: list[tuple[float, dict[str, Any]]] = []
        for meta in data.get("metadatas") or []:
            if not isinstance(meta, dict) or meta.get("modality") != "video":
                continue
            if not _preview_path_from_meta(meta):
                continue
            try:
                distance = abs(float(meta.get("timestamp_seconds") or 0.0) - timestamp_s)
            except (TypeError, ValueError):
                distance = 0.0
            candidates.append((distance, meta))
        if not candidates:
            return None
        _distance, meta = min(candidates, key=lambda item: item[0])
        return _preview_path_from_meta(meta)

    def delete_by_file_id(self, file_id: str) -> int:
        return self.kb.delete_by_file_id(file_id)

    def clear(self) -> None:
        self.kb.clear()


class KnowledgeHubKbBackend:
    backend_id = "knowledge_hub"

    def __init__(self, client: KnowledgeHubClient) -> None:
        self.client = client

    def count(self) -> int:
        data = self._dantedash_stats()
        try:
            return int(data.get("total") or 0)
        except (TypeError, ValueError) as exc:
            raise KbBackendUnavailable("knowledge_hub_stats_malformed") from exc

    def count_by_modality(self) -> dict[str, int]:
        data = self._dantedash_stats()
        by_modality = data.get("by_modality")
        if not isinstance(by_modality, dict):
            raise KbBackendUnavailable("knowledge_hub_stats_malformed")
        counts: dict[str, int] = {}
        for key, value in by_modality.items():
            try:
                counts[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return counts

    def search_text(
        self,
        query: str,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if modality_filter:
            payload["modality_filter"] = modality_filter
        response = self.client.dantedash_search_packages(payload)
        if not response.get("ok"):
            raise KbBackendUnavailable(str(response.get("error") or "knowledge_hub_unavailable"))
        data = _kh_data_or_unavailable(response, "knowledge_hub_search_unavailable")
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise KbBackendUnavailable("knowledge_hub_items_malformed")
        bounded_items = [item for item in items if isinstance(item, dict)][:top_k]
        return [_item_to_result(item, index) for index, item in enumerate(bounded_items)]

    def search_image(
        self,
        image_path: str | Path,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        limit = max(1, min(int(top_k), 50))
        request_top_k = max(1, min(limit * 4 if modality_filter else limit, 50))
        last_error = "knowledge_hub_image_search_unavailable"
        data: dict[str, Any] | None = None
        for attempt in range(2):
            response = self.client.dantedash_search_packages_by_image(image_path, top_k=request_top_k)
            if not response.get("ok"):
                last_error = str(response.get("error") or last_error)
            else:
                try:
                    data = _kh_data_or_unavailable(response, last_error)
                    break
                except KbBackendUnavailable as exc:
                    last_error = str(exc) or last_error
            if attempt == 0:
                time.sleep(0.5)
        if data is None:
            raise KbBackendUnavailable(last_error)
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise KbBackendUnavailable("knowledge_hub_image_items_malformed")
        bounded_items = [item for item in items if isinstance(item, dict)]
        results = [_item_to_result(item, index) for index, item in enumerate(bounded_items)]
        if modality_filter:
            allowed = {str(modality).strip().lower() for modality in modality_filter if str(modality).strip()}
            results = [result for result in results if result.modality.lower() in allowed]
        return results[:limit]

    def list_items(self, *, limit: int | None = None, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        response = self.client.dantedash_package_items(limit=limit, offset=offset)
        if not response.get("ok"):
            raise KbBackendUnavailable(str(response.get("error") or "knowledge_hub_listing_unavailable"))
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise KbBackendUnavailable("knowledge_hub_listing_malformed")
        try:
            total = int(data.get("total") or len(items))
        except (TypeError, ValueError):
            total = len(items)
        return [item for item in items if isinstance(item, dict)], total

    def get_item(self, *, file_id: str | None = None, node_id: str | None = None) -> dict[str, Any] | None:
        item_id = file_id or node_id
        if not item_id:
            return None
        response = self.client.dantedash_package_item(item_id, include_private=False)
        if response.get("status_code") == 404:
            return None
        if not response.get("ok"):
            raise KbBackendUnavailable(str(response.get("error") or "knowledge_hub_item_unavailable"))
        data = response.get("data")
        return dict(data) if isinstance(data, dict) else None

    def lookup_preview(self, file_id: str, *, timestamp_s: float | None = None) -> PreviewLookup:
        del timestamp_s
        item = self._private_dantedash_item(file_id)
        meta = dict(item.get("metadata") or {})
        preview_id = meta.get("preview_image_file_id")
        if isinstance(preview_id, str) and preview_id and preview_id != file_id:
            preview_item = self._private_dantedash_item(preview_id)
            preview_meta = dict(preview_item.get("metadata") or {})
            preview_path = _private_preview_path_from_meta(preview_meta)
            file_path = _private_file_path_from_meta(preview_meta)
            if file_path is not None:
                return PreviewLookup(
                    path=file_path,
                    metadata=preview_meta,
                    upload_dir=_preview_upload_root(file_path),
                    preview_path=preview_path,
                )

        file_path = _private_file_path_from_meta(meta)
        if file_path is None:
            raise KbBackendUnavailable("preview_file_missing")
        return PreviewLookup(
            path=file_path,
            metadata=meta,
            upload_dir=_preview_upload_root(file_path),
            preview_path=_private_preview_path_from_meta(meta),
        )

    def _dantedash_stats(self) -> dict[str, Any]:
        response = self.client.dantedash_package_stats()
        if not response.get("ok"):
            raise KbBackendUnavailable(str(response.get("error") or "knowledge_hub_stats_unavailable"))
        return _kh_data_or_unavailable(response, "knowledge_hub_stats_unavailable")

    def _private_dantedash_item(self, item_id: str) -> dict[str, Any]:
        response = self.client.dantedash_package_item(item_id, include_private=True)
        if response.get("status_code") == 404:
            raise KbBackendUnavailable("item_not_found")
        if not response.get("ok"):
            raise KbBackendUnavailable(str(response.get("error") or "knowledge_hub_preview_unavailable"))
        data = response.get("data")
        if not isinstance(data, dict):
            raise KbBackendUnavailable("knowledge_hub_item_malformed")
        return data


def _item_to_result(item: dict[str, Any], index: int) -> SearchResult:
    nested_meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = sanitize_public_payload({**dict(item), **dict(nested_meta)})
    if not isinstance(metadata, dict):
        metadata = {}
    item_id = _first_text(item, "node_id", "id", "chunk_id", "document_id") or f"kh-item-{index}"
    file_id = _first_text(metadata, "id", "file_id", "document_id") or item_id
    title = _first_text(metadata, "original_name", "display_name", "title", "source_title", "document_title")
    title = title or _first_text(item, "display_name", "title", "source_title", "document_title") or file_id
    modality = _first_text(metadata, "modality", "media_type") or _first_text(item, "modality", "media_type") or "text"
    snippet = _first_text(item, "snippet", "excerpt", "text", "content", "chunk_text", "summary") or ""
    score = _first_number(item, "score", "rerank_score", "similarity", "vector_score")
    metadata.setdefault("id", file_id)
    metadata.setdefault("original_name", title)
    metadata.setdefault("modality", modality)
    return SearchResult(
        node_id=item_id,
        score=score if score is not None else 0.0,
        modality=modality,
        metadata=metadata,
        snippet=snippet,
    )


def _kh_data_or_unavailable(response: dict[str, Any], default_error: str) -> dict[str, Any]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise KbBackendUnavailable(default_error)
    status = str(data.get("status") or "ok").strip().lower()
    if status not in {"ok", "indexed", "dry_run"}:
        raise KbBackendUnavailable(status or default_error)
    return data


def _first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _preview_path_from_meta(meta: dict[str, Any]) -> Path | None:
    preview_file_path = meta.get("preview_file_path")
    if not isinstance(preview_file_path, str) or not preview_file_path:
        return None
    return Path(preview_file_path)


def _private_file_path_from_meta(meta: dict[str, Any]) -> Path | None:
    for key in ("file_path", "preview_file_path", "source_path"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return Path(value)
    return None


def _private_preview_path_from_meta(meta: dict[str, Any]) -> Path | None:
    value = meta.get("preview_file_path")
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _preview_upload_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    known_roots = [
        Path("/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets"),
        Path("/Users/vidigal/Library/CloudStorage/Dropbox/andre/inbox"),
        Path("/Users/vidigal/codex/dantedash/uploads"),
    ]
    for root in known_roots:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return root
    return Path("/Users/vidigal/codex/dantedash/uploads")
