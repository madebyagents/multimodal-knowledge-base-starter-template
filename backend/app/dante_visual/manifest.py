"""Manifest inventory and path-safety helpers for Dante visual assets."""
from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError

REQUIRED_COLUMNS = (
    "old_relative_path",
    "new_relative_path",
    "previous_relative_path",
    "sha256",
    "bytes",
    "category",
    "group",
    "batch_or_note",
)

SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
IMAGE_SUFFIXES = {".jpg", ".jpeg"}

IssueSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class ManifestIssue:
    severity: IssueSeverity
    code: str
    message: str
    row_number: int | None = None
    path: str | None = None


@dataclass(frozen=True)
class VisualAsset:
    row_number: int
    image_id: str
    old_relative_path: str
    new_relative_path: str
    previous_relative_path: str
    sha256: str
    bytes: int
    category: str
    group: str
    batch_or_note: str
    width: int
    height: int
    file_name: str
    file_stem: str

    @property
    def card_relative_dir(self) -> Path:
        return Path(self.category) / self.group

    @property
    def card_json_relative_path(self) -> Path:
        return self.card_relative_dir / f"{self.file_stem}.json"

    @property
    def card_markdown_relative_path(self) -> Path:
        return self.card_relative_dir / f"{self.file_stem}.md"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class VisualManifest:
    manifest_path: Path
    asset_root: Path
    assets: list[VisualAsset] = field(default_factory=list)
    issues: list[ManifestIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def summary(self) -> dict[str, object]:
        by_category = Counter(asset.category for asset in self.assets)
        by_group = Counter(asset.group for asset in self.assets)
        by_issue = Counter(issue.code for issue in self.issues)
        return {
            "manifest_path": str(self.manifest_path),
            "asset_root": str(self.asset_root),
            "total_assets": len(self.assets),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "by_category": dict(sorted(by_category.items())),
            "group_count": len(by_group),
            "largest_groups": dict(by_group.most_common(20)),
            "issues_by_code": dict(sorted(by_issue.items())),
        }


def validate_run_id(run_id: str) -> str:
    if not SAFE_RUN_ID_RE.match(run_id):
        raise ValueError(f"Unsafe run id: {run_id!r}")
    return run_id


def validate_slug(value: str, *, field_name: str) -> str:
    if not SAFE_SLUG_RE.match(value):
        raise ValueError(f"Unsafe {field_name}: {value!r}")
    return value


def safe_relative_path(value: str, *, field_name: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"{field_name} must be relative: {value!r}")
    if any(part in {"", ".", ".."} for part in raw.parts):
        raise ValueError(f"{field_name} contains unsafe path parts: {value!r}")
    return raw


def resolve_inside(root: Path, relative_path: Path) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes root: {relative_path}") from exc
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def load_visual_manifest(manifest_path: Path, asset_root: Path) -> VisualManifest:
    manifest = VisualManifest(manifest_path=manifest_path.resolve(), asset_root=asset_root.resolve())
    if not manifest.manifest_path.exists():
        manifest.issues.append(
            ManifestIssue("error", "manifest_missing", "Manifest file does not exist", path=str(manifest_path))
        )
        return manifest

    with manifest.manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing_columns:
            manifest.issues.append(
                ManifestIssue(
                    "error",
                    "manifest_columns_missing",
                    f"Manifest is missing required columns: {', '.join(missing_columns)}",
                    path=str(manifest_path),
                )
            )
            return manifest

        seen_paths: dict[str, int] = {}
        seen_image_ids: dict[str, int] = {}
        seen_hashes: dict[str, int] = {}
        for row_number, row in enumerate(reader, start=2):
            asset = _row_to_asset(row, row_number, manifest.asset_root, manifest.issues)
            if asset is None:
                continue

            previous_path_row = seen_paths.get(asset.new_relative_path)
            if previous_path_row is not None:
                manifest.issues.append(
                    ManifestIssue(
                        "error",
                        "duplicate_current_path",
                        f"Duplicate current path also seen on row {previous_path_row}",
                        row_number=row_number,
                        path=asset.new_relative_path,
                    )
                )
            else:
                seen_paths[asset.new_relative_path] = row_number

            previous_image_id_row = seen_image_ids.get(asset.image_id)
            if previous_image_id_row is not None:
                manifest.issues.append(
                    ManifestIssue(
                        "warning",
                        "duplicate_image_id",
                        f"Duplicate image_id also seen on row {previous_image_id_row}",
                        row_number=row_number,
                        path=asset.new_relative_path,
                    )
                )
            else:
                seen_image_ids[asset.image_id] = row_number

            previous_hash_row = seen_hashes.get(asset.sha256)
            if previous_hash_row is not None:
                manifest.issues.append(
                    ManifestIssue(
                        "warning",
                        "duplicate_sha256",
                        f"Duplicate SHA-256 also seen on row {previous_hash_row}",
                        row_number=row_number,
                        path=asset.new_relative_path,
                    )
                )
            else:
                seen_hashes[asset.sha256] = row_number

            manifest.assets.append(asset)

    return manifest


def _row_to_asset(
    row: dict[str, str],
    row_number: int,
    asset_root: Path,
    issues: list[ManifestIssue],
) -> VisualAsset | None:
    try:
        category = validate_slug(row["category"], field_name="category")
        group = validate_slug(row["group"], field_name="group")
        relative_path = safe_relative_path(row["new_relative_path"], field_name="new_relative_path")
    except ValueError as exc:
        issues.append(ManifestIssue("error", "unsafe_manifest_value", str(exc), row_number=row_number))
        return None

    if relative_path.suffix.lower() not in IMAGE_SUFFIXES:
        issues.append(
            ManifestIssue(
                "error",
                "unsupported_image_suffix",
                "Visual assets must be JPG/JPEG files",
                row_number=row_number,
                path=str(relative_path),
            )
        )
        return None

    if len(relative_path.parts) != 3 or relative_path.parts[0] != category or relative_path.parts[1] != group:
        issues.append(
            ManifestIssue(
                "error",
                "path_group_mismatch",
                "Path must be exactly category/group/file from manifest row",
                row_number=row_number,
                path=str(relative_path),
            )
        )
        return None

    try:
        image_path = resolve_inside(asset_root, relative_path)
    except ValueError as exc:
        issues.append(ManifestIssue("error", "path_escape", str(exc), row_number=row_number, path=str(relative_path)))
        return None

    if not image_path.exists():
        issues.append(
            ManifestIssue("error", "image_missing", "Image file does not exist", row_number=row_number, path=str(relative_path))
        )
        return None
    if not image_path.is_file():
        issues.append(
            ManifestIssue("error", "not_a_file", "Manifest path is not a file", row_number=row_number, path=str(relative_path))
        )
        return None

    try:
        expected_bytes = int(row["bytes"])
    except ValueError:
        issues.append(
            ManifestIssue("error", "invalid_bytes", "bytes field must be an integer", row_number=row_number, path=str(relative_path))
        )
        return None

    actual_bytes = image_path.stat().st_size
    if actual_bytes != expected_bytes:
        issues.append(
            ManifestIssue(
                "error",
                "byte_mismatch",
                f"Expected {expected_bytes} bytes but found {actual_bytes}",
                row_number=row_number,
                path=str(relative_path),
            )
        )
        return None

    actual_sha = sha256_file(image_path)
    expected_sha = row["sha256"].strip().lower()
    if actual_sha != expected_sha:
        issues.append(
            ManifestIssue(
                "error",
                "sha256_mismatch",
                "Image SHA-256 does not match manifest",
                row_number=row_number,
                path=str(relative_path),
            )
        )
        return None

    try:
        width, height = image_dimensions(image_path)
    except (UnidentifiedImageError, OSError) as exc:
        issues.append(
            ManifestIssue(
                "error",
                "image_unreadable",
                f"Pillow could not read image: {exc}",
                row_number=row_number,
                path=str(relative_path),
            )
        )
        return None

    file_name = relative_path.name
    file_stem = relative_path.stem
    try:
        validate_slug(file_stem, field_name="file_stem")
    except ValueError as exc:
        issues.append(
            ManifestIssue("error", "unsafe_file_stem", str(exc), row_number=row_number, path=str(relative_path))
        )
        return None
    return VisualAsset(
        row_number=row_number,
        image_id=file_stem,
        old_relative_path=row["old_relative_path"],
        new_relative_path=str(relative_path),
        previous_relative_path=row["previous_relative_path"],
        sha256=expected_sha,
        bytes=actual_bytes,
        category=category,
        group=group,
        batch_or_note=row["batch_or_note"],
        width=width,
        height=height,
        file_name=file_name,
        file_stem=file_stem,
    )
