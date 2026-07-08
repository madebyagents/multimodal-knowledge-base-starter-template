"""External Dante vault text index routes."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..vault_index import VaultVectorIndex, build_from_env

router = APIRouter(prefix="/vault-index", tags=["vault-index"])


class VaultIndexSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    candidate_k: int = Field(default=80, ge=1, le=500)
    use_rerank: bool = True
    snippet_chars: int = Field(default=900, ge=120, le=4000)


class VaultIndexResultDTO(BaseModel):
    rank: int
    rel_path: str
    obsidian_uri: str
    chunk_index: int
    score: float
    vector_score: float
    rerank_score: float | None = None
    snippet: str


class VaultIndexSearchResponse(BaseModel):
    query: str
    results: list[VaultIndexResultDTO]
    rerank: str


class VaultIndexReindexRequest(BaseModel):
    dry_run: bool = False
    include_generated: bool = False
    include_sensitive: bool = False
    max_file_bytes: int = Field(default=2_500_000, ge=0)
    timeout_s: int = Field(default=3600, ge=30, le=21600)


@lru_cache(maxsize=1)
def get_vault_index() -> VaultVectorIndex:
    return build_from_env()


@router.get("/health")
async def health(check_embedding: bool = False) -> dict[str, Any]:
    return await run_in_threadpool(get_vault_index().health, check_embedding=check_embedding)


@router.get("/inspect")
async def inspect() -> dict[str, Any]:
    return await run_in_threadpool(get_vault_index().inspect)


@router.post("/search", response_model=VaultIndexSearchResponse)
async def search(req: VaultIndexSearchRequest) -> VaultIndexSearchResponse:
    try:
        index = get_vault_index()
        results = await run_in_threadpool(
            index.search,
            req.query,
            top_k=req.top_k,
            candidate_k=req.candidate_k,
            use_rerank=req.use_rerank,
            snippet_chars=req.snippet_chars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    rerank = "cohere" if req.use_rerank and index.cohere_api_key else "none"
    return VaultIndexSearchResponse(
        query=req.query,
        rerank=rerank,
        results=[
            VaultIndexResultDTO(
                rank=item.rank,
                rel_path=item.rel_path,
                obsidian_uri=to_obsidian_uri(item.rel_path),
                chunk_index=item.chunk_index,
                score=item.score,
                vector_score=item.vector_score,
                rerank_score=item.rerank_score,
                snippet=item.snippet,
            )
            for item in results
        ],
    )


@router.post("/reindex")
async def reindex(req: VaultIndexReindexRequest) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            get_vault_index().reindex,
            dry_run=req.dry_run,
            include_generated=req.include_generated,
            include_sensitive=req.include_sensitive,
            max_file_bytes=req.max_file_bytes,
            timeout_s=req.timeout_s,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result)
    return result


def to_obsidian_uri(rel_path: str) -> str:
    from urllib.parse import quote

    return f"obsidian://open?vault=Dante&file={quote(rel_path)}"
