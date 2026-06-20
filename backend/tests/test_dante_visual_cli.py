from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_ROOT = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from dante_visual_analysis_harness import resolve_paths, select_assets  # noqa: E402


def test_review_decision_paths_are_stable_across_run_ids(tmp_path: Path) -> None:
    dataset = Path("commercial-film-production-kb/13-visual-reference-assets")

    first = resolve_paths(tmp_path, dataset, "visual-one")
    second = resolve_paths(tmp_path, dataset, "visual-two")

    assert first["preflight_path"] != second["preflight_path"]
    assert first["decisions_log"] == second["decisions_log"]
    assert first["review_state_path"] == second["review_state_path"]


def test_select_assets_stratified_round_robins_groups() -> None:
    assets = [
        SimpleNamespace(category="film-stills", group="a", image_id="a1"),
        SimpleNamespace(category="film-stills", group="a", image_id="a2"),
        SimpleNamespace(category="film-stills", group="b", image_id="b1"),
        SimpleNamespace(category="film-stills", group="b", image_id="b2"),
        SimpleNamespace(category="shotdeck-batches", group="c", image_id="c1"),
    ]

    selected = select_assets(assets, sample=4, sample_mode="stratified")

    assert [asset.image_id for asset in selected] == ["a1", "b1", "c1", "a2"]
