"""Image-analysis card validation and rendering."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .manifest import VisualAsset, safe_relative_path, validate_slug
from .safe_io import safe_write_text

SCHEMA_VERSION = "image_analysis_card.v1"
PROMPT_VERSION = "dante_visual_analysis.v1"
DEFAULT_KH_PROMOTION = "not_targeted"
REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_premium", "needs_rerun"}


@dataclass(frozen=True)
class CardWriteResult:
    image_id: str
    json_path: Path
    markdown_path: Path
    reused: bool = False


def missing(reason: str) -> dict[str, str | None]:
    return {"value": None, "missing_reason": reason}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_card(
    asset: VisualAsset,
    *,
    run_id: str,
    model_runs: list[dict[str, Any]] | None = None,
    normalized_analysis: dict[str, Any] | None = None,
    editorial_judgment: dict[str, Any] | None = None,
    review_status: str = "pending",
) -> dict[str, Any]:
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {review_status}")

    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "image_id": asset.image_id,
        "created_at": utc_now_iso(),
        "run_id": run_id,
        "source": {
            "new_relative_path": asset.new_relative_path,
            "old_relative_path": asset.old_relative_path,
            "previous_relative_path": asset.previous_relative_path,
            "sha256": asset.sha256,
            "bytes": asset.bytes,
            "category": asset.category,
            "group": asset.group,
            "batch_or_note": asset.batch_or_note,
            "width": asset.width,
            "height": asset.height,
        },
        "asset": {
            "file_name": asset.file_name,
            "file_stem": asset.file_stem,
            "image_format": "jpg",
        },
        "model_runs": model_runs or [],
        "normalized_analysis": normalized_analysis or _empty_normalized_analysis(),
        "text_in_frame": {
            "detected": False,
            "transcript": None,
            "missing_reason": "No OCR or visual-facts reporter output was available.",
        },
        "product_brand_qc": {
            "logos_or_brands": [],
            "risks": [],
            "missing_reason": "No brand-specific review was available.",
        },
        "ai_artifact_qc": {
            "suspected_ai_artifacts": [],
            "real_vs_ai_signal": missing("No artifact specialist output was available."),
        },
        "continuity_qc": {
            "continuity_flags": [],
            "missing_reason": "No sequence-level continuity pass was available.",
        },
        "technical_visual_qc": {
            "focus": missing("No technical reporter output was available."),
            "exposure": missing("No technical reporter output was available."),
            "compression": missing("No technical reporter output was available."),
            "resolution": {"width": asset.width, "height": asset.height},
        },
        "editorial_judgment": editorial_judgment or _empty_editorial_judgment(),
        "review_assets": {
            "card_json": str(asset.card_json_relative_path),
            "card_markdown": str(asset.card_markdown_relative_path),
            "raw_runs": [run.get("redacted_raw_path") for run in (model_runs or []) if run.get("redacted_raw_path")],
        },
        "review": {
            "status": review_status,
            "reviewer": None,
            "reviewed_at": None,
            "reason": None,
        },
        "skill_kb": {
            "skill": "dailies-corte",
            "schema": SCHEMA_VERSION,
            "canonical_knowledge_hub_promotion": DEFAULT_KH_PROMOTION,
        },
    }


def _empty_normalized_analysis() -> dict[str, Any]:
    reason = "No vision-analysis provider output was available."
    return {
        "visual_tags": [],
        "subject": missing(reason),
        "shot_size": missing(reason),
        "composition": missing(reason),
        "color_palette": [],
        "lighting": missing(reason),
        "texture": missing(reason),
        "emotion": missing(reason),
        "narrative_use": missing(reason),
        "cinematography_notes": missing(reason),
        "direction_references": [],
    }


def _empty_editorial_judgment() -> dict[str, Any]:
    return {
        "score": 0,
        "tier": "unrated",
        "recommendation": "pending_analysis",
        "flags": ["baseline_missing"],
        "missing_reason": "No judge or editorial reporter output was available.",
    }


def validate_card(card: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "prompt_version", "image_id", "run_id", "source", "asset", "review"):
        if key not in card:
            errors.append(f"Missing required top-level field: {key}")

    source = card.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        for key in ("new_relative_path", "sha256", "category", "group", "width", "height"):
            if not source.get(key):
                errors.append(f"source.{key} is required")
        if source.get("new_relative_path"):
            try:
                safe_relative_path(str(source["new_relative_path"]), field_name="source.new_relative_path")
            except ValueError as exc:
                errors.append(str(exc))
        for key in ("category", "group"):
            if source.get(key):
                try:
                    validate_slug(str(source[key]), field_name=f"source.{key}")
                except ValueError as exc:
                    errors.append(str(exc))

    image_id = card.get("image_id")
    if image_id:
        try:
            validate_slug(str(image_id), field_name="image_id")
        except ValueError as exc:
            errors.append(str(exc))

    asset = card.get("asset")
    if isinstance(asset, dict) and asset.get("file_stem"):
        try:
            validate_slug(str(asset["file_stem"]), field_name="asset.file_stem")
        except ValueError as exc:
            errors.append(str(exc))

    review = card.get("review")
    if not isinstance(review, dict):
        errors.append("review must be an object")
    elif review.get("status") not in REVIEW_STATUSES:
        errors.append(f"review.status must be one of {sorted(REVIEW_STATUSES)}")

    if card.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    if not isinstance(card.get("model_runs", []), list):
        errors.append("model_runs must be a list")

    return errors


def ensure_valid_card(card: dict[str, Any]) -> None:
    errors = validate_card(card)
    if errors:
        raise ValueError("; ".join(errors))


def render_markdown(card: dict[str, Any]) -> str:
    ensure_valid_card(card)
    source = card["source"]
    analysis = card["normalized_analysis"]
    judgment = card["editorial_judgment"]
    dimensions = f"{source['width']}x{source['height']}"
    lines = [
        "---",
        f"image_id: {_md_text(card['image_id'])}",
        f"schema_version: {_md_text(card['schema_version'])}",
        f"source_sha256: {_md_text(source['sha256'])}",
        f"review_status: {_md_text(card['review']['status'])}",
        f"run_id: {_md_text(card['run_id'])}",
        "---",
        "",
        f"# {_md_text(card['image_id'])}",
        "",
        f"- Source: {_md_code(source['new_relative_path'])}",
        f"- Original path: {_md_code(source.get('old_relative_path') or 'n/a')}",
        f"- Previous path: {_md_code(source.get('previous_relative_path') or 'n/a')}",
        f"- Group: {_md_code(source['group'])}",
        f"- Category: {_md_code(source['category'])}",
        f"- Dimensions: {_md_code(dimensions)}",
        f"- Editorial tier: {_md_code(judgment.get('tier', 'unrated'))}",
        f"- Editorial score: {_md_code(judgment.get('score', 0))}",
        "",
        "## Visual Analysis",
        "",
        f"- Subject: {_display_value(analysis.get('subject'))}",
        f"- Shot size: {_display_value(analysis.get('shot_size'))}",
        f"- Composition: {_display_value(analysis.get('composition'))}",
        f"- Lighting: {_display_value(analysis.get('lighting'))}",
        f"- Texture: {_display_value(analysis.get('texture'))}",
        f"- Emotion: {_display_value(analysis.get('emotion'))}",
        f"- Narrative use: {_display_value(analysis.get('narrative_use'))}",
        "",
        "## Tags",
        "",
        ", ".join(_md_code(tag) for tag in analysis.get("visual_tags", [])) or "_No tags yet._",
        "",
        "## Model Runs",
        "",
    ]
    model_runs = card.get("model_runs") or []
    if model_runs:
        for run in model_runs:
            lines.append(
                f"- {_md_code(run.get('role', 'unknown'))} via {_md_code(run.get('provider', 'unknown'))} "
                f"model {_md_code(run.get('model', 'unknown'))} confidence {_md_code(run.get('confidence', 'n/a'))}"
            )
    else:
        lines.append("_No model runs recorded._")
    lines.extend(["", "## Review", "", f"- Status: {_md_code(card['review']['status'])}"])
    lines.extend(_render_interpretive_notes(card))
    return "\n".join(lines).rstrip() + "\n"


def _render_interpretive_notes(card: dict[str, Any]) -> list[str]:
    paragraphs = _build_interpretive_paragraphs(card)
    return [
        "",
        "## Interpretive Notes",
        "",
        "### Director's View",
        "",
        _md_text(paragraphs["director"]),
        "",
        "### DOP / Art Director's View",
        "",
        _md_text(paragraphs["dop_art_director"]),
        "",
        "### Additional Read",
        "",
        _md_text(paragraphs["additional"]),
    ]


def _build_interpretive_paragraphs(card: dict[str, Any]) -> dict[str, str]:
    analysis = card.get("normalized_analysis") or {}
    judgment = card.get("editorial_judgment") or {}
    image_id = str(card.get("image_id", "image"))
    subject = _field_text(analysis, "subject", "the visible subject")
    shot_size = _field_text(analysis, "shot_size", "the frame scale")
    composition = _field_text(analysis, "composition", "the frame geometry")
    lighting = _field_text(analysis, "lighting", "the lighting design")
    texture = _field_text(analysis, "texture", "the image texture")
    emotion = _field_text(analysis, "emotion", "the emotional pressure")
    narrative_use = _field_text(analysis, "narrative_use", "a usable story beat")
    cinematography_notes = _field_text(analysis, "cinematography_notes", "")
    color_palette = _field_text(analysis, "color_palette", "the recorded palette")
    direction_refs = _field_text(analysis, "direction_references", "")
    tags = _field_text(analysis, "visual_tags", "")
    explicit_director = _field_text(analysis, "director_opinion", "")
    explicit_dop_art_director = _field_text(analysis, "dop_art_director_opinion", "")
    explicit_additional = _field_text(analysis, "additional_read", "")
    tier = _field_text(judgment, "tier", "unrated")
    score = _field_text(judgment, "score", "unscored")
    recommendation = _field_text(judgment, "recommendation", "review-required")
    flags = _field_text(judgment, "flags", "")

    director_opening = _variant(
        image_id,
        [
            "This frame should be directed as a lived beat, not as decorative coverage.",
            "The directing value here is behavioral pressure: the image gives the scene a playable inner turn.",
            "As a directing reference, this works best when treated as withheld action rather than exposition.",
        ],
    )
    dop_opening = _variant(
        image_id + "-dop",
        [
            "The photographic and art-direction value sits in how the image controls attention.",
            "For camera and production design, the useful instruction is restraint with specific pressure points.",
            "The DOP and art department should treat the frame as a calibrated atmosphere, not a generic look.",
        ],
    )
    additional_opening = _variant(
        image_id + "-additional",
        [
            "What I would keep from this frame is its practical use as a decision-making reference.",
            "The extra value is not the label, but the discipline it implies for staging, color, and edit rhythm.",
            "I would keep this card because it can steer taste during pre-production rather than merely decorate a board.",
        ],
    )

    director = explicit_director or (
        f"{director_opening} The subject reads as {subject}; with {shot_size} and {composition}, "
        f"the scene attention should stay on behavior, silence, and the precise emotional turn. "
        f"The emotional register is {emotion}, and the strongest dramatic use is {narrative_use}."
    )

    dop_sentences = [
        (
            f"{dop_opening} The light reads as {lighting}, the palette reads as {color_palette}, "
            f"and the surface quality reads as {texture}."
        )
    ]
    if cinematography_notes:
        dop_sentences.append(_sentence_or_empty(cinematography_notes))
    dop_sentences.append(f"The art direction should support {composition} without adding noise.")
    dop_art_director = explicit_dop_art_director or " ".join(dop_sentences)

    if explicit_additional:
        additional = explicit_additional
    else:
        additional_bits = [
            f"{additional_opening} I would file it as {tier} with score {score} and recommendation {recommendation}."
        ]
        if direction_refs:
            additional_bits.append(f"The useful direction-reference signal is {direction_refs}.")
        if tags:
            additional_bits.append(f"The working tags are {tags}.")
        if flags:
            additional_bits.append(f"The review flags worth preserving are {flags}.")
        additional = " ".join(additional_bits)

    return {
        "director": director,
        "dop_art_director": dop_art_director,
        "additional": additional,
    }


def _sentence_or_empty(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _field_text(container: dict[str, Any], key: str, fallback: str) -> str:
    return _plain_text(container.get(key), fallback=fallback)


def _plain_text(value: Any, *, fallback: str = "") -> str:
    if isinstance(value, dict):
        if value.get("value") not in (None, ""):
            return _plain_text(value["value"], fallback=fallback)
        if value.get("missing_reason"):
            return fallback
        return fallback
    if isinstance(value, list):
        items = [_plain_text(item).strip() for item in value]
        items = [item for item in items if item]
        return ", ".join(items) if items else fallback
    if value in (None, ""):
        return fallback
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def _variant(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    index = sum(ord(char) for char in seed) % len(options)
    return options[index]


def _display_value(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("value") is not None:
            return _md_text(value["value"])
        if value.get("missing_reason"):
            return f"_Missing: {_md_text(value['missing_reason'])}_"
    if value is None:
        return "_Missing_"
    return _md_text(value)


def _md_text(value: Any) -> str:
    return html.escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")


def _md_code(value: Any) -> str:
    sanitized = _md_text(value).replace("`", "'")
    return f"`{sanitized}`"


def write_card_pair(card: dict[str, Any], cards_root: Path) -> CardWriteResult:
    ensure_valid_card(card)
    source = card["source"]
    stem = Path(source["new_relative_path"]).stem
    card_dir = cards_root / source["category"] / source["group"]
    json_path = card_dir / f"{stem}.json"
    markdown_path = card_dir / f"{stem}.md"
    safe_write_text(
        json_path,
        json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        root=cards_root,
    )
    safe_write_text(markdown_path, render_markdown(card), root=cards_root)
    return CardWriteResult(image_id=card["image_id"], json_path=json_path, markdown_path=markdown_path)


def read_card(path: Path) -> dict[str, Any]:
    card = json.loads(path.read_text(encoding="utf-8"))
    ensure_valid_card(card)
    return card
