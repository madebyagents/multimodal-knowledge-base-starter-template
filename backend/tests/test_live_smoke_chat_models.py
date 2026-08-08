from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "live-smoke-chat-models.py"
    spec = importlib.util.spec_from_file_location("live_smoke_chat_models", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_status_for_result_classifies_deepseek_insufficient_balance() -> None:
    module = _load_script_module()
    status = module._status_for_result(
        'DeepSeek chat HTTP 402: {"error":{"message":"Insufficient Balance"}}',
        "",
        None,
    )
    assert status == "provider_unavailable"


def test_status_for_result_requires_citation_validation() -> None:
    module = _load_script_module()
    assert module._status_for_result(None, "Grounded answer [1].", None) == "missing_citation_validation"
    assert (
        module._status_for_result(
            None,
            "Grounded answer [1].",
            {"ok": True, "source_count": 1},
        )
        == "ok"
    )
