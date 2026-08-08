from __future__ import annotations

from app.provider_preflight import (
    preflight_claude_oauth_runtime,
    preflight_codex_oauth_runtime,
    preflight_deepseek_config,
)


def test_deepseek_preflight_does_not_need_secret_value() -> None:
    result = preflight_deepseek_config(
        api_key_present=True,
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
    )
    assert result.ok
    assert result.details == ("ready",)


def test_deepseek_preflight_flags_bad_model_without_secret() -> None:
    result = preflight_deepseek_config(
        api_key_present=False,
        base_url="http://api.deepseek.com",
        model="deepseek-chat",
    )
    assert not result.ok
    assert "DEEPSEEK_API_KEY is missing" in result.details


def test_codex_preflight_checks_binary_and_model(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda value: "/usr/local/bin/codex" if value == "codex" else None)
    result = preflight_codex_oauth_runtime(codex_bin="codex", model="gpt-5.5")
    assert result.ok


def test_claude_preflight_checks_binary_and_model_family(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda value: "/Users/vidigal/.local/bin/claude" if value == "claude" else None)
    result = preflight_claude_oauth_runtime(
        claude_bin="claude",
        sonnet_model="claude-sonnet-4-6",
        opus_model="claude-opus-4-8",
        haiku_model="claude-haiku-4-5",
    )
    assert result.ok
