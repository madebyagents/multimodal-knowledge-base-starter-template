"""Runtime prompt registry for DanteDash chat."""
from .registry import (
    PromptBundle,
    get_prompt_bundle_for_chat_model,
    get_role_prompt_bundle,
    get_worker_prompt_bundle,
)

__all__ = [
    "PromptBundle",
    "get_prompt_bundle_for_chat_model",
    "get_role_prompt_bundle",
    "get_worker_prompt_bundle",
]
