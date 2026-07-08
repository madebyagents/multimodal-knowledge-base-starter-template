"""Prompt registry composition for active DanteDash chat modes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..chat_models import ChatModelId
from ..chat_profiles import get_chat_profile
from .loader import PromptAsset, load_prompt_asset

PROMPT_ROOT = Path(__file__).resolve().parent

PRINCIPAL_POLICIES = (
    "policies/provider_isolation.md",
    "policies/citation_grounding.md",
    "policies/insufficient_evidence.md",
    "policies/worker_visibility.md",
    "policies/voice.md",
)
WORKER_POLICIES = (
    "policies/provider_isolation.md",
    "policies/worker_visibility.md",
)
JUDGE_POLICIES = (
    "policies/provider_isolation.md",
    "policies/worker_visibility.md",
)
ROLE_ASSETS = {
    "deepseek_principal": "roles/deepseek_principal.md",
    "deepseek_worker": "roles/deepseek_worker.md",
    "codex_gpt55_principal": "roles/codex_gpt55_principal.md",
    "codex_gpt54_mini_worker": "roles/codex_gpt54_mini_worker.md",
    "claude_sonnet_principal": "roles/claude_sonnet_principal.md",
    "opus_premium_principal": "roles/opus_premium_principal.md",
    "haiku_worker": "roles/haiku_worker.md",
    "sonnet_chief": "roles/sonnet_chief.md",
    "opus_judge": "roles/opus_judge.md",
}
ACTIVE_PROMPT_IDS = frozenset(ROLE_ASSETS)
BLOCKED_RUNTIME_TERMS = ("claude", "anthropic", "opus", "sonnet", "haiku")


@dataclass(frozen=True)
class PromptBundle:
    prompt_id: str
    provider_family: str
    visibility: str
    system_prompt: str
    assets: tuple[str, ...]


def get_prompt_bundle_for_chat_model(chat_model: ChatModelId) -> PromptBundle:
    profile = get_chat_profile(chat_model)
    return _compose_bundle(
        prompt_id=profile.principal_prompt_id,
        provider_family=profile.provider_family,
        visibility="principal",
        policies=PRINCIPAL_POLICIES,
    )


def get_worker_prompt_bundle(prompt_id: str) -> PromptBundle:
    return get_role_prompt_bundle(prompt_id, visibility="worker")


def get_role_prompt_bundle(prompt_id: str, *, visibility: str) -> PromptBundle:
    if visibility == "principal":
        policies = PRINCIPAL_POLICIES
    elif visibility in {"worker", "chief"}:
        policies = WORKER_POLICIES
    elif visibility == "judge":
        policies = JUDGE_POLICIES
    else:
        raise ValueError(f"Unsupported prompt visibility: {visibility}")
    return _compose_bundle(
        prompt_id=prompt_id,
        provider_family=_load_role(prompt_id).metadata["provider_family"],
        visibility=visibility,
        policies=policies,
    )


def _compose_bundle(
    *,
    prompt_id: str,
    provider_family: str,
    visibility: str,
    policies: tuple[str, ...],
) -> PromptBundle:
    role = _load_role(prompt_id)
    _validate_asset(role, provider_family=provider_family, visibility=visibility)
    policy_assets = tuple(load_prompt_asset(PROMPT_ROOT / policy) for policy in policies)
    for policy in policy_assets:
        _validate_runtime_text(policy.body, policy.path)
    parts = [role.body, *(policy.body for policy in policy_assets)]
    system_prompt = "\n\n".join(parts).strip()
    return PromptBundle(
        prompt_id=prompt_id,
        provider_family=provider_family,
        visibility=visibility,
        system_prompt=system_prompt,
        assets=tuple([str(role.path.relative_to(PROMPT_ROOT)), *policies]),
    )


def _load_role(prompt_id: str) -> PromptAsset:
    if prompt_id not in ACTIVE_PROMPT_IDS:
        raise KeyError(f"Prompt is not active in this runtime: {prompt_id}")
    return load_prompt_asset(PROMPT_ROOT / ROLE_ASSETS[prompt_id])


def _validate_asset(asset: PromptAsset, *, provider_family: str, visibility: str) -> None:
    if asset.metadata.get("provider_family") != provider_family:
        raise ValueError(
            f"Prompt provider mismatch for {asset.path.name}: "
            f"{asset.metadata.get('provider_family')} != {provider_family}"
        )
    if asset.metadata.get("visibility") != visibility:
        raise ValueError(
            f"Prompt visibility mismatch for {asset.path.name}: "
            f"{asset.metadata.get('visibility')} != {visibility}"
        )
    _validate_runtime_text(asset.body, asset.path, allow_provider_terms=True)


def _validate_runtime_text(text: str, path: Path, *, allow_provider_terms: bool = False) -> None:
    if allow_provider_terms:
        return
    lowered = text.lower()
    blocked = [term for term in BLOCKED_RUNTIME_TERMS if term in lowered]
    if blocked:
        raise ValueError(f"Runtime prompt asset {path.name} mentions blocked provider terms: {blocked}")
