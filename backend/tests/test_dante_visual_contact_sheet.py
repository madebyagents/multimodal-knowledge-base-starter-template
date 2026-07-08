from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.dante_visual.cards import build_card, write_card_pair
from app.dante_visual.contact_sheet import ReviewDecision, append_review_decision, generate_contact_sheet
from app.dante_visual.manifest import VisualAsset


def make_asset(tmp_path: Path) -> tuple[VisualAsset, Path]:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/aftersun-2022-001.jpg"
    image_path = asset_root / image_rel
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), color=(10, 80, 140)).save(image_path, "JPEG")
    return (
        VisualAsset(
            row_number=2,
            image_id="aftersun-2022-001",
            old_relative_path=image_rel,
            new_relative_path=image_rel,
            previous_relative_path=image_rel,
            sha256="b" * 64,
            bytes=image_path.stat().st_size,
            category="film-stills",
            group="aftersun-2022",
            batch_or_note="",
            width=32,
            height=18,
            file_name="aftersun-2022-001.jpg",
            file_stem="aftersun-2022-001",
        ),
        asset_root,
    )


def test_contact_sheet_writes_html_and_review_state(tmp_path: Path) -> None:
    visual_asset, asset_root = make_asset(tmp_path)
    cards_root = tmp_path / "analysis-cards" / "cards"
    card = build_card(visual_asset, run_id="visual-test")
    card["editorial_judgment"]["flags"] = ["<script>alert(1)</script>"]
    write_card_pair(card, cards_root)
    decisions_log = tmp_path / "analysis-cards" / "manifests" / "visual-test" / "review-decisions.jsonl"
    append_review_decision(
        decisions_log,
        ReviewDecision(
            image_id="aftersun-2022-001",
            source_sha256="b" * 64,
            status="approved",
            reviewer="tester",
            reason="fixture",
            run_id="visual-test",
            card_schema_version="image_analysis_card.v1",
        ),
    )

    result = generate_contact_sheet(
        cards_root=cards_root,
        asset_root=asset_root,
        review_dir=tmp_path / "review",
        decisions_log=decisions_log,
        review_state_path=tmp_path / "analysis-cards" / "manifests" / "visual-test" / "review-state.tsv",
    )

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert result["card_count"] == 1
    assert "approved" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "../source-assets/film-stills/aftersun-2022/aftersun-2022-001.jpg" in html
    assert (tmp_path / "analysis-cards" / "manifests" / "visual-test" / "review-state.tsv").exists()


def test_contact_sheet_reports_unsafe_card_as_residual(tmp_path: Path) -> None:
    visual_asset, asset_root = make_asset(tmp_path)
    cards_root = tmp_path / "analysis-cards" / "cards"
    card = build_card(visual_asset, run_id="visual-test")
    card["source"]["new_relative_path"] = "../outside.jpg"
    card_dir = cards_root / "film-stills" / "aftersun-2022"
    card_dir.mkdir(parents=True)
    (card_dir / "aftersun-2022-001.json").write_text(json.dumps(card), encoding="utf-8")

    result = generate_contact_sheet(
        cards_root=cards_root,
        asset_root=asset_root,
        review_dir=tmp_path / "review",
        decisions_log=tmp_path / "analysis-cards" / "review-decisions.jsonl",
        review_state_path=tmp_path / "analysis-cards" / "review-state.tsv",
    )

    assert result["card_count"] == 0
    assert result["residual_count"] == 1
    assert (tmp_path / "review" / "residuals.json").exists()
