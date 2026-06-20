"""Pydantic request/response models for the API layer."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .chat_models import CHAT_MODEL_DEEPSEEK, ChatModelId
from .knowledge_hub_client import sanitize_public_payload

if TYPE_CHECKING:
    from .kb import SearchResult


class SearchResultDTO(BaseModel):
    node_id: str
    score: float
    modality: str
    display_name: str
    file_id: str
    metadata: dict[str, Any]
    snippet: str = ""
    preview_url: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultDTO]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    modality_filter: list[str] | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    modality_filter: list[str] | None = None
    max_images: int = Field(default=6, ge=0, le=20)
    chat_model: ChatModelId = CHAT_MODEL_DEEPSEEK
    project_id: str | None = None
    thread_id: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(default="Dante", min_length=1, max_length=120)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    memory: str | None = None
    instructions: str | None = None


class ProjectDTO(BaseModel):
    id: str
    name: str
    memory: str
    instructions: str
    created_at: str
    updated_at: str
    thread_count: int = 0
    latest_thread_at: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[ProjectDTO]


class ThreadCreateRequest(BaseModel):
    project_id: str
    title: str | None = Field(default=None, max_length=160)
    chat_model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)


class ThreadUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = None
    chat_model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    archived: bool | None = None
    pinned: bool | None = None


class ThreadDTO(BaseModel):
    id: str
    project_id: str
    title: str
    summary: str
    chat_model: str | None = None
    top_k: int | None = None
    archived: bool = False
    pinned: bool = False
    created_at: str
    updated_at: str
    message_count: int = 0


class ThreadsResponse(BaseModel):
    threads: list[ThreadDTO]


class ChatMessageDTO(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    chat_model: str | None = None
    top_k: int | None = None
    status: str = "complete"
    visual_attachments: int = 0
    citation_validation: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    sources: list[SearchResultDTO] = Field(default_factory=list)


class ThreadDetailResponse(ThreadDTO):
    project: ProjectDTO
    messages: list[ChatMessageDTO]


class WorkspaceBootstrapResponse(BaseModel):
    project: ProjectDTO
    thread: ThreadDTO


class IngestItemDTO(BaseModel):
    file_id: str
    original_name: str
    modality: str
    node_ids: list[str]
    total_pages: int | None = None
    duration_seconds: float | None = None
    preview_url: str | None = None


class IngestResponse(BaseModel):
    items: list[IngestItemDTO]
    total: int


class ItemDTO(BaseModel):
    file_id: str
    original_name: str
    modality: str
    upload_time: str
    node_ids: list[str]
    preview_url: str | None = None


class ItemsResponse(BaseModel):
    items: list[ItemDTO]
    total: int
    returned: int
    limit: int | None = None
    offset: int = 0


class ItemNodeDTO(BaseModel):
    node_id: str
    snippet: str = ""
    metadata: dict[str, Any]


class ItemDetailResponse(BaseModel):
    file_id: str
    original_name: str
    modality: str
    upload_time: str
    node_ids: list[str]
    preview_url: str | None = None
    matched_node_id: str | None = None
    metadata: dict[str, Any]
    nodes: list[ItemNodeDTO]


class StatsResponse(BaseModel):
    total: int
    by_modality: dict[str, int]


class KbStatusResponse(BaseModel):
    mode: str
    primary_backend: str
    shadow_backend: str | None = None
    chroma_fallback_enabled: bool
    chroma_available_as_fallback: bool
    writes_enabled: bool
    surfaces: dict[str, str]


class DeleteResponse(BaseModel):
    deleted: int


class ClearResponse(BaseModel):
    cleared: bool


def search_result_to_dto(r: SearchResult) -> SearchResultDTO:
    """Convert an internal SearchResult into the wire-format DTO, stripping
    server-side fields (e.g. on-disk file_path) from metadata."""
    meta = safe_metadata(r.metadata)
    return SearchResultDTO(
        node_id=r.node_id,
        score=r.score,
        modality=r.modality,
        display_name=r.display_name,
        file_id=r.metadata.get("id", ""),
        metadata=meta,
        snippet=r.snippet,
        preview_url=preview_url_for(r.metadata),
    )


def project_to_dto(project: dict[str, Any]) -> ProjectDTO:
    return ProjectDTO(**project)


def thread_to_dto(thread: dict[str, Any]) -> ThreadDTO:
    return ThreadDTO(**thread)


def persisted_message_to_dto(message: dict[str, Any]) -> ChatMessageDTO:
    sources = []
    for source in message.get("sources") or []:
        payload = source.get("payload") if isinstance(source, dict) else None
        if isinstance(payload, dict):
            sources.append(SearchResultDTO(**payload))
    return ChatMessageDTO(
        id=message["id"],
        thread_id=message["thread_id"],
        role=message["role"],
        content=message["content"],
        chat_model=message.get("chat_model"),
        top_k=message.get("top_k"),
        status=message.get("status", "complete"),
        visual_attachments=message.get("visual_attachments", 0),
        citation_validation=message.get("citation_validation"),
        created_at=message["created_at"],
        updated_at=message["updated_at"],
        sources=sources,
    )


def thread_detail_to_dto(detail: dict[str, Any]) -> ThreadDetailResponse:
    thread = thread_to_dto(detail)
    return ThreadDetailResponse(
        **thread.model_dump(),
        project=project_to_dto(detail["project"]),
        messages=[persisted_message_to_dto(m) for m in detail.get("messages", [])],
    )


def item_detail_to_dto(item: dict[str, Any]) -> ItemDetailResponse:
    """Convert an internal grouped item lookup into a safe public DTO."""
    meta = dict(item.get("metadata") or {})
    nodes = [
        ItemNodeDTO(
            node_id=node["node_id"],
            snippet=node.get("snippet") or "",
            metadata=safe_metadata(node.get("metadata") or {}),
        )
        for node in item.get("nodes") or []
    ]
    return ItemDetailResponse(
        file_id=item["file_id"],
        original_name=item.get("original_name") or item["file_id"],
        modality=item.get("modality") or "unknown",
        upload_time=item.get("upload_time") or "",
        node_ids=item.get("node_ids") or [node.node_id for node in nodes],
        preview_url=preview_url_for(meta),
        matched_node_id=item.get("matched_node_id"),
        metadata=safe_metadata(meta),
        nodes=nodes,
    )


def safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Strip server-side metadata before returning API payloads."""
    out = sanitize_public_payload(dict(meta))
    return out if isinstance(out, dict) else {}


def preview_url_for(meta: dict[str, Any]) -> str | None:
    """Build a preview URL for a search/library item based on its metadata."""
    preview_image_file_id = meta.get("preview_image_file_id")
    if meta.get("modality") == "text" and preview_image_file_id:
        return f"/api/preview/{preview_image_file_id}"
    file_id = meta.get("id")
    if not file_id:
        return None
    modality = meta.get("modality")
    if modality == "image":
        return f"/api/preview/{file_id}"
    if modality == "pdf":
        page = int(meta.get("page_start") or 1)
        return f"/api/preview/{file_id}/pdf-page/{page}"
    if modality == "video":
        t = meta.get("timestamp_seconds")
        t_val = float(t) if t is not None else 0.0
        return f"/api/preview/{file_id}/video-frame?t={t_val}"
    return None
