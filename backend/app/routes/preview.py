"""GET previews for ingested files (image / pdf-page / video-frame)."""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ..deps import get_kb_gateway
from ..kb import MIME_BY_EXT, load_video_frame_at, render_pdf_page
from ..kb_backends import KbBackendUnavailable, PreviewLookup
from ..kb_gateway import KbGateway

router = APIRouter(tags=["preview"])
logger = logging.getLogger("kb.preview")
DEFAULT_EXTRA_PREVIEW_ROOTS = [
    Path("/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets"),
    Path("/Users/vidigal/Library/CloudStorage/Dropbox/andre/inbox"),
]
EXTRA_PREVIEW_ROOTS = [
    *DEFAULT_EXTRA_PREVIEW_ROOTS,
    *[
        Path(item).expanduser()
        for item in os.getenv("KB_EXTRA_PREVIEW_ROOTS", "").split(":")
        if item.strip()
    ],
]


def _lookup_file(kb: KbGateway, file_id: str, *, timestamp_s: float | None = None) -> PreviewLookup:
    """Locate the on-disk path and any metadata for a given file_id.

    Defensive check: the resolved path must live inside the backend's allowed
    preview roots so corrupted metadata cannot serve arbitrary files.
    """
    try:
        lookup = kb.lookup_preview(file_id, timestamp_s=timestamp_s)
    except KbBackendUnavailable as exc:
        reason = str(exc)
        if reason in {"item_not_found", "preview_file_missing"}:
            raise HTTPException(status_code=404, detail=f"No item with file_id={file_id}") from exc
        raise HTTPException(status_code=503, detail="Knowledge base preview unavailable") from exc
    meta = lookup.metadata
    if not lookup.path:
        raise HTTPException(status_code=404, detail="Item has no file path")
    path = lookup.path.resolve()
    _ensure_allowed_path(lookup.upload_dir, path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="File no longer on disk")
    if lookup.preview_path is not None:
        preview_path = lookup.preview_path.resolve()
        _ensure_allowed_path(lookup.upload_dir, preview_path)
        if not preview_path.exists():
            return PreviewLookup(path=path, metadata=meta, upload_dir=lookup.upload_dir)
        return PreviewLookup(
            path=path,
            metadata=meta,
            upload_dir=lookup.upload_dir,
            preview_path=preview_path,
        )
    return lookup


def _ensure_allowed_path(upload_dir: Path, path: Path) -> None:
    allowed_roots = [upload_dir.resolve(), *[root.resolve() for root in EXTRA_PREVIEW_ROOTS]]
    if not any(path.is_relative_to(root) for root in allowed_roots):
        logger.warning("Refusing to serve %s — outside preview roots %s", path, allowed_roots)
        raise HTTPException(status_code=404, detail="File not available")


def _jpeg_response(img) -> Response:
    buf = io.BytesIO()
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return Response(content=buf.getvalue(), media_type="image/jpeg")


@router.get("/preview/{file_id}")
async def preview_image(file_id: str, kb: KbGateway = Depends(get_kb_gateway)):
    lookup = await run_in_threadpool(_lookup_file, kb, file_id)
    path, meta = lookup.path, lookup.metadata
    if meta.get("modality") != "image":
        raise HTTPException(status_code=400, detail="This file is not an image")
    path = lookup.preview_path or path
    media_type = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
    content = await run_in_threadpool(path.read_bytes)
    return Response(content=content, media_type=media_type)


@router.get("/preview/{file_id}/pdf-page/{page_1based}")
async def preview_pdf_page(file_id: str, page_1based: int, kb: KbGateway = Depends(get_kb_gateway)):
    lookup = await run_in_threadpool(_lookup_file, kb, file_id)
    path, meta = lookup.path, lookup.metadata
    if meta.get("modality") != "pdf":
        raise HTTPException(status_code=400, detail="This file is not a PDF")
    img = await run_in_threadpool(render_pdf_page, path, max(0, page_1based - 1), 1.5)
    return _jpeg_response(img)


@router.get("/preview/{file_id}/video-frame")
async def preview_video_frame(
    file_id: str,
    t: float = Query(default=0.0, ge=0.0),
    kb: KbGateway = Depends(get_kb_gateway),
):
    lookup = await run_in_threadpool(_lookup_file, kb, file_id, timestamp_s=t)
    path, meta = lookup.path, lookup.metadata
    if meta.get("modality") != "video":
        raise HTTPException(status_code=400, detail="This file is not a video")
    if lookup.preview_path is not None:
        content = await run_in_threadpool(lookup.preview_path.read_bytes)
        return Response(content=content, media_type="image/jpeg")
    img = await run_in_threadpool(load_video_frame_at, path, t)
    if img is None:
        raise HTTPException(status_code=404, detail=f"No frame available at t={t}")
    return _jpeg_response(img)
