from __future__ import annotations

import pytest

from app.dante_visual.decoupage import (
    ALLOWED_DECOUPAGE_LENSES,
    DECOUPAGE_PROFILE_ID,
    build_decoupage_instructions,
    decoupage_required_fields,
    load_decoupage_prompt,
    load_decoupage_schema,
    load_decoupage_text_format,
)


def test_decoupage_prompt_is_available() -> None:
    prompt = load_decoupage_prompt()

    assert "Art-Grade Decoupage Vision Analyst" in prompt
    assert "Four planes" in prompt
    assert "markdown_handoff" in prompt
    assert DECOUPAGE_PROFILE_ID.endswith(".v1")


def test_decoupage_text_format_is_strict_responses_api_shape() -> None:
    text_format = load_decoupage_text_format()

    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "decoupage_sidecar"
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False


def test_decoupage_schema_keeps_required_contract_and_closed_enums() -> None:
    schema = load_decoupage_schema()
    required = decoupage_required_fields()

    for field in (
        "asset_id",
        "frame_type",
        "lens",
        "decoupage_spine",
        "grounding",
        "markdown_handoff",
    ):
        assert field in required
        assert field in schema["properties"]

    assert schema["properties"]["frame_type"]["enum"] == [
        "film_frame",
        "still_photograph",
        "animation_frame",
        "comic_panel",
        "artwork",
        "architecture",
        "design",
        "unknown",
    ]
    assert tuple(schema["properties"]["lens"]["enum"]) == ALLOWED_DECOUPAGE_LENSES
    assert schema["properties"]["distinction"]["properties"]["flag"]["enum"] == [
        "premium_s_tier",
        "unusual",
        "elegant",
        "innovative",
        "none",
    ]


def test_build_decoupage_instructions_binds_asset_and_lens() -> None:
    instructions = build_decoupage_instructions(asset_id="aftersun-2022-001", lens="judge")

    assert "asset_id: aftersun-2022-001" in instructions
    assert "requested_lens: judge" in instructions
    assert "Return only the structured object accepted by the decoupage_sidecar schema." in instructions


def test_build_decoupage_instructions_rejects_unknown_lens() -> None:
    with pytest.raises(ValueError, match="Unsupported decoupage lens"):
        build_decoupage_instructions(asset_id="aftersun-2022-001", lens="bad-lens")
