"""Gemini vision provider for Dante visual-analysis cards."""
from __future__ import annotations

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from .manifest import VisualAsset, resolve_inside, safe_relative_path
from .orchestrator import AnalysisRole, ProviderPreflight, RoleOutput

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


class GeminiVisionAnalysisProvider:
    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        asset_root: Path,
        model_name: str = DEFAULT_GEMINI_MODEL,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        max_image_edge: int = 1280,
        jpeg_quality: int = 82,
        max_output_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key.strip()
        self.asset_root = asset_root
        self.model_name = model_name.removeprefix("models/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.max_image_edge = max_image_edge
        self.jpeg_quality = jpeg_quality
        self.max_output_tokens = max_output_tokens

    def preflight(self) -> ProviderPreflight:
        return ProviderPreflight(
            provider=self.provider_name,
            model=self.model_name,
            credentials_present=bool(self.api_key),
            execute_supported=True,
            no_training_or_retention=(
                "Google Gemini API request; image bytes and text prompt are sent to Google. "
                "This harness stores only normalized card fields and redacted run metadata."
            ),
            data_sent=["resized_image_bytes", "image_metadata", "analysis_prompt"],
            estimated_cost_per_image_usd=None,
            disabled_roles=[],
            privacy_posture_known=True,
        )

    def analyze(self, asset: VisualAsset, roles: list[AnalysisRole]) -> list[RoleOutput]:
        response = self._generate_json(asset, roles)
        outputs: list[RoleOutput] = []
        for role in roles:
            role_payload = response.get(role.value)
            if not isinstance(role_payload, dict):
                role_payload = {}
            normalized_fields = role_payload.get("normalized_fields")
            editorial_flags = role_payload.get("editorial_flags")
            outputs.append(
                RoleOutput(
                    role=role,
                    provider=self.provider_name,
                    model=self.model_name,
                    confidence=_float_between(role_payload.get("confidence"), default=0.66),
                    normalized_fields=normalized_fields if isinstance(normalized_fields, dict) else {},
                    editorial_flags=[str(flag) for flag in editorial_flags] if isinstance(editorial_flags, list) else [],
                    redacted_raw={
                        "provider": self.provider_name,
                        "model": self.model_name,
                        "role": role.value,
                        "image_id": asset.image_id,
                        "source_sha256": asset.sha256,
                        "redacted": True,
                    },
                )
            )
        return outputs

    def _generate_json(self, asset: VisualAsset, roles: list[AnalysisRole]) -> dict[str, Any]:
        image_path = resolve_inside(
            self.asset_root,
            safe_relative_path(asset.new_relative_path, field_name="new_relative_path"),
        )
        image_bytes = _prepare_image_bytes(
            image_path,
            max_image_edge=self.max_image_edge,
            jpeg_quality=self.jpeg_quality,
        )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _prompt(asset, roles)},
                        {"inline_data": {"mime_type": "image/jpeg", "data": encoded}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.15,
                "topP": 0.8,
                "maxOutputTokens": self.max_output_tokens,
                "response_mime_type": "application/json",
            },
        }
        url = f"{GEMINI_ENDPOINT}/models/{self.model_name}:generateContent"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                    timeout=self.timeout_s,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:500]}")
                text = _extract_text(response.json())
                parsed = _parse_json_text(text)
                if not isinstance(parsed, dict):
                    raise ValueError("Gemini response JSON must be an object")
                return parsed
            except (httpx.HTTPError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(2**attempt, 12))
        raise RuntimeError(f"Gemini vision analysis failed for {asset.image_id}: {last_error}") from last_error


def _prompt(asset: VisualAsset, roles: list[AnalysisRole]) -> str:
    role_names = [role.value for role in roles]
    return f"""
Analyze this film/reference image for a premium commercial film production dataset.

Asset:
- image_id: {asset.image_id}
- group: {asset.group}
- category: {asset.category}
- dimensions: {asset.width}x{asset.height}

Return JSON only. The top-level object must contain exactly the requested role keys:
{json.dumps(role_names)}

Each role object must use:
{{
  "confidence": 0.0,
  "normalized_fields": {{}},
  "editorial_flags": []
}}

Use concise, evidence-grounded language. Do not identify private people. Do not invent exact camera/lens data; use phrases like "appears", "suggests", or "candidate" when uncertain.

Required role guidance:
- technical_reporter: visual_tags, texture, focus, exposure, compression, resolution_notes.
- cinematography_reporter: shot_size, composition, lighting, color_palette, cinematography_notes, direction_references, dop_art_director_opinion.
- narrative_editorial_reporter: subject, emotion, narrative_use, editorial_energy, director_opinion, additional_read.
- ocr_visual_facts_reporter: text_detected, visible_text, logos_or_marks, factual_risks.
- judge: score integer 0-100, tier one of s-tier/reference/utility/reject, recommendation.
- confrontation: confrontation, unsupported_claims, contradictions, needs_rerun boolean.

Opinion paragraph rules:
- director_opinion: one paragraph with the eye of a director; do not summarize the card.
- dop_art_director_opinion: one paragraph with the eye of a DOP and art director; do not summarize the card.
- additional_read: one paragraph with a useful extra observation of your choice; do not summarize the card.
- Anti-fatigue mode: avoid generic repeated phrasing; use visible evidence and keep claims defensible.

For card-compatible fields, prefer this shape:
{{"value": "short phrase", "missing_reason": null}}
""".strip()


def _extract_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not include candidates[0].content.parts") from exc
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    text = "\n".join(text for text in texts if text).strip()
    if not text:
        raise ValueError("Gemini response text was empty")
    return text


def _parse_json_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _prepare_image_bytes(image_path: Path, *, max_image_edge: int, jpeg_quality: int) -> bytes:
    with Image.open(image_path) as image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((max_image_edge, max_image_edge))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        return buffer.getvalue()


def _float_between(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))
