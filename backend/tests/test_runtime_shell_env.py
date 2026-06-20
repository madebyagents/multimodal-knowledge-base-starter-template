from __future__ import annotations

import subprocess
from pathlib import Path

from app.deps import get_settings


ROOT_DIR = Path(__file__).resolve().parents[2]
HELPER = ROOT_DIR / "scripts" / "dante_kb_runtime_env.sh"


def run_bash(script: str) -> str:
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def source_helper(command: str) -> str:
    return run_bash(f"source {HELPER!s}; {command}")


def test_kb_runtime_defaults_export_knowledge_hub_without_chroma_fallback() -> None:
    output = source_helper(
        "unset DANTEDASH_KB_BACKEND DANTEDASH_CHROMA_FALLBACK_ENABLED; "
        "dante_export_kb_runtime_defaults; "
        'printf "%s %s" "$DANTEDASH_KB_BACKEND" "$DANTEDASH_CHROMA_FALLBACK_ENABLED"'
    )

    assert output == "knowledge_hub false"


def test_python_settings_default_to_knowledge_hub_without_chroma_fallback(monkeypatch) -> None:
    monkeypatch.delenv("DANTEDASH_KB_BACKEND", raising=False)
    monkeypatch.delenv("DANTEDASH_CHROMA_FALLBACK_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.dantedash_kb_backend == "knowledge_hub"
        assert settings.dantedash_chroma_fallback_enabled is False
    finally:
        get_settings.cache_clear()


def test_python_settings_preserve_explicit_chroma_fallback(monkeypatch) -> None:
    monkeypatch.setenv("DANTEDASH_KB_BACKEND", "knowledge_hub")
    monkeypatch.setenv("DANTEDASH_CHROMA_FALLBACK_ENABLED", "true")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.dantedash_kb_backend == "knowledge_hub"
        assert settings.dantedash_chroma_fallback_enabled is True
    finally:
        get_settings.cache_clear()


def test_kb_runtime_defaults_preserve_explicit_operator_values() -> None:
    output = source_helper(
        "export DANTEDASH_KB_BACKEND=chroma; "
        "export DANTEDASH_CHROMA_FALLBACK_ENABLED=false; "
        "dante_export_kb_runtime_defaults; "
        'printf "%s %s" "$DANTEDASH_KB_BACKEND" "$DANTEDASH_CHROMA_FALLBACK_ENABLED"'
    )

    assert output == "chroma false"


def test_default_chroma_fallback_matches_backend_mode() -> None:
    output = source_helper(
        'printf "%s %s %s %s" '
        '"$(dante_default_chroma_fallback_for_backend knowledge_hub)" '
        '"$(dante_default_chroma_fallback_for_backend chroma)" '
        '"$(dante_default_chroma_fallback_for_backend dual)" '
        '"$(dante_default_chroma_fallback_for_backend "")"'
    )

    assert output == "false false false false"


def test_truthy_helper_is_case_insensitive_and_strict() -> None:
    output = source_helper(
        "for value in 1 true TRUE yes On 0 false no off ''; do "
        "if dante_truthy \"$value\"; then printf 'T'; else printf 'F'; fi; "
        "done"
    )

    assert output == "TTTTTFFFFF"
