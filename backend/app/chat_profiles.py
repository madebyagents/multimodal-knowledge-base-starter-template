"""Runtime chat profile registry for DanteDash."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .chat_models import (
    ACTIVE_CHAT_MODEL_IDS,
    CHAT_MODEL_CLAUDE_OPUS,
    CHAT_MODEL_CLAUDE_SONNET,
    CHAT_MODEL_CODEX_OAUTH,
    CHAT_MODEL_DEEPSEEK,
    ChatModelId,
)

ProviderFamily = Literal["deepseek", "openai_codex", "anthropic"]
Visibility = Literal["principal", "worker", "chief", "judge"]

QUALITY_GATE = 0.78


@dataclass(frozen=True)
class WorkerProfile:
    """Hidden same-provider worker configuration."""

    worker_id: str
    provider_family: ProviderFamily
    model: str
    prompt_id: str
    default_enabled: bool = False
    quality_gate: float = QUALITY_GATE
    visibility: Visibility = "worker"


@dataclass(frozen=True)
class ChiefProfile:
    """Hidden same-provider chief configuration for Premium orchestration."""

    chief_id: str
    provider_family: ProviderFamily
    model: str
    prompt_id: str
    visibility: Visibility = "chief"


@dataclass(frozen=True)
class JudgeProfile:
    """Hidden same-provider judge configuration for Premium orchestration."""

    judge_id: str
    provider_family: ProviderFamily
    model: str
    prompt_id: str
    visibility: Visibility = "judge"


@dataclass(frozen=True)
class PremiumOrchestrationProfile:
    """Hidden same-provider Premium workflow configuration."""

    chief: ChiefProfile
    worker_pool: tuple[WorkerProfile, ...]
    judge: JudgeProfile
    repair_cap: int = 1


@dataclass(frozen=True)
class ChatProfile:
    """A user-visible chat mode and its hidden same-provider orchestration."""

    public_id: ChatModelId
    label: str
    provider_family: ProviderFamily
    principal_model: str
    principal_prompt_id: str
    auth_route: Literal["api_key", "codex_oauth", "claude_oauth"]
    quality_gate: float = QUALITY_GATE
    worker: WorkerProfile | None = None
    premium: PremiumOrchestrationProfile | None = None
    visibility: Visibility = "principal"


ACTIVE_CHAT_PROFILES: dict[ChatModelId, ChatProfile] = {
    CHAT_MODEL_DEEPSEEK: ChatProfile(
        public_id=CHAT_MODEL_DEEPSEEK,
        label="deepseek - deepseek-v4-pro",
        provider_family="deepseek",
        principal_model="deepseek-v4-pro",
        principal_prompt_id="deepseek_principal",
        auth_route="api_key",
        worker=WorkerProfile(
            worker_id="deepseek-worker",
            provider_family="deepseek",
            model="deepseek-v4-flash",
            prompt_id="deepseek_worker",
            default_enabled=False,
        ),
    ),
    CHAT_MODEL_CODEX_OAUTH: ChatProfile(
        public_id=CHAT_MODEL_CODEX_OAUTH,
        label="openai/codex - gpt-5.5 OAuth",
        provider_family="openai_codex",
        principal_model="gpt-5.5",
        principal_prompt_id="codex_gpt55_principal",
        auth_route="codex_oauth",
        worker=WorkerProfile(
            worker_id="codex-gpt54-mini-worker",
            provider_family="openai_codex",
            model="gpt-5.4-mini",
            prompt_id="codex_gpt54_mini_worker",
            default_enabled=False,
        ),
    ),
    CHAT_MODEL_CLAUDE_SONNET: ChatProfile(
        public_id=CHAT_MODEL_CLAUDE_SONNET,
        label="claude - sonnet-4.6 OAuth",
        provider_family="anthropic",
        principal_model="claude-sonnet-4-6",
        principal_prompt_id="claude_sonnet_principal",
        auth_route="claude_oauth",
        worker=WorkerProfile(
            worker_id="claude-haiku-45-worker",
            provider_family="anthropic",
            model="claude-haiku-4-5",
            prompt_id="haiku_worker",
            default_enabled=False,
        ),
    ),
    CHAT_MODEL_CLAUDE_OPUS: ChatProfile(
        public_id=CHAT_MODEL_CLAUDE_OPUS,
        label="claude - opus-4.8 OAuth Premium",
        provider_family="anthropic",
        principal_model="claude-opus-4-8",
        principal_prompt_id="opus_premium_principal",
        auth_route="claude_oauth",
        premium=PremiumOrchestrationProfile(
            chief=ChiefProfile(
                chief_id="claude-sonnet-46-chief",
                provider_family="anthropic",
                model="claude-sonnet-4-6",
                prompt_id="sonnet_chief",
            ),
            worker_pool=(
                WorkerProfile(
                    worker_id="claude-haiku-45-premium-worker",
                    provider_family="anthropic",
                    model="claude-haiku-4-5",
                    prompt_id="haiku_worker",
                    default_enabled=True,
                ),
            ),
            judge=JudgeProfile(
                judge_id="claude-opus-48-judge",
                provider_family="anthropic",
                model="claude-opus-4-8",
                prompt_id="opus_judge",
            ),
            repair_cap=1,
        ),
    ),
}


def get_chat_profile(chat_model: ChatModelId) -> ChatProfile:
    """Return the active runtime profile for a supported chat model."""
    return ACTIVE_CHAT_PROFILES[chat_model]


def active_chat_profiles() -> tuple[ChatProfile, ...]:
    """Return profiles in menu order."""
    return tuple(ACTIVE_CHAT_PROFILES[model_id] for model_id in ACTIVE_CHAT_MODEL_IDS)


def active_profile_ids() -> tuple[ChatModelId, ...]:
    """Return the public model IDs accepted by the current runtime."""
    return ACTIVE_CHAT_MODEL_IDS
