from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.dante_visual.manifest import VisualAsset, sha256_file
from app.dante_visual.openai_decoupage_provider import (
    MockDecoupageProvider,
    OpenAIDecoupageProvider,
    _extract_response_text,
    mock_decoupage_payload,
)


def make_asset(tmp_path: Path) -> tuple[Path, VisualAsset]:
    asset_root = tmp_path / "assets"
    relative = Path("film-stills") / "aftersun-2022" / "aftersun-2022-001.jpg"
    image_path = asset_root / relative
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (32, 18), color=(80, 90, 70)).save(image_path, "JPEG")
    return asset_root, VisualAsset(
        row_number=2,
        image_id="aftersun-2022-001",
        old_relative_path=str(relative),
        new_relative_path=str(relative),
        previous_relative_path=str(relative),
        sha256=sha256_file(image_path),
        bytes=image_path.stat().st_size,
        category="film-stills",
        group="aftersun-2022",
        batch_or_note="",
        width=32,
        height=18,
        file_name="aftersun-2022-001.jpg",
        file_stem="aftersun-2022-001",
    )


def test_openai_decoupage_preflight_requires_credentials(tmp_path: Path) -> None:
    provider = OpenAIDecoupageProvider(api_key="", asset_root=tmp_path)

    preflight = provider.preflight()

    assert not preflight.execute_ready
    assert preflight.provider == "openai-decoupage"
    assert "strict_json_schema" in preflight.data_sent


def test_mock_decoupage_provider_returns_schema_shaped_payload(tmp_path: Path) -> None:
    _asset_root, asset = make_asset(tmp_path)
    payload = MockDecoupageProvider().analyze(asset, lens="judge")

    assert payload["asset_id"] == asset.image_id
    assert payload["lens"] == "judge"
    assert payload["grounding"]["visible"]
    assert payload["markdown_handoff"].startswith("# aftersun-2022-001")


def test_openai_decoupage_provider_posts_responses_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asset_root, asset = make_asset(tmp_path)
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {"output_text": json.dumps(mock_decoupage_payload(asset, lens="critic"))}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("app.dante_visual.openai_decoupage_provider.httpx.post", fake_post)
    provider = OpenAIDecoupageProvider(
        api_key="test-key",
        asset_root=asset_root,
        model_name="test-model",
        base_url="https://example.test/v1",
        max_retries=0,
    )

    result = provider.analyze(asset, lens="critic")

    assert result["asset_id"] == asset.image_id
    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    request = captured["json"]
    assert request["model"] == "test-model"
    assert request["text"]["format"]["name"] == "decoupage_sidecar"
    assert request["text"]["format"]["strict"] is True
    assert request["reasoning"]["effort"] == "high"
    assert request["input"][0]["content"][1]["type"] == "input_image"
    assert request["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")


def test_openai_decoupage_provider_rejects_asset_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset_root, asset = make_asset(tmp_path)
    bad_payload = mock_decoupage_payload(asset, lens="solo")
    bad_payload["asset_id"] = "other-asset-001"

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {"output_text": json.dumps(bad_payload)}

    monkeypatch.setattr("app.dante_visual.openai_decoupage_provider.httpx.post", lambda *a, **k: FakeResponse())
    provider = OpenAIDecoupageProvider(api_key="test-key", asset_root=asset_root, max_retries=0)

    with pytest.raises(RuntimeError, match="asset_id mismatch"):
        provider.analyze(asset, lens="solo")


def test_extract_response_text_reads_nested_output_content() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"ok": true}'},
                ],
            }
        ]
    }

    assert _extract_response_text(payload) == '{"ok": true}'
