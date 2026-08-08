"""Art-grade decoupage prompt/schema profile for Dante visual analysis."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DECOUPAGE_PROFILE_ID = "art_grade_decoupage_vision_analyst.gpt55_port.v1"
DECOUPAGE_SCHEMA_NAME = "decoupage_sidecar"
DECOUPAGE_PROMPT_PATH = Path(__file__).with_name("prompts") / "art_grade_decoupage_vision_analyst.md"
DECOUPAGE_TEXT_FORMAT_PATH = Path(__file__).with_name("schemas") / "decoupage_sidecar.schema.json"

ALLOWED_DECOUPAGE_LENSES = ("solo", "dp", "art_cast", "critic", "judge", "confrontador")


@lru_cache
def load_decoupage_prompt() -> str:
    """Return the full operator prompt supplied for the decoupage pass."""
    return DECOUPAGE_PROMPT_PATH.read_text(encoding="utf-8")


def load_decoupage_text_format() -> dict[str, Any]:
    """Return a copy of the OpenAI Responses API structured-output text.format object."""
    return copy.deepcopy(_load_decoupage_text_format_cached())


@lru_cache
def _load_decoupage_text_format_cached() -> dict[str, Any]:
    payload = json.loads(DECOUPAGE_TEXT_FORMAT_PATH.read_text(encoding="utf-8"))
    _validate_text_format_shape(payload)
    return payload


def load_decoupage_schema() -> dict[str, Any]:
    """Return a defensive copy of the JSON schema inside text.format."""
    return copy.deepcopy(_load_decoupage_text_format_cached()["schema"])


def decoupage_required_fields() -> tuple[str, ...]:
    schema = load_decoupage_schema()
    return tuple(str(field) for field in schema.get("required", ()))


def build_decoupage_instructions(*, asset_id: str, lens: str = "solo") -> str:
    """Build model-facing instructions for one asset without embedding image bytes."""
    if lens not in ALLOWED_DECOUPAGE_LENSES:
        raise ValueError(f"Unsupported decoupage lens: {lens}")
    return (
        f"{load_decoupage_prompt().strip()}\n\n"
        "Runtime binding:\n"
        f"- asset_id: {asset_id}\n"
        f"- requested_lens: {lens}\n"
        "- Return only the structured object accepted by the decoupage_sidecar schema.\n"
        "- Keep every claim grounded in visible, inferred, uncertain, or not_visible evidence.\n"
    )


def _validate_text_format_shape(payload: dict[str, Any]) -> None:
    if payload.get("type") != "json_schema":
        raise ValueError("Decoupage text.format.type must be json_schema")
    if payload.get("name") != DECOUPAGE_SCHEMA_NAME:
        raise ValueError(f"Decoupage schema name must be {DECOUPAGE_SCHEMA_NAME}")
    if payload.get("strict") is not True:
        raise ValueError("Decoupage schema must be strict")
    schema = payload.get("schema")
    if not isinstance(schema, dict):
        raise ValueError("Decoupage payload must include a schema object")
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        raise ValueError("Decoupage schema must include required fields and properties")
    missing_properties = [field for field in required if field not in properties]
    if missing_properties:
        raise ValueError(f"Required decoupage fields missing from properties: {missing_properties}")
