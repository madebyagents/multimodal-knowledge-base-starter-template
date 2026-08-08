"""FastAPI app entry point.

Single-port deployment: in dev, Vite proxies /api → :8000.
In prod, the Vite build is mounted at / via StaticFiles.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .deps import get_kb_gateway, get_knowledge_hub_client, get_settings
from .routes import chat, chat_state, graph, ingest, knowledge_hub, library, preview, search, vault_index

logger = logging.getLogger("kb")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    get_kb_gateway()  # fail fast if configured KB backend is invalid/broken
    logger.info("Knowledge Base ready.")
    try:
        yield
    finally:
        try:
            get_knowledge_hub_client().close()
        finally:
            get_knowledge_hub_client.cache_clear()
            get_kb_gateway.cache_clear()


app = FastAPI(
    title="Multimodal Knowledge Base",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method, request.url.path, response.status_code, dt_ms,
    )
    return response


# CORS only if explicitly configured (same-origin prod deploys don't need it).
# Parse CORS_ORIGINS directly so we don't have to instantiate Settings at
# import time (which would crash without provider keys); lifespan still
# surfaces that error cleanly when the app actually starts.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# /api routers — register BEFORE the static mount so they always win.
app.include_router(ingest.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(chat_state.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(vault_index.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(knowledge_hub.router, prefix="/api")


# Static SPA mount for prod. In dev this directory doesn't exist, so we skip.
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
    logger.info("Mounted SPA from %s", _static_dir)
