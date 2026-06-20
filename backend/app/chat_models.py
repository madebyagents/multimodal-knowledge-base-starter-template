"""Chat model identifiers accepted by the Dante Dashboard API."""
from __future__ import annotations

from typing import Literal

CHAT_MODEL_DEEPSEEK = "deepseek-v4-pro"
CHAT_MODEL_CODEX_OAUTH = "codex-gpt-5.5-oauth"
CHAT_MODEL_CLAUDE_SONNET = "claude-sonnet-4-6-oauth"
CHAT_MODEL_CLAUDE_OPUS = "claude-opus-4-8-oauth"

ChatModelId = Literal[
    "deepseek-v4-pro",
    "codex-gpt-5.5-oauth",
    "claude-sonnet-4-6-oauth",
    "claude-opus-4-8-oauth",
]

ACTIVE_CHAT_MODEL_IDS: tuple[ChatModelId, ...] = (
    CHAT_MODEL_DEEPSEEK,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CLAUDE_OPUS,
)
