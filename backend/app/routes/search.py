"""POST /api/search, POST /api/search/image."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from ..deps import get_kb_gateway
from ..kb_backends import KbBackendUnavailable
from ..kb_gateway import KbGateway
from ..schemas import SearchRequest, SearchResponse, search_result_to_dto
from ._uploads import upload_to_tempfile

router = APIRouter(tags=["search"])
logger = logging.getLogger("kb.search")


@router.post("/search", response_model=SearchResponse)
async def search_text(req: SearchRequest, kb: KbGateway = Depends(get_kb_gateway)) -> SearchResponse:
    try:
        results = await run_in_threadpool(
            kb.search_text,
            req.query,
            top_k=req.top_k,
            modality_filter=req.modality_filter,
        )
    except KbBackendUnavailable as exc:
        raise HTTPException(status_code=503, detail="Knowledge base backend unavailable") from exc
    logger.info("text-search q=%r top_k=%d → %d hits", req.query, req.top_k, len(results))
    return SearchResponse(results=[search_result_to_dto(r) for r in results])


@router.post("/search/image", response_model=SearchResponse)
async def search_image(
    file: Annotated[UploadFile, File()],
    top_k: Annotated[int, Form()] = 5,
    modality_filter: Annotated[str, Form()] = "",
    kb: KbGateway = Depends(get_kb_gateway),
) -> SearchResponse:
    filters = [m.strip() for m in modality_filter.split(",") if m.strip()] or None
    async with upload_to_tempfile(file, default_suffix=".jpg") as tmp_path:
        try:
            results = await run_in_threadpool(
                kb.search_image, tmp_path, top_k=top_k, modality_filter=filters,
            )
        except KbBackendUnavailable as e:
            raise HTTPException(status_code=503, detail="Knowledge base backend unavailable") from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Image search failed")
            raise HTTPException(status_code=500, detail="Image search failed") from e
    logger.info("image-search file=%s top_k=%d → %d hits", file.filename, top_k, len(results))
    return SearchResponse(results=[search_result_to_dto(r) for r in results])
