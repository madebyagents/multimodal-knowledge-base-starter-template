from __future__ import annotations

from app.chat_models import (
    CHAT_MODEL_CLAUDE_OPUS,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_DEEPSEEK,
)
from app.chat_prompts import get_prompt_bundle_for_chat_model, get_role_prompt_bundle, get_worker_prompt_bundle


def test_principal_prompt_bundles_load_for_active_models() -> None:
    for chat_model in (
        CHAT_MODEL_DEEPSEEK,
        CHAT_MODEL_CODEX_OAUTH,
        CHAT_MODEL_CLAUDE_SONNET,
        CHAT_MODEL_CLAUDE_OPUS,
    ):
        bundle = get_prompt_bundle_for_chat_model(chat_model)
        assert bundle.visibility == "principal"
        assert "Grounding and Citation" in bundle.system_prompt
        assert "Evidence Sufficiency" in bundle.system_prompt
        assert "Provider Isolation" in bundle.system_prompt
        assert "Internal Visibility" in bundle.system_prompt
        assert "Voice" in bundle.system_prompt
        assert "policies/voice.md" in bundle.assets


def test_worker_prompt_bundles_are_hidden_and_structured() -> None:
    for prompt_id in ("deepseek_worker", "codex_gpt54_mini_worker", "haiku_worker"):
        bundle = get_worker_prompt_bundle(prompt_id)
        assert bundle.visibility == "worker"
        assert "not user-facing" in bundle.system_prompt
        assert "Return only a JSON object" in bundle.system_prompt
        assert "policies/voice.md" not in bundle.assets


def test_anthropic_prompt_ids_are_runtime_registered_with_expected_roles() -> None:
    sonnet = get_prompt_bundle_for_chat_model(CHAT_MODEL_CLAUDE_SONNET)
    opus = get_prompt_bundle_for_chat_model(CHAT_MODEL_CLAUDE_OPUS)
    worker = get_role_prompt_bundle("haiku_worker", visibility="worker")
    chief = get_role_prompt_bundle("sonnet_chief", visibility="chief")
    judge = get_role_prompt_bundle("opus_judge", visibility="judge")

    assert sonnet.provider_family == "anthropic"
    assert opus.provider_family == "anthropic"
    assert worker.provider_family == "anthropic"
    assert chief.visibility == "chief"
    assert judge.visibility == "judge"
    assert "Return only a JSON object" in judge.system_prompt
    assert "policies/voice.md" not in worker.assets
    assert "policies/voice.md" not in chief.assets
    assert "policies/voice.md" not in judge.assets


def test_user_facing_prompt_bundles_do_not_leak_provider_model_names() -> None:
    for chat_model in (
        CHAT_MODEL_DEEPSEEK,
        CHAT_MODEL_CODEX_OAUTH,
        CHAT_MODEL_CLAUDE_SONNET,
        CHAT_MODEL_CLAUDE_OPUS,
    ):
        lowered = get_prompt_bundle_for_chat_model(chat_model).system_prompt.lower()
        assert "anthropic" not in lowered
        assert "claude" not in lowered
        assert "opus" not in lowered
        assert "sonnet" not in lowered
        assert "haiku" not in lowered


def test_voice_policy_is_guard_clean() -> None:
    bundle = get_prompt_bundle_for_chat_model(CHAT_MODEL_DEEPSEEK)
    voice_asset = [asset for asset in bundle.assets if asset == "policies/voice.md"]
    assert voice_asset == ["policies/voice.md"]
    assert "\u2014" not in bundle.system_prompt
