"""Premium-balanced visual-analysis orchestration."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .cards import build_card, write_card_pair
from .manifest import VisualAsset, validate_run_id
from .safe_io import safe_write_text


class AnalysisRole(StrEnum):
    TECHNICAL = "technical_reporter"
    CINEMATOGRAPHY = "cinematography_reporter"
    NARRATIVE = "narrative_editorial_reporter"
    OCR_FACTS = "ocr_visual_facts_reporter"
    JUDGE = "judge"
    CONFRONTATION = "confrontation"


BASELINE_ROLES = (
    AnalysisRole.TECHNICAL,
    AnalysisRole.CINEMATOGRAPHY,
    AnalysisRole.NARRATIVE,
    AnalysisRole.OCR_FACTS,
)

PREMIUM_ROLES = (AnalysisRole.JUDGE, AnalysisRole.CONFRONTATION)


@dataclass(frozen=True)
class ProviderPreflight:
    provider: str
    model: str
    credentials_present: bool
    execute_supported: bool
    no_training_or_retention: str
    data_sent: list[str]
    estimated_cost_per_image_usd: float | None
    disabled_roles: list[str]
    privacy_posture_known: bool

    @property
    def execute_ready(self) -> bool:
        return self.execute_supported and self.credentials_present and self.privacy_posture_known


@dataclass(frozen=True)
class RoleOutput:
    role: AnalysisRole
    provider: str
    model: str
    confidence: float
    normalized_fields: dict[str, object]
    editorial_flags: list[str]
    redacted_raw: dict[str, object]


class VisionAnalysisProvider(Protocol):
    """Provider contract for image-input visual analysis."""

    provider_name: str
    model_name: str

    def preflight(self) -> ProviderPreflight:
        """Return credential, cost, request-shape, and privacy posture data."""

    def analyze(self, asset: VisualAsset, roles: list[AnalysisRole]) -> list[RoleOutput]:
        """Analyze one visual asset for the requested roles."""


class MockVisionAnalysisProvider:
    provider_name = "mock"
    model_name = "mock-vision-analysis-v1"

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

    def analyze(self, asset: VisualAsset, roles: list[AnalysisRole]) -> list[RoleOutput]:
        outputs: list[RoleOutput] = []
        score_seed = int(asset.sha256[:2], 16)
        score = 55 + (score_seed % 41)
        for role in roles:
            outputs.append(
                RoleOutput(
                    role=role,
                    provider=self.provider_name,
                    model=self.model_name,
                    confidence=0.74 if role in BASELINE_ROLES else 0.82,
                    normalized_fields=_mock_fields(asset, role, score),
                    editorial_flags=_mock_flags(asset, role, score),
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


def _mock_fields(asset: VisualAsset, role: AnalysisRole, score: int) -> dict[str, object]:
    if role == AnalysisRole.TECHNICAL:
        return {
            "visual_tags": ["film-still", asset.category, asset.group],
            "texture": {"value": "visible film-reference texture", "missing_reason": None},
        }
    if role == AnalysisRole.CINEMATOGRAPHY:
        return {
            "shot_size": {"value": "medium shot candidate", "missing_reason": None},
            "composition": {"value": "balanced frame with cinematic blocking cues", "missing_reason": None},
            "lighting": {"value": "motivated practical or naturalistic light candidate", "missing_reason": None},
            "color_palette": ["neutral", "cinematic-reference"],
        }
    if role == AnalysisRole.NARRATIVE:
        return {
            "subject": {"value": asset.group.replace("-", " "), "missing_reason": None},
            "emotion": {"value": "restrained dramatic energy", "missing_reason": None},
            "narrative_use": {"value": "usable as visual reference for scene tone and staging", "missing_reason": None},
        }
    if role == AnalysisRole.OCR_FACTS:
        return {"text_detected": False}
    if role == AnalysisRole.JUDGE:
        return {"score": score, "tier": "s-tier" if score >= 85 else "reference"}
    return {"confrontation": "No contradictions detected by mock provider."}


def _mock_flags(asset: VisualAsset, role: AnalysisRole, score: int) -> list[str]:
    flags: list[str] = []
    if score >= 85:
        flags.append("s_tier_candidate")
    if asset.category == "curated-research":
        flags.append("curated_research")
    if role == AnalysisRole.CONFRONTATION and score < 65:
        flags.append("low_priority_no_conflict")
    return flags


def select_premium_assets(assets: list[VisualAsset], *, max_premium: int) -> set[str]:
    if max_premium <= 0:
        return set()
    preferred: list[tuple[int, str]] = []
    fallback: list[tuple[int, str]] = []
    for asset in assets:
        score_seed = int(asset.sha256[:2], 16)
        score = 55 + (score_seed % 41)
        fallback.append((score, asset.image_id))
        if score >= 85 or asset.category == "curated-research":
            preferred.append((score, asset.image_id))
    preferred.sort(reverse=True)
    fallback.sort(reverse=True)
    selected: list[str] = []
    for _score, image_id in preferred + fallback:
        if image_id not in selected:
            selected.append(image_id)
        if len(selected) >= max_premium:
            break
    return set(selected)


def generate_cards(
    assets: list[VisualAsset],
    *,
    cards_root: Path,
    raw_runs_root: Path,
    run_id: str,
    provider: VisionAnalysisProvider | None = None,
    max_premium: int = 0,
    continue_on_error: bool = False,
) -> dict[str, object]:
    provider = provider or MockVisionAnalysisProvider()
    preflight = provider.preflight()
    if not preflight.execute_ready:
        raise RuntimeError(
            f"Vision provider {preflight.provider!r} is not execute-ready; "
            "check credentials, support, and privacy posture."
        )
    premium_ids = select_premium_assets(assets, max_premium=max_premium)
    results = []
    errors = []
    cards_written = 0
    for asset in assets:
        roles = list(BASELINE_ROLES)
        if asset.image_id in premium_ids:
            roles.extend(PREMIUM_ROLES)
        try:
            role_outputs = provider.analyze(asset, roles)
        except Exception as exc:
            if not continue_on_error:
                raise
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            errors.append({"image_id": asset.image_id, "error": error})
            results.append(
                {
                    "image_id": asset.image_id,
                    "card_json": "",
                    "card_markdown": "",
                    "premium": asset.image_id in premium_ids,
                    "error": error,
                }
            )
            continue
        model_runs = [_write_raw_run(output, asset, raw_runs_root, run_id) for output in role_outputs]
        normalized = _merge_normalized_fields(role_outputs)
        judgment = _build_editorial_judgment(role_outputs)
        card = build_card(
            asset,
            run_id=run_id,
            model_runs=model_runs,
            normalized_analysis=normalized,
            editorial_judgment=judgment,
        )
        write_result = write_card_pair(card, cards_root)
        cards_written += 1
        results.append(
            {
                "image_id": asset.image_id,
                "card_json": str(write_result.json_path.relative_to(cards_root.parent)),
                "card_markdown": str(write_result.markdown_path.relative_to(cards_root.parent)),
                "premium": asset.image_id in premium_ids,
                "error": "",
            }
        )

    return {
        "provider_preflight": asdict(preflight),
        "cards_written": cards_written,
        "premium_selected": len(premium_ids),
        "error_count": len(errors),
        "errors": errors,
        "results": results,
    }


def _write_raw_run(output: RoleOutput, asset: VisualAsset, raw_runs_root: Path, run_id: str) -> dict[str, object]:
    run_id = validate_run_id(run_id)
    raw_dir = raw_runs_root / run_id / output.role.value / asset.category / asset.group
    raw_path = raw_dir / f"{asset.file_stem}.json"
    payload = _redacted_raw_payload(output)
    safe_write_text(raw_path, json.dumps(payload, indent=2, sort_keys=True) + "\n", root=raw_runs_root)
    return {
        "role": output.role.value,
        "provider": output.provider,
        "model": output.model,
        "confidence": output.confidence,
        "redacted_raw_path": str(
            Path("raw-runs") / run_id / output.role.value / asset.category / asset.group / raw_path.name
        ),
    }


def _redacted_raw_payload(output: RoleOutput) -> dict[str, object]:
    allowed_keys = {"provider", "model", "role", "image_id", "source_sha256", "redacted"}
    denied_fragments = ("key", "token", "secret", "authorization", "password")
    extra_keys = set(output.redacted_raw) - allowed_keys
    if extra_keys:
        raise ValueError(f"Raw-run payload contains disallowed keys: {sorted(extra_keys)}")
    payload: dict[str, object] = {}
    for key in allowed_keys:
        if key not in output.redacted_raw:
            continue
        value = output.redacted_raw[key]
        if isinstance(value, str):
            lowered = value.lower()
            if any(fragment in key.lower() for fragment in denied_fragments) or any(
                fragment in lowered for fragment in denied_fragments
            ):
                raise ValueError(f"Raw-run payload contains secret-like value in {key}")
        elif not isinstance(value, bool):
            raise ValueError(f"Raw-run field {key} must be a string or boolean")
        payload[key] = value
    if payload.get("redacted") is not True:
        raise ValueError("Raw-run payload must declare redacted=true")
    return payload


def _merge_normalized_fields(outputs: list[RoleOutput]) -> dict[str, object]:
    merged = {
        "visual_tags": [],
        "subject": {"value": None, "missing_reason": "No subject reporter output was available."},
        "shot_size": {"value": None, "missing_reason": "No cinematography reporter output was available."},
        "composition": {"value": None, "missing_reason": "No cinematography reporter output was available."},
        "color_palette": [],
        "lighting": {"value": None, "missing_reason": "No cinematography reporter output was available."},
        "texture": {"value": None, "missing_reason": "No technical reporter output was available."},
        "emotion": {"value": None, "missing_reason": "No narrative reporter output was available."},
        "narrative_use": {"value": None, "missing_reason": "No narrative reporter output was available."},
        "cinematography_notes": {"value": None, "missing_reason": "No cinematography reporter output was available."},
        "direction_references": [],
        "director_opinion": {"value": None, "missing_reason": "No narrative reporter output was available."},
        "dop_art_director_opinion": {"value": None, "missing_reason": "No cinematography reporter output was available."},
        "additional_read": {"value": None, "missing_reason": "No narrative reporter output was available."},
    }
    tags: set[str] = set()
    for output in outputs:
        for key, value in output.normalized_fields.items():
            if key == "visual_tags" and isinstance(value, list):
                tags.update(str(item) for item in value)
            elif key == "color_palette" and isinstance(value, list):
                merged["color_palette"] = sorted(set(str(item) for item in value))
            elif key in merged:
                merged[key] = value
    merged["visual_tags"] = sorted(tags)
    return merged


def _build_editorial_judgment(outputs: list[RoleOutput]) -> dict[str, object]:
    score = 0
    tier = "unrated"
    flags: set[str] = set()
    for output in outputs:
        flags.update(output.editorial_flags)
        if output.role == AnalysisRole.JUDGE:
            score = _coerce_score(output.normalized_fields.get("score"), default=0)
            tier = _coerce_text(output.normalized_fields.get("tier"), default="reference")
    if score == 0:
        score = 50
        tier = "baseline"
    return {
        "score": score,
        "tier": tier,
        "recommendation": "review_required",
        "flags": sorted(flags),
        "missing_reason": None,
    }


def _coerce_score(value: object, *, default: int) -> int:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        score = int(float(str(value)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


def _coerce_text(value: object, *, default: str) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return default
    text = str(value).strip()
    return text or default
