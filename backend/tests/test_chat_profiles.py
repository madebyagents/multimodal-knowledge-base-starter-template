from __future__ import annotations

from app.chat_models import (
    CHAT_MODEL_CLAUDE_OPUS,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_DEEPSEEK,
)
from app.chat_profiles import QUALITY_GATE, active_chat_profiles, active_profile_ids, get_chat_profile


def test_active_profiles_are_in_menu_order() -> None:
    ids = active_profile_ids()
    assert ids == (
        CHAT_MODEL_DEEPSEEK,
        CHAT_MODEL_CODEX_OAUTH,
        CHAT_MODEL_CLAUDE_SONNET,
        CHAT_MODEL_CLAUDE_OPUS,
    )
    labels = [profile.label for profile in active_chat_profiles()]
    assert labels == [
        "deepseek - deepseek-v4-pro",
        "openai/codex - gpt-5.5 OAuth",
        "claude - sonnet-4.6 OAuth",
        "claude - opus-4.8 OAuth Premium",
    ]


def test_profiles_keep_same_provider_helpers_hidden() -> None:
    for profile in active_chat_profiles():
        assert profile.quality_gate == QUALITY_GATE
        assert profile.visibility == "principal"
        if profile.worker is not None:
            assert profile.worker.provider_family == profile.provider_family
            assert profile.worker.visibility == "worker"
            assert profile.worker.default_enabled is False
        if profile.premium is not None:
            assert profile.premium.chief.provider_family == profile.provider_family
            assert profile.premium.judge.provider_family == profile.provider_family
            assert all(worker.provider_family == profile.provider_family for worker in profile.premium.worker_pool)
            assert 1 <= profile.premium.repair_cap <= 2


def test_get_chat_profile_returns_expected_provider_routes() -> None:
    assert get_chat_profile(CHAT_MODEL_DEEPSEEK).auth_route == "api_key"
    assert get_chat_profile(CHAT_MODEL_CODEX_OAUTH).auth_route == "codex_oauth"
    assert get_chat_profile(CHAT_MODEL_CLAUDE_SONNET).auth_route == "claude_oauth"
    assert get_chat_profile(CHAT_MODEL_CLAUDE_OPUS).auth_route == "claude_oauth"
