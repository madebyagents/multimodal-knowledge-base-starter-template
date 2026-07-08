from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.chat_models import (
    CHAT_MODEL_CLAUDE_OPUS,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_DEEPSEEK,
)
from app.schemas import preview_url_for
from app.schemas import ChatRequest


def test_preview_url_for_text_visual_bundle_uses_linked_image() -> None:
    assert (
        preview_url_for(
            {
                "id": "dante_visual_card_a",
                "modality": "text",
                "preview_image_file_id": "dante_visual_img_a",
            }
        )
        == "/api/preview/dante_visual_img_a"
    )


def test_chat_request_accepts_supported_chat_models() -> None:
    assert ChatRequest(question="x").chat_model == CHAT_MODEL_DEEPSEEK
    assert (
        ChatRequest(question="x", chat_model=CHAT_MODEL_CODEX_OAUTH).chat_model
        == CHAT_MODEL_CODEX_OAUTH
    )
    assert (
        ChatRequest(question="x", chat_model=CHAT_MODEL_CLAUDE_SONNET).chat_model
        == CHAT_MODEL_CLAUDE_SONNET
    )
    assert (
        ChatRequest(question="x", chat_model=CHAT_MODEL_CLAUDE_OPUS).chat_model
        == CHAT_MODEL_CLAUDE_OPUS
    )


def test_chat_request_rejects_unknown_chat_model() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="x", chat_model="unknown")
