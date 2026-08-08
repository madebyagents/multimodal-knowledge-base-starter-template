"""Multimodal Knowledge Base core.

Stack:
    Voyage multimodal embeddings   - one shared vector space for text/images/video
    ChromaDB persistent collection - local vector store
    Cohere rerank                  - optional text-query reranking

Design:
    - Text is chunked locally with LlamaIndex and embedded directly with Voyage.
    - Images and video frames are embedded through Voyage multimodal base64 inputs.
    - PDF pages are rendered to JPEG before embedding because Voyage documents
      text, image, and video inputs for the multimodal endpoint, not raw PDFs.
    - All vectors in this sidecar are 1024-dim by default, matching
      voyage-multimodal-3.5's default output size.
"""
from __future__ import annotations

import io
import logging
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import chromadb
import cv2
import fitz  # PyMuPDF
import httpx
import numpy as np
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores import (
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)
from llama_index.vector_stores.chroma import ChromaVectorStore
from PIL import Image
from pypdf import PdfReader, PdfWriter

from .chat_models import (
    CHAT_MODEL_CLAUDE_OPUS,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_DEEPSEEK,
    ChatModelId,
)
from .providers import (
    ClaudeOAuthChatClient,
    CodexOAuthChatClient,
    CohereReranker,
    DeepSeekChatClient,
    ProviderError,
    VoyageMultimodalEmbedder,
)

# ---------- Configuration ----------

logger = logging.getLogger("kb.core")

EMBED_MODEL = "voyage-multimodal-3.5"
EMBED_DIM = 1024
PDF_PAGES_PER_EMBED = 1          # One vector per page — exact-page citations
MAX_VIDEO_SECONDS_DIRECT = 120   # Above this, sample frames instead
MAX_VIDEO_BYTES_DIRECT = 20 * 1024 * 1024
DEFAULT_VIDEO_FRAME_INTERVAL_S = 5

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
TEXT_EXTS = {".txt", ".md", ".csv", ".log"}
PDF_EXTS = {".pdf"}

# MIME type lookup
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


# ---------- Pipeline event protocol ----------

@dataclass
class PipelineEvent:
    """Emitted during ingestion or search so the UI can show a live trace."""
    stage: str
    detail: str
    progress: float | None = None  # 0..1


ProgressCallback = Callable[[PipelineEvent], None]


def _noop(_event: PipelineEvent) -> None:
    pass


# ---------- Result type ----------

@dataclass
class SearchResult:
    node_id: str
    score: float        # cosine similarity (1 - distance), 0..1
    modality: str
    metadata: dict[str, Any]
    snippet: str = ""

    @property
    def file_path(self) -> Path | None:
        p = self.metadata.get("file_path")
        return Path(p) if p else None

    @property
    def display_name(self) -> str:
        return self.metadata.get("original_name", self.node_id)


# ---------- Knowledge Base ----------

class KnowledgeBase:
    """
    Multimodal KB on top of Voyage multimodal embeddings + Chroma.

    Single instance per process. Cache it with @st.cache_resource in Streamlit.
    """

    def __init__(
        self,
        *,
        voyage_api_key: str,
        deepseek_api_key: str,
        cohere_api_key: str | None = None,
        collection_name: str = "multimodal_kb",
        persist_dir: str | Path = "chroma_db",
        upload_dir: str | Path = "uploads",
        embed_model: str = EMBED_MODEL,
        embed_dim: int = EMBED_DIM,
        deepseek_model: str = "deepseek-v4-pro",
        deepseek_base_url: str = "https://api.deepseek.com",
        codex_bin: str = "codex",
        codex_oauth_model: str = "gpt-5.5",
        codex_oauth_reasoning_effort: str = "xhigh",
        codex_oauth_timeout_s: float = 600.0,
        claude_bin: str = "claude",
        claude_sonnet_model: str = "claude-sonnet-4-6",
        claude_opus_model: str = "claude-opus-4-8",
        claude_haiku_model: str = "claude-haiku-4-5",
        claude_sonnet_effort: str = "medium",
        claude_opus_effort: str = "xhigh",
        claude_haiku_effort: str = "low",
        claude_judge_effort: str = "medium",
        claude_oauth_timeout_s: float = 900.0,
        claude_oauth_premium_timeout_s: float = 1200.0,
        claude_premium_repair_cap: int = 1,
        cohere_rerank_model: str = "rerank-v4.0-pro",
        enable_rerank: bool = True,
    ):
        self.voyage_api_key = voyage_api_key
        self.deepseek_api_key = deepseek_api_key
        self.cohere_api_key = cohere_api_key
        self.collection_name = collection_name
        self.persist_dir = Path(persist_dir)
        self.upload_dir = Path(upload_dir)
        self.embed_model_name = embed_model
        self.embed_dim = embed_dim

        self.persist_dir.mkdir(exist_ok=True, parents=True)
        self.upload_dir.mkdir(exist_ok=True, parents=True)

        # 1. Cloud providers
        self.embedder = VoyageMultimodalEmbedder(
            api_key=voyage_api_key,
            model=embed_model,
            dimension=embed_dim,
        )
        self.chat_client = DeepSeekChatClient(
            api_key=deepseek_api_key,
            model=deepseek_model,
            base_url=deepseek_base_url,
        )
        self.codex_oauth_chat_client = CodexOAuthChatClient(
            codex_bin=codex_bin,
            model=codex_oauth_model,
            reasoning_effort=codex_oauth_reasoning_effort,
            timeout_s=codex_oauth_timeout_s,
        )
        self.claude_sonnet_chat_client = ClaudeOAuthChatClient(
            claude_bin=claude_bin,
            model=claude_sonnet_model,
            effort=claude_sonnet_effort,
            timeout_s=claude_oauth_timeout_s,
        )
        self.claude_opus_chat_client = ClaudeOAuthChatClient(
            claude_bin=claude_bin,
            model=claude_opus_model,
            effort=claude_opus_effort,
            timeout_s=claude_oauth_premium_timeout_s,
        )
        self.claude_haiku_worker_client = ClaudeOAuthChatClient(
            claude_bin=claude_bin,
            model=claude_haiku_model,
            effort=claude_haiku_effort,
            timeout_s=claude_oauth_timeout_s,
        )
        self.claude_sonnet_chief_client = ClaudeOAuthChatClient(
            claude_bin=claude_bin,
            model=claude_sonnet_model,
            effort=claude_sonnet_effort,
            timeout_s=claude_oauth_timeout_s,
        )
        self.claude_opus_judge_client = ClaudeOAuthChatClient(
            claude_bin=claude_bin,
            model=claude_opus_model,
            effort=claude_judge_effort,
            timeout_s=claude_oauth_timeout_s,
        )
        self.claude_premium_repair_cap = max(1, min(int(claude_premium_repair_cap), 2))
        self.reranker = (
            CohereReranker(api_key=cohere_api_key, model=cohere_rerank_model)
            if enable_rerank and cohere_api_key
            else None
        )

        # 2. Chroma persistent client + collection (cosine = best for unit-norm vectors)
        self.chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # 3. LlamaIndex Chroma adapter; embeddings are precomputed by Voyage.
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)
        self.text_splitter = SentenceSplitter(chunk_size=500, chunk_overlap=50)

    def chat_client_for_model(self, chat_model: ChatModelId):
        if chat_model == CHAT_MODEL_DEEPSEEK:
            return self.chat_client
        if chat_model == CHAT_MODEL_CODEX_OAUTH:
            return self.codex_oauth_chat_client
        if chat_model == CHAT_MODEL_CLAUDE_SONNET:
            return self.claude_sonnet_chat_client
        if chat_model == CHAT_MODEL_CLAUDE_OPUS:
            return self.claude_opus_chat_client
        raise ProviderError(f"Unsupported chat model: {chat_model}")

    # ===== Embedding primitives =====

    def _embed_bytes(self, data: bytes, mime_type: str) -> list[float]:
        """Embed one media blob via Voyage multimodal document mode."""
        attempt = 0
        while True:
            try:
                return _l2_normalize(self.embedder.embed_bytes(data, mime_type, input_type="document"))
            except httpx.HTTPError:
                attempt += 1
                if attempt > 3:
                    raise
                time.sleep(min(2**attempt, 20))

    def _embed_text(self, text: str, *, input_type: str) -> list[float]:
        return _l2_normalize(self.embedder.embed_text(text, input_type=input_type))

    def _embed_query_text(self, text: str) -> list[float]:
        """Embed a search query through Voyage query mode."""
        return self._embed_text(text, input_type="query")

    # ===== Ingestion: dispatcher =====

    def ingest_path(
        self,
        path: str | Path,
        *,
        original_name: str | None = None,
        tags: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        copy_to_uploads: bool = True,
        on_progress: ProgressCallback = _noop,
        video_frame_interval_s: int = DEFAULT_VIDEO_FRAME_INTERVAL_S,
    ) -> list[str]:
        """Persist a file under uploads/ and dispatch to the right ingester."""
        src = Path(path)
        ext = src.suffix.lower()
        if not src.exists():
            raise FileNotFoundError(src)

        file_id = uuid.uuid4().hex
        if copy_to_uploads:
            # Copy original into managed uploads dir (so it survives temp cleanup).
            dest = self.upload_dir / f"{file_id}{ext}"
        else:
            dest = src.resolve()
        if copy_to_uploads and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

        base_meta = {
            "id": file_id,
            "original_name": original_name or src.name,
            "file_path": str(dest),
            "managed_upload": copy_to_uploads,
            "upload_time": datetime.now().isoformat(timespec="seconds"),
            "file_size": dest.stat().st_size,
            "tags": ",".join(tags) if tags else "",
        }
        if extra_metadata:
            base_meta.update(extra_metadata)

        on_progress(PipelineEvent("read", f"Loaded {base_meta['original_name']} ({_human_size(base_meta['file_size'])})"))

        if ext in IMAGE_EXTS:
            return [self._ingest_image(dest, base_meta, on_progress)]
        if ext in PDF_EXTS:
            return self._ingest_pdf(dest, base_meta, on_progress)
        if ext in VIDEO_EXTS:
            return self._ingest_video(dest, base_meta, on_progress, video_frame_interval_s)
        if ext in TEXT_EXTS:
            return self._ingest_text_file(dest, base_meta, on_progress)
        raise ValueError(f"Unsupported file type: {ext}")

    # ===== Ingestion: per-modality =====

    def _ingest_image(
        self,
        path: Path,
        base_meta: dict[str, Any],
        on_progress: ProgressCallback,
    ) -> str:
        on_progress(PipelineEvent("embed", "Embedding image with Voyage multimodal..."))
        data, mime = _image_embedding_payload(path)
        vec = self._embed_bytes(data, mime)

        node_id = f"img_{base_meta['id']}"
        node = TextNode(
            id_=node_id,
            text=f"[Image] {base_meta['original_name']}",
            metadata={**base_meta, "modality": "image"},
            embedding=vec,
        )
        on_progress(PipelineEvent("store", "Writing vector to ChromaDB…"))
        self.vector_store.add([node])
        on_progress(PipelineEvent("done", f"Indexed image: {base_meta['original_name']}", 1.0))
        return node_id

    def _ingest_pdf(
        self,
        path: Path,
        base_meta: dict[str, Any],
        on_progress: ProgressCallback,
    ) -> list[str]:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
        base_meta["total_pages"] = total_pages
        on_progress(PipelineEvent("inspect", f"PDF has {total_pages} page(s)"))

        # One vector per page so retrieval pinpoints the exact page.
        on_progress(PipelineEvent(
            "split",
            f"Rendering and embedding {total_pages} page(s) individually for exact-page citations...",
        ))
        ids: list[str] = []
        for page in range(1, total_pages + 1):
            on_progress(PipelineEvent(
                "embed",
                f"Embedding rendered page {page}/{total_pages}...",
                progress=page / max(total_pages, 1),
            ))
            img = render_pdf_page(path, page - 1, zoom=2.0)
            vec = self._embed_bytes(_image_to_jpeg_bytes(img), "image/jpeg")
            node_id = f"pdf_{base_meta['id']}_p{page}"
            node = TextNode(
                id_=node_id,
                text=f"[PDF page image] {base_meta['original_name']} page {page}",
                metadata={
                    **base_meta,
                    "modality": "pdf",
                    "page": page,
                    "page_start": page,
                    "page_end": page,
                },
                embedding=vec,
            )
            self.vector_store.add([node])
            ids.append(node_id)

        on_progress(PipelineEvent(
            "done",
            f"Indexed PDF: {base_meta['original_name']} ({len(ids)} page vector(s))",
            1.0,
        ))
        return ids

    def _ingest_video(
        self,
        path: Path,
        base_meta: dict[str, Any],
        on_progress: ProgressCallback,
        frame_interval_s: int,
    ) -> list[str]:
        duration_s = _video_duration_seconds(path)
        base_meta["duration_seconds"] = round(duration_s, 1)
        on_progress(PipelineEvent("inspect", f"Video duration: {duration_s:.1f}s"))

        # Short MP4: embed the whole video directly. Voyage documents MP4 only.
        can_embed_full_video = (
            path.suffix.lower() == ".mp4"
            and path.stat().st_size <= MAX_VIDEO_BYTES_DIRECT
            and duration_s <= MAX_VIDEO_SECONDS_DIRECT
        )
        if can_embed_full_video:
            try:
                on_progress(PipelineEvent("embed", "Embedding full MP4 with Voyage multimodal..."))
                data = path.read_bytes()
                vec = self._embed_bytes(data, "video/mp4")
                node_id = f"vid_{base_meta['id']}"
                node = TextNode(
                    id_=node_id,
                    text=f"[Video] {base_meta['original_name']} ({duration_s:.1f}s)",
                    metadata={**base_meta, "modality": "video", "frame_index": -1},
                    embedding=vec,
                )
                self.vector_store.add([node])
                on_progress(PipelineEvent("done", f"Indexed video: {base_meta['original_name']}", 1.0))
                return [node_id]
            except (ProviderError, httpx.HTTPError) as exc:
                logger.warning(
                    "Full-video embedding failed for %s; falling back to sampled frames: %s",
                    base_meta["original_name"],
                    exc,
                )

        # Long or non-MP4 video: sample frames every N seconds, embed each as image.
        on_progress(PipelineEvent(
            "split",
            f"Sampling frames every {frame_interval_s}s (~{int(duration_s // frame_interval_s)} frames)...",
        ))
        frames = _sample_video_frames(path, frame_interval_s)
        ids: list[str] = []
        for i, (timestamp_s, frame_bytes) in enumerate(frames, 1):
            on_progress(PipelineEvent(
                "embed",
                f"Frame {i}/{len(frames)} @ {timestamp_s:.1f}s",
                progress=i / max(len(frames), 1),
            ))
            vec = self._embed_bytes(frame_bytes, "image/jpeg")
            node_id = f"vid_{base_meta['id']}_f{i:03d}"
            node = TextNode(
                id_=node_id,
                text=f"[Video frame] {base_meta['original_name']} @ {timestamp_s:.1f}s",
                metadata={
                    **base_meta,
                    "modality": "video",
                    "timestamp_seconds": round(timestamp_s, 2),
                    "frame_index": i,
                },
                embedding=vec,
            )
            self.vector_store.add([node])
            ids.append(node_id)

        on_progress(PipelineEvent("done", f"Indexed video: {base_meta['original_name']} ({len(ids)} frames)", 1.0))
        return ids

    def _ingest_text_file(
        self,
        path: Path,
        base_meta: dict[str, Any],
        on_progress: ProgressCallback,
    ) -> list[str]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        on_progress(PipelineEvent("split", "Chunking text via LlamaIndex SentenceSplitter…"))
        return self.ingest_text(
            text,
            base_meta=base_meta,
            on_progress=on_progress,
        )

    def ingest_text(
        self,
        text: str,
        *,
        base_meta: dict[str, Any] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[str]:
        """Chunk + embed + insert raw text with Voyage document embeddings."""
        meta = dict(base_meta or {})
        meta.setdefault("id", uuid.uuid4().hex)
        meta.setdefault("original_name", meta.get("original_name", "text_snippet"))
        meta.setdefault("upload_time", datetime.now().isoformat(timespec="seconds"))
        meta["modality"] = "text"

        doc = Document(text=text, metadata=meta)
        on_progress(PipelineEvent("split", "Chunking text via LlamaIndex SentenceSplitter..."))
        nodes = self.text_splitter.get_nodes_from_documents([doc])
        for i, node in enumerate(nodes, 1):
            on_progress(PipelineEvent(
                "embed",
                f"Embedding text chunk {i}/{len(nodes)} with Voyage...",
                progress=i / max(len(nodes), 1),
            ))
            node.embedding = self._embed_text(node.get_content(), input_type="document")
        self.vector_store.add(nodes)
        on_progress(PipelineEvent(
            "done",
            f"Indexed text: {meta.get('original_name')} ({len(nodes)} chunks)",
            1.0,
        ))
        return [n.node_id for n in nodes]

    # ===== Retrieval =====

    def search_text(
        self,
        query: str,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        on_progress(PipelineEvent("embed", "Embedding query with Voyage multimodal..."))
        qvec = self._embed_query_text(query)
        return self._query_by_embedding(
            qvec,
            top_k=top_k,
            modality_filter=modality_filter,
            on_progress=on_progress,
            rerank_query=query,
        )

    def search_image(
        self,
        image_path: str | Path,
        *,
        top_k: int = 5,
        modality_filter: list[str] | None = None,
        on_progress: ProgressCallback = _noop,
    ) -> list[SearchResult]:
        path = Path(image_path)
        on_progress(PipelineEvent("embed", "Embedding query image (cross-modal)…"))
        data = path.read_bytes()
        mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
        qvec = self._embed_bytes(data, mime)
        return self._query_by_embedding(qvec, top_k=top_k, modality_filter=modality_filter, on_progress=on_progress)

    def _query_by_embedding(
        self,
        qvec: list[float],
        *,
        top_k: int,
        modality_filter: list[str] | None,
        on_progress: ProgressCallback,
        rerank_query: str | None = None,
    ) -> list[SearchResult]:
        on_progress(PipelineEvent("search", f"Searching {self.count()} vectors…"))

        filters = None
        if modality_filter:
            filters = MetadataFilters(
                filters=[MetadataFilter(key="modality", value=m) for m in modality_filter],
                condition="or",
            )

        q = VectorStoreQuery(
            query_embedding=qvec,
            similarity_top_k=top_k,
            filters=filters,
        )
        result = self.vector_store.query(q)
        out: list[SearchResult] = []
        nodes = result.nodes or []
        sims = result.similarities or [None] * len(nodes)
        for node, sim in zip(nodes, sims):
            score = float(sim) if sim is not None else 0.0
            # Chroma returns cosine distance; LlamaIndex normalizes to similarity for some versions.
            # If we somehow got a distance instead, convert.
            if score < 0:
                score = 1.0 + score
            score = max(0.0, min(1.0, score))
            out.append(SearchResult(
                node_id=node.node_id,
                score=score,
                modality=node.metadata.get("modality", "unknown"),
                metadata=dict(node.metadata),
                snippet=node.get_content() if hasattr(node, "get_content") else "",
            ))

        if rerank_query and self.reranker and out:
            try:
                on_progress(PipelineEvent("rerank", f"Reranking {len(out)} result(s) with Cohere..."))
                out = self.reranker.rerank(
                    rerank_query,
                    out,
                    top_k=top_k,
                    to_document=_rerank_document,
                )
            except ProviderError as exc:
                logger.warning("Cohere rerank failed; returning vector order: %s", exc)

        on_progress(PipelineEvent("done", f"Returned {len(out)} result(s)", 1.0))
        return out

    # ===== Bookkeeping =====

    def count(self) -> int:
        return self.collection.count()

    def count_by_modality(self) -> dict[str, int]:
        """Approximate per-modality count via metadata scan."""
        try:
            data = self.collection.get(include=["metadatas"])
        except Exception:
            return {}
        counts: dict[str, int] = {}
        for meta in data.get("metadatas") or []:
            modality = (meta or {}).get("modality", "unknown")
            counts[modality] = counts.get(modality, 0) + 1
        return counts

    def list_items(self, *, limit: int | None = None, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """List stored items grouped by source file (for the manage view)."""
        data = self.collection.get(include=["metadatas"])
        ids = data.get("ids") or []
        metas = data.get("metadatas") or []
        grouped: dict[str, dict[str, Any]] = {}
        for nid, meta in zip(ids, metas):
            meta = meta or {}
            file_id = meta.get("id", nid)
            entry = grouped.setdefault(file_id, {
                "file_id": file_id,
                "original_name": meta.get("original_name", file_id),
                "file_path": meta.get("file_path"),
                "modality": meta.get("modality", "unknown"),
                "upload_time": meta.get("upload_time", ""),
                "preview_image_file_id": meta.get("preview_image_file_id"),
                "node_ids": [],
            })
            entry["node_ids"].append(nid)
        items = list(grouped.values())
        items.sort(key=lambda item: str(item.get("upload_time", "")), reverse=True)
        total = len(items)
        if offset > 0:
            items = items[offset:]
        if limit is not None:
            items = items[:limit]
        return items, total

    def get_item(
        self,
        *,
        file_id: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one grouped source item by file_id or by one of its node IDs."""
        if bool(file_id) == bool(node_id):
            raise ValueError("Pass exactly one of file_id or node_id")

        matched_node_id: str | None = None
        if node_id:
            seed = self.collection.get(ids=[node_id], include=["metadatas"])
            seed_ids = seed.get("ids") or []
            seed_metas = seed.get("metadatas") or []
            if not seed_ids or not seed_metas:
                return None
            matched_node_id = seed_ids[0]
            file_id = (seed_metas[0] or {}).get("id") or matched_node_id

        assert file_id is not None
        data = self.collection.get(where={"id": file_id}, include=["metadatas", "documents"])
        ids = data.get("ids") or []
        metas = data.get("metadatas") or []
        docs = data.get("documents") or []
        if not ids:
            return None

        first_meta = dict(metas[0] or {})
        nodes = []
        for nid, meta, doc in zip(ids, metas, docs):
            nodes.append(
                {
                    "node_id": nid,
                    "snippet": doc or "",
                    "metadata": dict(meta or {}),
                }
            )

        return {
            "file_id": first_meta.get("id") or file_id,
            "original_name": first_meta.get("original_name") or file_id,
            "modality": first_meta.get("modality", "unknown"),
            "upload_time": first_meta.get("upload_time", ""),
            "node_ids": ids,
            "matched_node_id": matched_node_id,
            "metadata": first_meta,
            "nodes": nodes,
        }

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all chunks/frames for a single source file. Returns count deleted."""
        data = self.collection.get(where={"id": file_id}, include=["metadatas"])
        ids = data.get("ids") or []
        if not ids:
            return 0
        # Best-effort: also remove the original file from disk
        metas = data.get("metadatas") or []
        for meta in metas:
            fp = (meta or {}).get("file_path")
            if fp and (meta or {}).get("managed_upload", True):
                path = Path(fp)
                try:
                    if path.exists() and path.resolve().is_relative_to(self.upload_dir.resolve()):
                        path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not delete managed upload %s", path)
        self.collection.delete(ids=ids)
        return len(ids)

    def clear(self) -> None:
        """Reset the entire KB. Safe; collection is recreated."""
        try:
            self.chroma_client.delete_collection(self.collection_name)
        except Exception:
            pass
        shutil.rmtree(self.upload_dir, ignore_errors=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        # Reinitialize
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)


# ---------- Helpers ----------

def _l2_normalize(vec: list[float] | np.ndarray) -> list[float]:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


def _human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{n} B"


def _image_to_jpeg_bytes(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _image_embedding_payload(path: Path) -> tuple[bytes, str]:
    mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
    if mime in {"image/jpeg", "image/png"}:
        return path.read_bytes(), mime
    with Image.open(path) as img:
        img.seek(0)
        return _image_to_jpeg_bytes(img), "image/jpeg"


def _rerank_document(result: SearchResult) -> str:
    meta = result.metadata
    parts = [
        f"Name: {result.display_name}",
        f"Modality: {result.modality}",
    ]
    if meta.get("page_start"):
        parts.append(f"Page: {meta.get('page_start')}")
    if meta.get("timestamp_seconds") is not None:
        parts.append(f"Timestamp: {meta.get('timestamp_seconds')} seconds")
    if result.snippet:
        parts.append(f"Snippet: {result.snippet[:1200]}")
    return "\n".join(parts)


def _split_pdf(pdf_path: Path, max_pages: int) -> list[tuple[Path, int, int]]:
    """Split a PDF into temp files of <=max_pages each. Returns (path, start_1based, end_1based)."""
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    chunks: list[tuple[Path, int, int]] = []
    for start in range(0, total, max_pages):
        end = min(start + max_pages, total)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        tmp = Path(tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name)
        with open(tmp, "wb") as f:
            writer.write(f)
        chunks.append((tmp, start + 1, end))
    return chunks


def render_pdf_page(pdf_path: Path, page_index_0based: int = 0, zoom: float = 1.5) -> Image.Image:
    """Render a PDF page to a PIL.Image. Used for previews and vision-RAG context."""
    doc = fitz.open(str(pdf_path))
    try:
        idx = max(0, min(page_index_0based, len(doc) - 1))
        page = doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        doc.close()


def _video_duration_seconds(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0:
            return 0.0
        return float(frames) / float(fps)
    finally:
        cap.release()


def _sample_video_frames(path: Path, interval_s: float) -> list[tuple[float, bytes]]:
    """Return [(timestamp_seconds, jpeg_bytes), ...] sampled every interval_s."""
    cap = cv2.VideoCapture(str(path))
    samples: list[tuple[float, bytes]] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0 or total <= 0:
            return samples
        step_frames = max(int(round(fps * interval_s)), 1)
        idx = 0
        while idx < total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                break
            ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok2:
                samples.append((idx / fps, buf.tobytes()))
            idx += step_frames
    finally:
        cap.release()
    return samples


def load_video_frame_at(path: Path, timestamp_s: float) -> Image.Image | None:
    """Load a single frame for preview. Returns PIL.Image or None."""
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        if fps <= 0:
            return None
        frame_idx = int(round(timestamp_s * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)
    finally:
        cap.release()
