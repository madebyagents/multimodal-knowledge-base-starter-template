"""Read-only Knowledge Hub cockpit routes."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..deps import Settings, get_kb_gateway, get_knowledge_hub_client, get_settings
from ..kb_gateway import KbGateway
from ..knowledge_hub_client import READ_ONLY_ACTION_PATHS, KnowledgeHubClient, sanitize_public_payload
from ..schemas import search_result_to_dto
from .graph import get_graph_explorer
from .vault_index import get_vault_index

router = APIRouter(prefix="/knowledge-hub", tags=["knowledge-hub"])

FederatedSurface = Literal["multimodal", "vault_index", "graph", "knowledge_hub"]
DEFAULT_OBSIDIAN_VAULT_ROOT = Path("/Users/vidigal/Dante")
DEFAULT_OBSIDIAN_VAULT_NAME = "Dante"


class KnowledgeHubRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    kb_slugs: list[str] | None = None
    mode: Literal["auto", "rag", "cag"] = "auto"
    explain_retrieval: bool = False


class FederatedSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=12)
    surfaces: list[FederatedSurface] = Field(
        default_factory=lambda: ["multimodal", "vault_index", "graph", "knowledge_hub"]
    )
    kb_slugs: list[str] | None = None
    knowledge_hub_mode: Literal["auto", "rag", "cag"] = "auto"


@router.get("/health")
async def health(
    kb: KbGateway = Depends(get_kb_gateway),
    settings: Settings = Depends(get_settings),
    client: KnowledgeHubClient = Depends(get_knowledge_hub_client),
) -> dict[str, Any]:
    dashboard = await run_in_threadpool(_dashboard_kb_status, kb)
    knowledge_hub = await run_in_threadpool(client.health)
    actions_bridge = await run_in_threadpool(_actions_bridge_status, client)
    graph = await run_in_threadpool(_graph_status)
    vault_index = await run_in_threadpool(_vault_index_status)

    surfaces = {
        "dantedash_kb": dashboard,
        "knowledge_hub": knowledge_hub,
        "actions_bridge": actions_bridge,
        "graph": graph,
        "vault_index": vault_index,
    }
    strict_ok = all(surfaces[key].get("ok") for key in ("knowledge_hub", "actions_bridge"))
    return {
        "ok": bool(dashboard.get("ok")) and (strict_ok if settings.knowledge_hub_strict_smoke else True),
        "strict": settings.knowledge_hub_strict_smoke,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "surfaces": surfaces,
    }


@router.get("/capabilities")
async def capabilities(client: KnowledgeHubClient = Depends(get_knowledge_hub_client)) -> dict[str, Any]:
    topology = await run_in_threadpool(client.topology)
    kbs = await run_in_threadpool(client.kbs)
    actions_health = await run_in_threadpool(client.actions_health)
    actions_topology = _read_only_actions_topology(await run_in_threadpool(client.actions_topology))
    actions_openapi = await run_in_threadpool(client.actions_openapi_operations)
    return {
        "ok": any(
            item.get("ok")
            for item in (topology, kbs, actions_health, actions_topology, actions_openapi)
        ),
        "knowledge_hub": {"topology": topology, "kbs": kbs},
        "actions_bridge": {
            "health": actions_health,
            "topology": actions_topology,
            "openapi": actions_openapi,
        },
        "read_only": True,
        "mutating_operations_exposed": False,
    }


@router.post("/retrieve")
async def retrieve(
    request: KnowledgeHubRetrieveRequest,
    client: KnowledgeHubClient = Depends(get_knowledge_hub_client),
) -> dict[str, Any]:
    payload = request.model_dump(exclude_none=True)
    return await run_in_threadpool(client.retrieve, payload)


@router.post("/federated-search")
async def federated_search(
    request: FederatedSearchRequest,
    kb: KbGateway = Depends(get_kb_gateway),
    client: KnowledgeHubClient = Depends(get_knowledge_hub_client),
) -> dict[str, Any]:
    surfaces = _dedupe_surfaces(request.surfaces)
    groups: list[dict[str, Any]] = []
    for surface in surfaces:
        if surface == "multimodal":
            groups.append(await run_in_threadpool(_search_multimodal, kb, request.query, request.top_k))
        elif surface == "vault_index":
            groups.append(await run_in_threadpool(_search_vault_index, request.query, request.top_k))
        elif surface == "graph":
            groups.append(await run_in_threadpool(_search_graph, request.query, request.top_k))
        elif surface == "knowledge_hub":
            payload = {
                "query": request.query,
                "kb_slugs": request.kb_slugs,
                "mode": request.knowledge_hub_mode,
                "explain_retrieval": False,
            }
            groups.append(await run_in_threadpool(_search_knowledge_hub, client, payload))
    return {
        "query": request.query,
        "top_k": request.top_k,
        "groups": groups,
    }


def _dashboard_kb_status(kb: KbGateway) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "surface": "dantedash_kb",
            "status": "available",
            "data": {"total": kb.count(), "by_modality": kb.count_by_modality()},
        }
    except Exception:  # noqa: BLE001
        return {"ok": False, "surface": "dantedash_kb", "status": "unavailable", "error": "kb_unavailable"}


def _actions_bridge_status(client: KnowledgeHubClient) -> dict[str, Any]:
    health = client.actions_health()
    if health.get("ok"):
        return health
    openapi = client.actions_openapi_operations()
    if openapi.get("ok"):
        return {
            "ok": True,
            "surface": "actions_bridge",
            "status": "available",
            "status_code": openapi.get("status_code"),
            "data": {"health": "unavailable", "openapi": openapi.get("data", {})},
        }
    return health


def _read_only_actions_topology(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok") or not isinstance(payload.get("data"), dict):
        return payload
    data = dict(payload["data"])
    if isinstance(data.get("allowed_paths"), list):
        data["allowed_paths"] = [
            path
            for path in data["allowed_paths"]
            if path == "/openapi.json" or path in READ_ONLY_ACTION_PATHS
        ]
    data.pop("write_boundary", None)
    data.pop("inbox_lanes", None)
    data.pop("kb_candidate_namespace", None)
    return {**payload, "data": data}


def _graph_status() -> dict[str, Any]:
    try:
        data = get_graph_explorer().health(load=False)
        return {
            "ok": bool(data.get("ok")),
            "surface": "graph",
            "status": "available" if data.get("ok") else "unavailable",
            "data": sanitize_public_payload(data),
            "error": data.get("error"),
        }
    except Exception:  # noqa: BLE001
        return {"ok": False, "surface": "graph", "status": "unavailable", "error": "graph_unavailable"}


def _vault_index_status() -> dict[str, Any]:
    try:
        data = get_vault_index().health(check_embedding=False)
        return {
            "ok": bool(data.get("ok")),
            "surface": "vault_index",
            "status": "available" if data.get("ok") else "unavailable",
            "data": sanitize_public_payload(data),
            "error": data.get("reason"),
        }
    except Exception:  # noqa: BLE001
        return {
            "ok": False,
            "surface": "vault_index",
            "status": "unavailable",
            "error": "vault_index_unavailable",
        }


def _dedupe_surfaces(surfaces: list[FederatedSurface]) -> list[FederatedSurface]:
    seen: set[str] = set()
    out: list[FederatedSurface] = []
    for surface in surfaces:
        if surface in seen:
            continue
        seen.add(surface)
        out.append(surface)
    return out


def _group(surface: FederatedSurface, *, ok: bool, results: list[dict[str, Any]] | None = None,
           error: str | None = None) -> dict[str, Any]:
    return {
        "surface": surface,
        "ok": ok,
        "returned": len(results or []),
        "results": results or [],
        "error": error,
    }


def _search_multimodal(kb: KbGateway, query: str, top_k: int) -> dict[str, Any]:
    try:
        results = kb.search_text(query, top_k=top_k)
        normalized = []
        for result in results:
            dto = search_result_to_dto(result).model_dump()
            normalized.append(
                {
                    "id": dto["node_id"],
                    "surface": "multimodal",
                    "title": dto["display_name"],
                    "snippet": dto.get("snippet") or "",
                    "score": dto.get("score"),
                    "preview_url": dto.get("preview_url"),
                    "obsidian_uri": None,
                    "metadata": dto.get("metadata") or {},
                    "provenance": {
                        "node_id": dto["node_id"],
                        "file_id": dto.get("file_id"),
                        "modality": dto.get("modality"),
                    },
                }
            )
        return _group("multimodal", ok=True, results=normalized)
    except Exception:  # noqa: BLE001
        return _group("multimodal", ok=False, error="multimodal_search_unavailable")


def _search_vault_index(query: str, top_k: int) -> dict[str, Any]:
    try:
        results = get_vault_index().search(
            query,
            top_k=top_k,
            candidate_k=max(40, top_k * 10),
            use_rerank=True,
            snippet_chars=900,
        )
        normalized = [
            {
                "id": f"{item.rel_path}#chunk-{item.chunk_index}",
                "surface": "vault_index",
                "title": item.rel_path,
                "snippet": item.snippet,
                "score": item.score,
                "preview_url": None,
                "obsidian_uri": _verified_obsidian_uri(item.rel_path),
                "metadata": {
                    "rel_path": item.rel_path,
                    "chunk_index": item.chunk_index,
                    "vector_score": item.vector_score,
                    "rerank_score": item.rerank_score,
                },
                "provenance": {"rel_path": item.rel_path, "chunk_index": item.chunk_index},
            }
            for item in results
        ]
        return _group("vault_index", ok=True, results=normalized)
    except Exception:  # noqa: BLE001
        return _group("vault_index", ok=False, error="vault_index_search_unavailable")


def _search_graph(query: str, top_k: int) -> dict[str, Any]:
    try:
        payload = get_graph_explorer().search(query, limit=top_k)
        results = payload.get("results") or []
        normalized = [
            {
                "id": str(item.get("id") or ""),
                "surface": "graph",
                "title": str(item.get("label") or item.get("id") or ""),
                "snippet": str(item.get("snippet") or item.get("description") or ""),
                "score": item.get("score"),
                "preview_url": None,
                "obsidian_uri": _first_verified_obsidian_uri(item),
                "metadata": {
                    "entity_type": item.get("entity_type"),
                    "routes": item.get("routes") or [],
                    "route_labels": item.get("route_labels") or [],
                    "source_families": item.get("source_families") or [],
                    "degree": item.get("degree"),
                },
                "provenance": {"node_id": item.get("id"), "source": "graph"},
            }
            for item in results
        ]
        return _group("graph", ok=True, results=normalized)
    except Exception:  # noqa: BLE001
        return _group("graph", ok=False, error="graph_search_unavailable")


def _search_knowledge_hub(client: KnowledgeHubClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.retrieve({k: v for k, v in payload.items() if v is not None})
    if not response.get("ok"):
        return _group("knowledge_hub", ok=False, error=str(response.get("error") or "knowledge_hub_unavailable"))
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    items = data.get("items") if isinstance(data, dict) else []
    normalized = [_normalize_knowledge_hub_item(item, data) for item in items if isinstance(item, dict)]
    return _group("knowledge_hub", ok=True, results=normalized)


def _normalize_knowledge_hub_item(item: dict[str, Any], response_data: dict[str, Any]) -> dict[str, Any]:
    title = _first_text(item, "title", "source_title", "document_title", "relative_path", "path", "id") or "Knowledge Hub item"
    snippet = _first_text(item, "snippet", "text", "content", "chunk_text", "summary") or ""
    score = _first_number(item, "score", "rerank_score", "similarity", "vector_score")
    kb_slug = item.get("kb_slug") or item.get("kb") or item.get("collection")
    item_id = _first_text(item, "id", "chunk_id", "document_id", "relative_path", "path") or title
    return {
        "id": item_id,
        "surface": "knowledge_hub",
        "title": title,
        "snippet": snippet,
        "score": score,
        "preview_url": None,
        "obsidian_uri": None,
        "metadata": sanitize_public_payload(item),
        "provenance": {
            "kb_slug": kb_slug,
            "mode": response_data.get("mode"),
            "engine_version": response_data.get("engine_version"),
        },
    }


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


def _first_verified_obsidian_uri(item: dict[str, Any]) -> str | None:
    hints = item.get("obsidian_hints")
    if isinstance(hints, list):
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            uri = _verified_obsidian_uri(hint.get("best_effort_rel_path"))
            if uri:
                return uri
    return None


def _verified_obsidian_uri(rel_path: Any) -> str | None:
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    clean = rel_path.strip().lstrip("/")
    rel = Path(clean)
    if rel.is_absolute() or ".." in rel.parts:
        return None

    vault_root = Path(os.getenv("DANTE_OBSIDIAN_VAULT_ROOT", str(DEFAULT_OBSIDIAN_VAULT_ROOT))).expanduser()
    if not (vault_root / rel).is_file():
        return None

    vault_name = os.getenv("DANTE_OBSIDIAN_VAULT_NAME", DEFAULT_OBSIDIAN_VAULT_NAME)
    return f"obsidian://open?vault={quote(vault_name)}&file={quote(clean)}"
