"""POST /api/chat — Server-Sent Events stream of tokens + final sources event."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..chat_store import ChatStore, ChatStoreNotFound
from ..deps import get_chat_store, get_kb_gateway
from ..kb_backends import KbBackendUnavailable
from ..kb_gateway import KbGateway
from ..providers import ProviderError
from ..rag import GroundedAnswer, answer_with_vision
from ..schemas import ChatRequest, search_result_to_dto

router = APIRouter(tags=["chat"])
logger = logging.getLogger("kb.chat")
MAX_CONTEXT_MESSAGES = 8
MAX_SUMMARY_MESSAGES = 10
MAX_CONTEXT_CHARS = 6000
MAX_SUMMARY_CHARS = 2400


def _sse(event: str | None, data: str) -> str:
    """Format a single SSE frame. Empty event name → default 'message'."""
    prefix = f"event: {event}\n" if event else ""
    # Data must be JSON-encoded so newlines/quotes inside tokens are safe.
    return f"{prefix}data: {data}\n\n"


def _stream(kb: KbGateway, req: ChatRequest, store: ChatStore) -> Iterator[str]:
    token_count = 0
    final: GroundedAnswer | None = None
    persisted_user_id: str | None = None
    conversation_context = ""

    if req.thread_id:
        conversation_context = _build_conversation_context(store, req.thread_id)
        persisted_user = store.append_message(
            req.thread_id,
            role="user",
            content=req.question,
            chat_model=req.chat_model,
            top_k=req.top_k,
        )
        persisted_user_id = persisted_user["id"]
        store.update_thread(
            req.thread_id,
            chat_model=req.chat_model,
            top_k=req.top_k,
        )

    try:
        for chunk in answer_with_vision(
            kb,
            req.question,
            top_k=req.top_k,
            modality_filter=req.modality_filter,
            chat_model=req.chat_model,
            max_images=req.max_images,
            conversation_context=conversation_context,
        ):
            if isinstance(chunk, str):
                token_count += 1
                yield _sse(None, json.dumps(chunk))
            else:
                final = chunk
    except ProviderError:
        logger.exception("Chat provider failed")
        yield _sse(
            "error",
            json.dumps({"message": f"Selected chat mode {req.chat_model} is currently unavailable."}),
        )
        yield _sse("done", "{}")
        return
    except KbBackendUnavailable:
        logger.exception("Chat knowledge base backend unavailable")
        yield _sse("error", json.dumps({"message": "Knowledge base backend unavailable."}))
        yield _sse("done", "{}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Chat stream failed")
        yield _sse("error", json.dumps({"message": "Chat failed before a grounded answer could be produced."}))
        yield _sse("done", "{}")
        return

    sources_payload: dict = {"sources": [], "visual_attachments": 0}
    if final is not None:
        sources_payload["visual_attachments"] = final.visual_attachments
        sources_payload["sources"] = [
            search_result_to_dto(r).model_dump() for r in final.sources
        ]
        if final.citation_validation is not None:
            sources_payload["citation_validation"] = final.citation_validation.to_payload()
        if req.thread_id:
            assistant = store.append_message(
                req.thread_id,
                role="assistant",
                content=final.answer,
                chat_model=req.chat_model,
                top_k=req.top_k,
                visual_attachments=final.visual_attachments,
                citation_validation=sources_payload.get("citation_validation"),
            )
            store.save_message_sources(assistant["id"], sources_payload["sources"])
            store.update_thread(
                req.thread_id,
                summary=_summarize_thread(store, req.thread_id),
                chat_model=req.chat_model,
                top_k=req.top_k,
            )

    logger.info(
        "chat q=%r thread=%s user_msg=%s tokens=%d sources=%d visuals=%d",
        req.question, req.thread_id, persisted_user_id, token_count,
        len(sources_payload["sources"]),
        sources_payload["visual_attachments"],
    )
    yield _sse("sources", json.dumps(sources_payload))
    yield _sse("done", "{}")


@router.post("/chat")
def chat(
    req: ChatRequest,
    kb: KbGateway = Depends(get_kb_gateway),
    store: ChatStore = Depends(get_chat_store),
) -> StreamingResponse:
    if req.thread_id:
        try:
            thread = store.get_thread(req.thread_id)
        except ChatStoreNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if req.project_id and thread["project_id"] != req.project_id:
            raise HTTPException(status_code=400, detail="thread_id does not belong to project_id")
    return StreamingResponse(
        _stream(kb, req, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _build_conversation_context(store: ChatStore, thread_id: str) -> str:
    detail = store.get_thread_detail(thread_id)
    project = detail["project"]
    blocks: list[str] = []

    if project.get("instructions", "").strip():
        blocks.append(f"Project instructions:\n{project['instructions'].strip()}")
    if project.get("memory", "").strip():
        blocks.append(f"Curated project memory:\n{project['memory'].strip()}")
    if detail.get("summary", "").strip():
        blocks.append(f"Thread summary:\n{detail['summary'].strip()}")

    prior_messages = detail.get("messages", [])[-MAX_CONTEXT_MESSAGES:]
    if prior_messages:
        recent_lines = []
        for message in prior_messages:
            role = "User" if message["role"] == "user" else "Assistant"
            content = _one_line(message.get("content", ""))[:700]
            if content:
                recent_lines.append(f"{role}: {content}")
        if recent_lines:
            blocks.append("Recent messages:\n" + "\n".join(recent_lines))

    return "\n\n".join(blocks)[:MAX_CONTEXT_CHARS]


def _summarize_thread(store: ChatStore, thread_id: str) -> str:
    detail = store.get_thread_detail(thread_id)
    lines = []
    for message in detail.get("messages", [])[-MAX_SUMMARY_MESSAGES:]:
        role = "User" if message["role"] == "user" else "Assistant"
        content = _one_line(message.get("content", ""))[:320]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[-MAX_SUMMARY_CHARS:]


def _one_line(value: str) -> str:
    return " ".join(value.split())
