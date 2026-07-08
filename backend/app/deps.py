"""Settings + KB singleton."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .chat_store import ChatStore
from .kb import KnowledgeBase
from .kb_backends import ChromaKbBackend, KnowledgeHubKbBackend
from .kb_gateway import KbGateway
from .knowledge_hub_client import KnowledgeHubClient

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    voyage_api_key: str
    deepseek_api_key: str
    cohere_api_key: str | None
    voyage_multimodal_model: str
    voyage_multimodal_dimension: int
    deepseek_model: str
    deepseek_base_url: str
    codex_bin: str
    codex_oauth_model: str
    codex_oauth_reasoning_effort: str
    codex_oauth_timeout_s: float
    claude_bin: str
    claude_sonnet_model: str
    claude_opus_model: str
    claude_haiku_model: str
    claude_sonnet_effort: str
    claude_opus_effort: str
    claude_haiku_effort: str
    claude_judge_effort: str
    claude_oauth_timeout_s: float
    claude_oauth_premium_timeout_s: float
    claude_premium_repair_cap: int
    cohere_rerank_model: str
    enable_cohere_rerank: bool
    kb_persist_dir: Path
    kb_upload_dir: Path
    chat_state_db: Path
    kb_collection: str
    cors_origins: list[str]
    log_level: str
    knowledge_hub_base_url: str
    knowledge_hub_actions_base_url: str
    knowledge_hub_actions_bearer_token: str | None
    knowledge_hub_timeout_s: float
    knowledge_hub_strict_smoke: bool
    dantedash_kb_backend: str
    dantedash_chroma_fallback_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    voyage_api_key = os.getenv("VOYAGE_API_KEY", "").strip()
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    cohere_api_key = os.getenv("COHERE_API_KEY", "").strip() or None
    enable_cohere_rerank = os.getenv("ENABLE_COHERE_RERANK", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    if not voyage_api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is not set. Set it in backend/.env before starting the sidecar."
        )
    if not deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set. Set it in backend/.env before starting the sidecar."
        )
    if enable_cohere_rerank and not cohere_api_key:
        raise RuntimeError(
            "COHERE_API_KEY is not set while ENABLE_COHERE_RERANK=true."
        )
    return Settings(
        voyage_api_key=voyage_api_key,
        deepseek_api_key=deepseek_api_key,
        cohere_api_key=cohere_api_key,
        voyage_multimodal_model=os.getenv("VOYAGE_MULTIMODAL_MODEL", "voyage-multimodal-3.5"),
        voyage_multimodal_dimension=int(os.getenv("VOYAGE_MULTIMODAL_DIMENSION", "1024")),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        codex_bin=os.getenv("CODEX_BIN", "codex"),
        codex_oauth_model=os.getenv("CODEX_OAUTH_MODEL", "gpt-5.5"),
        codex_oauth_reasoning_effort=os.getenv("CODEX_OAUTH_REASONING_EFFORT", "xhigh"),
        codex_oauth_timeout_s=float(os.getenv("CODEX_OAUTH_TIMEOUT_S", "600")),
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        claude_sonnet_model=os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6"),
        claude_opus_model=os.getenv("CLAUDE_OPUS_MODEL", "claude-opus-4-8"),
        claude_haiku_model=os.getenv("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5"),
        claude_sonnet_effort=os.getenv("CLAUDE_SONNET_EFFORT", "medium"),
        claude_opus_effort=os.getenv("CLAUDE_OPUS_EFFORT", "high"),
        claude_haiku_effort=os.getenv("CLAUDE_HAIKU_EFFORT", "low"),
        claude_judge_effort=os.getenv("CLAUDE_JUDGE_EFFORT", "medium"),
        claude_oauth_timeout_s=float(os.getenv("CLAUDE_OAUTH_TIMEOUT_S", "900")),
        claude_oauth_premium_timeout_s=float(os.getenv("CLAUDE_OAUTH_PREMIUM_TIMEOUT_S", "1200")),
        claude_premium_repair_cap=int(os.getenv("CLAUDE_PREMIUM_REPAIR_CAP", "1")),
        cohere_rerank_model=os.getenv("COHERE_RERANK_MODEL", "rerank-v4.0-pro"),
        enable_cohere_rerank=enable_cohere_rerank,
        kb_persist_dir=_setting_path("KB_PERSIST_DIR", BASE_DIR / "chroma_db"),
        kb_upload_dir=_setting_path("KB_UPLOAD_DIR", BASE_DIR / "uploads"),
        chat_state_db=_setting_path("CHAT_STATE_DB", BASE_DIR / "app_state" / "chat.sqlite"),
        kb_collection=os.getenv("KB_COLLECTION", "dante_multimodal_kb"),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()],
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        knowledge_hub_base_url=os.getenv("KNOWLEDGE_HUB_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
        knowledge_hub_actions_base_url=os.getenv(
            "KNOWLEDGE_HUB_ACTIONS_BASE_URL",
            "http://127.0.0.1:8098",
        ).rstrip("/"),
        knowledge_hub_actions_bearer_token=os.getenv("KNOWLEDGE_HUB_ACTIONS_BEARER_TOKEN", "").strip() or None,
        knowledge_hub_timeout_s=float(os.getenv("KNOWLEDGE_HUB_TIMEOUT_S", "4")),
        knowledge_hub_strict_smoke=os.getenv("KNOWLEDGE_HUB_STRICT_SMOKE", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        dantedash_kb_backend=os.getenv("DANTEDASH_KB_BACKEND", "knowledge_hub").strip().lower() or "knowledge_hub",
        dantedash_chroma_fallback_enabled=os.getenv("DANTEDASH_CHROMA_FALLBACK_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )


def _setting_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


@lru_cache(maxsize=1)
def get_kb() -> KnowledgeBase:
    s = get_settings()
    logger.info(
        "Initialising KnowledgeBase (persist=%s, upload=%s, collection=%s, embed=%s/%sd, rerank=%s)",
        s.kb_persist_dir, s.kb_upload_dir, s.kb_collection,
        s.voyage_multimodal_model, s.voyage_multimodal_dimension, s.enable_cohere_rerank,
    )
    return KnowledgeBase(
        voyage_api_key=s.voyage_api_key,
        deepseek_api_key=s.deepseek_api_key,
        cohere_api_key=s.cohere_api_key,
        collection_name=s.kb_collection,
        persist_dir=s.kb_persist_dir,
        upload_dir=s.kb_upload_dir,
        embed_model=s.voyage_multimodal_model,
        embed_dim=s.voyage_multimodal_dimension,
        deepseek_model=s.deepseek_model,
        deepseek_base_url=s.deepseek_base_url,
        codex_bin=s.codex_bin,
        codex_oauth_model=s.codex_oauth_model,
        codex_oauth_reasoning_effort=s.codex_oauth_reasoning_effort,
        codex_oauth_timeout_s=s.codex_oauth_timeout_s,
        claude_bin=s.claude_bin,
        claude_sonnet_model=s.claude_sonnet_model,
        claude_opus_model=s.claude_opus_model,
        claude_haiku_model=s.claude_haiku_model,
        claude_sonnet_effort=s.claude_sonnet_effort,
        claude_opus_effort=s.claude_opus_effort,
        claude_haiku_effort=s.claude_haiku_effort,
        claude_judge_effort=s.claude_judge_effort,
        claude_oauth_timeout_s=s.claude_oauth_timeout_s,
        claude_oauth_premium_timeout_s=s.claude_oauth_premium_timeout_s,
        claude_premium_repair_cap=s.claude_premium_repair_cap,
        cohere_rerank_model=s.cohere_rerank_model,
        enable_rerank=s.enable_cohere_rerank,
    )


@lru_cache(maxsize=1)
def get_knowledge_hub_client() -> KnowledgeHubClient:
    s = get_settings()
    return KnowledgeHubClient(
        base_url=s.knowledge_hub_base_url,
        actions_base_url=s.knowledge_hub_actions_base_url,
        actions_bearer_token=s.knowledge_hub_actions_bearer_token,
        timeout_s=s.knowledge_hub_timeout_s,
    )


@lru_cache(maxsize=1)
def get_kb_gateway() -> KbGateway:
    s = get_settings()
    return KbGateway(
        mode=s.dantedash_kb_backend,
        chroma=lambda: ChromaKbBackend(get_kb()),
        knowledge_hub=KnowledgeHubKbBackend(get_knowledge_hub_client()),
        chroma_fallback_enabled=s.dantedash_chroma_fallback_enabled,
    )


@lru_cache(maxsize=1)
def get_chat_store() -> ChatStore:
    s = get_settings()
    logger.info("Initialising ChatStore (db=%s)", s.chat_state_db)
    return ChatStore(s.chat_state_db)
