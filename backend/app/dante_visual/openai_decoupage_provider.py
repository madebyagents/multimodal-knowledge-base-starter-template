"""OpenAI Responses API provider for art-grade decoupage sidecars."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .decoupage import build_decoupage_instructions, load_decoupage_text_format
from .gemini_provider import _prepare_image_bytes
from .manifest import VisualAsset, resolve_inside, safe_relative_path
from .orchestrator import ProviderPreflight

DEFAULT_OPENAI_DECOUPAGE_MODEL = "gpt-5.5"
DEFAULT_OPENAI_RESPONSES_BASE_URL = "https://api.openai.com/v1"


@dataclass
class OpenAIDecoupageProvider:
    """Thin REST client for strict decoupage sidecars.

    This provider is intentionally separate from the production
    image_analysis_card.v1 Gemini pipeline. It returns the raw structured
    decoupage object, which should be written into its own sidecar directory
    and reviewed before any ingest.
    """

    api_key: str
    asset_root: Path
    model_name: str = DEFAULT_OPENAI_DECOUPAGE_MODEL
    base_url: str = DEFAULT_OPENAI_RESPONSES_BASE_URL
    timeout_s: float = 180.0
    max_retries: int = 2
    max_image_edge: int = 1280
    jpeg_quality: int = 82
    max_output_tokens: int = 8192
    reasoning_effort: str = "high"
    text_verbosity: str = "high"

    provider_name: str = "openai-decoupage"

    def preflight(self) -> ProviderPreflight:
        return ProviderPreflight(
            provider=self.provider_name,
            model=self.model_name,
            credentials_present=bool(self.api_key.strip()),
            execute_supported=True,
            no_training_or_retention=(
                "OpenAI Responses API request; image bytes, image metadata, strict schema, "
                "and decoupage prompt are sent to OpenAI. This harness stores only reviewed "
                "sidecars and redacted run metadata."
            ),
            data_sent=["resized_image_bytes", "image_metadata", "decoupage_prompt", "strict_json_schema"],
            estimated_cost_per_image_usd=None,
            disabled_roles=[],
            privacy_posture_known=True,
        )

    def analyze(self, asset: VisualAsset, *, lens: str = "solo") -> dict[str, Any]:
        payload = self._build_payload(asset, lens=lens)
        url = f"{self.base_url.rstrip('/')}/responses"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_s,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"OpenAI Responses HTTP {response.status_code}: {response.text[:500]}")
                parsed = _parse_json_text(_extract_response_text(response.json()))
                if not isinstance(parsed, dict):
                    raise ValueError("OpenAI decoupage response JSON must be an object")
                _validate_decoupage_response(parsed, asset=asset, lens=lens)
                return parsed
            except (httpx.HTTPError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(2**attempt, 12))
        raise RuntimeError(f"OpenAI decoupage analysis failed for {asset.image_id}: {last_error}") from last_error

    def _build_payload(self, asset: VisualAsset, *, lens: str) -> dict[str, Any]:
        image_path = resolve_inside(
            self.asset_root,
            safe_relative_path(asset.new_relative_path, field_name="new_relative_path"),
        )
        image_bytes = _prepare_image_bytes(
            image_path,
            max_image_edge=self.max_image_edge,
            jpeg_quality=self.jpeg_quality,
        )
        data_uri = _jpeg_data_uri(image_bytes)
        instructions = (
            f"{build_decoupage_instructions(asset_id=asset.image_id, lens=lens)}\n"
            "Asset metadata:\n"
            f"- group: {asset.group}\n"
            f"- category: {asset.category}\n"
            f"- dimensions: {asset.width}x{asset.height}\n"
            f"- source_sha256: {asset.sha256}\n"
        )
        return {
            "model": self.model_name,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instructions},
                        {"type": "input_image", "image_url": data_uri},
                    ],
                }
            ],
            "reasoning": {"effort": self.reasoning_effort},
            "text": {
                "format": load_decoupage_text_format(),
                "verbosity": self.text_verbosity,
            },
            "max_output_tokens": self.max_output_tokens,
        }


class MockDecoupageProvider:
    """Deterministic local provider for tests and zero-cost pipeline smokes."""

    provider_name = "mock-decoupage"
    model_name = "mock-decoupage-v1"

    def preflight(self) -> ProviderPreflight:
        return ProviderPreflight(
            provider=self.provider_name,
            model=self.model_name,
            credentials_present=True,
            execute_supported=True,
            no_training_or_retention="local deterministic mock; no data leaves machine",
            data_sent=[],
            estimated_cost_per_image_usd=0.0,
            disabled_roles=[],
            privacy_posture_known=True,
        )

    def analyze(self, asset: VisualAsset, *, lens: str = "solo") -> dict[str, Any]:
        payload = mock_decoupage_payload(asset, lens=lens)
        _validate_decoupage_response(payload, asset=asset, lens=lens)
        return payload


def mock_decoupage_payload(asset: VisualAsset, *, lens: str = "solo") -> dict[str, Any]:
    title = asset.group.replace("-", " ")
    return {
        "asset_id": asset.image_id,
        "frame_type": "film_frame",
        "lens": lens,
        "one_line": f"{title} reference frame with controlled cinematic staging.",
        "decoupage_spine": {
            "key": "cinematic reference",
            "form": "balanced film-still analysis",
            "angle": "craft-first, evidence-grounded read",
        },
        "composition": {
            "dominant_geometry": "stable rectangular frame with readable subject hierarchy",
            "blocking": "primary subject pressure is carried by placement and negative space",
            "depth": "foreground, midground, and background remain separable",
            "edge_pressure": "moderate edge control without accidental cropping claims",
            "negative_space": "negative space supports the dramatic read",
            "balance": "asymmetric but intentional",
        },
        "camera_lens": {
            "shot_size": "medium",
            "angle_height": "eye-level candidate",
            "focal_length_class": "normal-to-slightly-long candidate",
            "depth_of_field": "selective enough to guide attention",
            "movement": "still frame; movement not visible",
            "camera_intention": "organizes the viewer around mood and blocking rather than spectacle",
        },
        "lighting": {
            "pattern": "motivated",
            "quality": "soft-to-moderate",
            "direction": "directional motivated source candidate",
            "contrast_ratio": "moderate contrast",
            "practicals": "not confidently visible",
            "shadow_design": "shadows preserve contour and atmosphere",
            "exposure_strategy": "protects important tonal information",
        },
        "color": {
            "grade_family": "naturalistic",
            "grade_family_note": "naturalistic candidate; exact grade cannot be asserted from the still alone",
            "harmony": "restrained palette with coherent tonal relationships",
            "palette": [
                {"hex": "#2b2f2f", "role": "shadow", "name": "charcoal green gray"},
                {"hex": "#b6a179", "role": "midtone", "name": "muted warm beige"},
                {"hex": "#d8c8a3", "role": "highlight", "name": "soft aged ivory"},
            ],
            "lift_gamma_gain": "low lift, measured midtones, protected highlights",
            "saturation": "restrained",
            "contrast_curve": "gentle cinematic contrast",
            "skin_tone": "not asserted unless visible",
            "technical_vs_creative": "grade appears to support mood while keeping the image legible",
        },
        "art_direction": {
            "world_period": "not fully determinable from the frame alone",
            "set_decoration": "visible environment is read as intentional production context",
            "props_signified": ["contextual texture"],
            "texture_materiality": "material surfaces are treated as story information",
            "production_value": "reference-grade photographic control candidate",
            "read": "art direction supports the image without overwhelming the central read",
        },
        "costume": {
            "pieces": [],
            "silhouette_period": "not confidently visible",
            "character_through_wardrobe": "wardrobe read is unavailable or secondary",
            "color_story": "costume color does not dominate this mock read",
            "condition_wear": "not confidently visible",
        },
        "performance": {
            "present": False,
            "physical_type": "no performer-specific physical type confidently visible in mock mode",
            "status_read": "not visible",
            "method_tells": [],
            "body_effort": "not visible",
            "facs_aus": [],
            "displayed_emotion": {
                "primary": "not visible",
                "blend": [],
                "intensity": "1",
                "suppressed": "not visible",
            },
            "subtext": "not visible",
            "objective_obstacle": "not visible",
            "implied_moment": "not visible",
        },
        "domain_module": {"kind": "none", "read": "No secondary medium-specific module is required."},
        "registers": {
            "technical": "The frame is treated as a controlled visual reference, not a source of exact camera facts.",
            "artistic": "Its value comes from composed restraint and readable atmospheric intent.",
            "taste": "Useful as a premium reference if the collection needs quiet craft over novelty.",
            "narrative": "The image can anchor tone, blocking, and emotional pacing.",
            "philosophical": "The frame matters as evidence that small visual decisions can carry authorial weight.",
        },
        "lineage": {
            "echoes": ["naturalistic cinema", "restrained production design"],
            "why": "The lineage is inferred from visible restraint, tonal control, and staging discipline.",
        },
        "distinction": {
            "flag": "elegant",
            "why": "Elegant because the frame reads as disciplined rather than decorative.",
            "consistency_of_intention": True,
        },
        "grounding": {
            "visible": [
                {
                    "claim": "The image is a rectangular visual reference asset.",
                    "visible_support": f"{asset.width}x{asset.height} source dimensions in the manifest.",
                    "confidence": 1.0,
                }
            ],
            "inferred": [
                {
                    "claim": "The frame has cinematic reference value.",
                    "basis": "Manifest grouping and visible-image workflow context.",
                    "confidence": 0.62,
                }
            ],
            "uncertain": ["Exact camera body, lens, stock, Kelvin, and production intent are not asserted."],
            "not_visible": ["True internal emotion", "behind-the-scenes production facts"],
        },
        "proactive_adjacencies": [
            {
                "pointer": "compare with adjacent frames in the same film group",
                "why": "Sequence context can separate one-off beauty from repeatable visual language.",
            }
        ],
        "opinion": "This mock read marks the asset as worth a serious decoupage pass, while withholding exact technical claims.",
        "provenance": {
            "lens": lens,
            "frame_type": "film_frame",
            "confidence_overall": 0.68,
        },
        "markdown_handoff": (
            f"# {asset.image_id}\n\n"
            "A disciplined cinematic reference frame with enough craft signal to justify a premium decoupage pass. "
            "The important move is restraint: composition, tonal control, and atmosphere are treated as evidence, "
            "while exact equipment and production facts remain unclaimed until a real model pass reviews the pixels."
        ),
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    joined = "\n".join(texts).strip()
    if not joined:
        raise ValueError("OpenAI response did not include output_text or output[].content[].text")
    return joined


def _parse_json_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _validate_decoupage_response(payload: dict[str, Any], *, asset: VisualAsset, lens: str) -> None:
    required = set(load_decoupage_text_format()["schema"]["required"])
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Decoupage response missing required fields: {missing}")
    if payload.get("asset_id") != asset.image_id:
        raise ValueError(f"Decoupage asset_id mismatch: {payload.get('asset_id')!r} != {asset.image_id!r}")
    if payload.get("lens") != lens:
        raise ValueError(f"Decoupage lens mismatch: {payload.get('lens')!r} != {lens!r}")
    markdown = payload.get("markdown_handoff")
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Decoupage response must include non-empty markdown_handoff")


def _jpeg_data_uri(data: bytes) -> str:
    import base64

    return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"
