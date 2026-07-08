from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.dante_visual.cards import build_card, read_card, render_markdown, validate_card, write_card_pair
from app.dante_visual.manifest import VisualAsset


def asset() -> VisualAsset:
    return VisualAsset(
        row_number=2,
        image_id="aftersun-2022-001",
        old_relative_path="film-stills/aftersun-2022/old.jpg",
        new_relative_path="film-stills/aftersun-2022/aftersun-2022-001.jpg",
        previous_relative_path="film-stills/aftersun-2022/previous.jpg",
        sha256="a" * 64,
        bytes=1234,
        category="film-stills",
        group="aftersun-2022",
        batch_or_note="",
        width=1920,
        height=1080,
        file_name="aftersun-2022-001.jpg",
        file_stem="aftersun-2022-001",
    )


def test_build_card_validates_and_renders_markdown() -> None:
    card = build_card(asset(), run_id="visual-test")

    assert validate_card(card) == []
    markdown = render_markdown(card)
    assert "# aftersun-2022-001" in markdown
    assert "source_sha256" in markdown
    assert "not_targeted" not in markdown


def test_render_markdown_adds_interpretive_opinion_paragraphs() -> None:
    card = build_card(
        asset(),
        run_id="visual-test",
        normalized_analysis={
            "visual_tags": ["close-up", "soft-light"],
            "subject": "woman at a threshold",
            "shot_size": {"value": "close-up", "missing_reason": None},
            "composition": {"value": "centered, shallow-depth portrait", "missing_reason": None},
            "color_palette": ["cyan", "skin-tone", "black"],
            "lighting": {"value": "soft cool top-light with low contrast fill", "missing_reason": None},
            "texture": "fine grain and visible skin detail",
            "emotion": "quiet pressure",
            "narrative_use": "a held reaction beat before the cut",
            "cinematography_notes": "Preserve the restrained contrast and shallow focus.",
            "direction_references": ["clinical intimacy"],
        },
        editorial_judgment={
            "score": 87,
            "tier": "s-tier",
            "recommendation": "promote_to_reference",
            "flags": ["hero_reference"],
            "missing_reason": None,
        },
    )

    markdown = render_markdown(card)

    assert markdown.index("## Visual Analysis") < markdown.index("## Interpretive Notes")
    assert "### Director's View" in markdown
    assert "### DOP / Art Director's View" in markdown
    assert "### Additional Read" in markdown
    assert "woman at a threshold" in markdown
    assert "promote_to_reference" in markdown


def test_render_markdown_prefers_explicit_interpretive_fields() -> None:
    card = build_card(
        asset(),
        run_id="visual-test",
        normalized_analysis={
            "director_opinion": "Direct the frame as a withheld decision, not as a plot explanation.",
            "dop_art_director_opinion": "Protect the cool soft source and let the set stay spare.",
            "additional_read": "The useful extra note is the refusal to over-design the beat.",
        },
    )

    markdown = render_markdown(card)

    assert "Direct the frame as a withheld decision" in markdown
    assert "Protect the cool soft source" in markdown
    assert "refusal to over-design" in markdown
    assert "The subject reads as the visible subject" not in markdown


def test_write_card_pair_uses_same_basename(tmp_path: Path) -> None:
    card = build_card(asset(), run_id="visual-test")

    result = write_card_pair(card, tmp_path)

    assert result.json_path.name == "aftersun-2022-001.json"
    assert result.markdown_path.name == "aftersun-2022-001.md"
    assert read_card(result.json_path)["image_id"] == "aftersun-2022-001"


def test_card_requires_source_sha() -> None:
    broken_asset = replace(asset(), sha256="")
    card = build_card(broken_asset, run_id="visual-test")

    assert "source.sha256 is required" in validate_card(card)
