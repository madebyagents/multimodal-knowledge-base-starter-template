"""Provider preflight checks that avoid printing secrets or auth state."""
from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatPreflightResult:
    provider: str
    ok: bool
    model: str
    details: tuple[str, ...]


def preflight_deepseek_config(
    *,
    api_key_present: bool,
    base_url: str,
    model: str,
) -> ChatPreflightResult:
    details: list[str] = []
    if not api_key_present:
        details.append("DEEPSEEK_API_KEY is missing")
    if not base_url.startswith("https://"):
        details.append("DeepSeek base URL should be HTTPS")
    if model not in {"deepseek-v4-pro", "deepseek-v4-flash"}:
        details.append("DeepSeek model is not one of the verified V4 IDs")
    return ChatPreflightResult(
        provider="deepseek",
        ok=not details,
        model=model,
        details=tuple(details or ("ready",)),
    )


def preflight_codex_oauth_runtime(
    *,
    codex_bin: str,
    model: str,
) -> ChatPreflightResult:
    details: list[str] = []
    if shutil.which(codex_bin) is None:
        details.append(f"Codex binary not found: {codex_bin}")
    if model != "gpt-5.5":
        details.append("Codex OAuth principal model should be gpt-5.5")
    return ChatPreflightResult(
        provider="openai_codex",
        ok=not details,
        model=model,
        details=tuple(details or ("ready",)),
    )


def preflight_claude_oauth_runtime(
    *,
    claude_bin: str,
    sonnet_model: str,
    opus_model: str,
    haiku_model: str,
) -> ChatPreflightResult:
    details: list[str] = []
    if shutil.which(claude_bin) is None:
        details.append(f"Claude binary not found: {claude_bin}")
    expected = {
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-8",
        "haiku": "claude-haiku-4-5",
    }
    if sonnet_model != expected["sonnet"]:
        details.append("Claude Sonnet OAuth model should be claude-sonnet-4-6")
    if opus_model != expected["opus"]:
        details.append("Claude Opus OAuth model should be claude-opus-4-8")
    if haiku_model != expected["haiku"]:
        details.append("Claude Haiku OAuth worker model should be claude-haiku-4-5")
    return ChatPreflightResult(
        provider="anthropic",
        ok=not details,
        model=opus_model,
        details=tuple(details or ("ready",)),
    )
