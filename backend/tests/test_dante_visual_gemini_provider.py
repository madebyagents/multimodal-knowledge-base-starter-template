from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.dante_visual.gemini_provider import GeminiVisionAnalysisProvider, _extract_text, _parse_json_text, _prepare_image_bytes


def test_gemini_preflight_requires_credentials(tmp_path: Path) -> None:
    provider = GeminiVisionAnalysisProvider(api_key="", asset_root=tmp_path, model_name="gemini-3-flash-preview")

    preflight = provider.preflight()

    assert not preflight.execute_ready
    assert preflight.provider == "gemini"
    assert "resized_image_bytes" in preflight.data_sent


def test_gemini_preflight_ready_with_credentials(tmp_path: Path) -> None:
    provider = GeminiVisionAnalysisProvider(api_key="test-key", asset_root=tmp_path, model_name="models/test-model")

    preflight = provider.preflight()

    assert preflight.execute_ready
    assert preflight.model == "test-model"


def test_parse_json_text_accepts_fenced_json() -> None:
    assert _parse_json_text('```json\n{"technical_reporter": {"confidence": 1}}\n```') == {
        "technical_reporter": {"confidence": 1}
    }


def test_extract_text_reads_gemini_candidate_parts() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}

    assert _extract_text(payload) == '{"ok": true}'


def test_prepare_image_bytes_resizes_to_jpeg(tmp_path: Path) -> None:
    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (2400, 1200), color=(40, 80, 120)).save(image_path, "JPEG", quality=95)

    data = _prepare_image_bytes(image_path, max_image_edge=640, jpeg_quality=80)
    out_path = tmp_path / "out.jpg"
    out_path.write_bytes(data)

    with Image.open(out_path) as image:
        assert max(image.size) == 640
        assert image.format == "JPEG"
