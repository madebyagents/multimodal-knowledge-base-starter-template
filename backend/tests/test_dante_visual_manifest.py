from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from app.dante_visual.manifest import load_visual_manifest, sha256_file


def write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 9), color=(120, 80, 40)).save(path, "JPEG")


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "old_relative_path",
        "new_relative_path",
        "previous_relative_path",
        "sha256",
        "bytes",
        "category",
        "group",
        "batch_or_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def manifest_row(asset_root: Path, relative: str, category: str = "film-stills", group: str = "aftersun-2022") -> dict[str, str]:
    image_path = asset_root / relative
    return {
        "old_relative_path": relative,
        "new_relative_path": relative,
        "previous_relative_path": relative,
        "sha256": sha256_file(image_path),
        "bytes": str(image_path.stat().st_size),
        "category": category,
        "group": group,
        "batch_or_note": "",
    }


def test_load_visual_manifest_accepts_valid_jpg(tmp_path: Path) -> None:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/aftersun-2022-001.jpg"
    write_image(asset_root / image_rel)
    manifest_path = asset_root / "asset-manifest.tsv"
    write_manifest(manifest_path, [manifest_row(asset_root, image_rel)])

    manifest = load_visual_manifest(manifest_path, asset_root)

    assert manifest.is_valid
    assert manifest.summary()["total_assets"] == 1
    assert manifest.assets[0].image_id == "aftersun-2022-001"
    assert manifest.assets[0].width == 16


def test_load_visual_manifest_rejects_traversal(tmp_path: Path) -> None:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/aftersun-2022-001.jpg"
    write_image(asset_root / image_rel)
    row = manifest_row(asset_root, image_rel)
    row["new_relative_path"] = "../outside.jpg"
    manifest_path = asset_root / "asset-manifest.tsv"
    write_manifest(manifest_path, [row])

    manifest = load_visual_manifest(manifest_path, asset_root)

    assert not manifest.is_valid
    assert any(issue.code == "unsafe_manifest_value" for issue in manifest.issues)


def test_load_visual_manifest_reports_duplicate_current_path(tmp_path: Path) -> None:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/aftersun-2022-001.jpg"
    write_image(asset_root / image_rel)
    row = manifest_row(asset_root, image_rel)
    manifest_path = asset_root / "asset-manifest.tsv"
    write_manifest(manifest_path, [row, row])

    manifest = load_visual_manifest(manifest_path, asset_root)

    assert not manifest.is_valid
    assert any(issue.code == "duplicate_current_path" for issue in manifest.issues)


def test_load_visual_manifest_rejects_nested_card_collision_path(tmp_path: Path) -> None:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/subdir/aftersun-2022-001.jpg"
    write_image(asset_root / image_rel)
    manifest_path = asset_root / "asset-manifest.tsv"
    write_manifest(manifest_path, [manifest_row(asset_root, image_rel)])

    manifest = load_visual_manifest(manifest_path, asset_root)

    assert not manifest.is_valid
    assert any(issue.code == "path_group_mismatch" for issue in manifest.issues)


def test_load_visual_manifest_rejects_unsafe_file_stem(tmp_path: Path) -> None:
    asset_root = tmp_path / "source-assets"
    image_rel = "film-stills/aftersun-2022/Frame_001.jpg"
    write_image(asset_root / image_rel)
    manifest_path = asset_root / "asset-manifest.tsv"
    write_manifest(manifest_path, [manifest_row(asset_root, image_rel)])

    manifest = load_visual_manifest(manifest_path, asset_root)

    assert not manifest.is_valid
    assert any(issue.code == "unsafe_file_stem" for issue in manifest.issues)
