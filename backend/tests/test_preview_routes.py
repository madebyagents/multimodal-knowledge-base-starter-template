from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.kb_backends import KbBackendUnavailable, PreviewLookup, _preview_upload_root
from app.routes.preview import _lookup_file


class UnavailablePreviewGateway:
    def lookup_preview(self, _file_id: str, *, timestamp_s=None):
        raise KbBackendUnavailable("knowledge_hub_preview_not_available")


class MissingGeneratedPreviewGateway:
    def __init__(self, upload_dir: Path, source_path: Path, preview_path: Path) -> None:
        self.upload_dir = upload_dir
        self.source_path = source_path
        self.preview_path = preview_path

    def lookup_preview(self, _file_id: str, *, timestamp_s=None):
        return PreviewLookup(
            path=self.source_path,
            metadata={"id": "img-a", "modality": "image"},
            upload_dir=self.upload_dir,
            preview_path=self.preview_path,
        )


def test_lookup_file_returns_503_when_backend_preview_is_unavailable() -> None:
    with pytest.raises(HTTPException) as exc:
        _lookup_file(UnavailablePreviewGateway(), "img-a")

    assert exc.value.status_code == 503
    assert exc.value.detail == "Knowledge base preview unavailable"


def test_lookup_file_ignores_missing_generated_preview(tmp_path: Path) -> None:
    source_path = tmp_path / "source.jpg"
    source_path.write_bytes(b"fake")
    missing_preview = tmp_path / "missing-preview.jpg"

    lookup = _lookup_file(MissingGeneratedPreviewGateway(tmp_path, source_path, missing_preview), "img-a")

    assert lookup.path == source_path.resolve()
    assert lookup.preview_path is None


def test_lookup_file_refuses_path_outside_preview_roots(tmp_path: Path) -> None:
    source_path = tmp_path / "secret.jpg"
    source_path.write_bytes(b"fake")
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()

    with pytest.raises(HTTPException) as exc:
        _lookup_file(MissingGeneratedPreviewGateway(upload_root, source_path, source_path), "img-a")

    assert exc.value.status_code == 404
    assert exc.value.detail == "File not available"


def test_preview_upload_root_does_not_trust_unknown_file_parent(tmp_path: Path) -> None:
    root = _preview_upload_root(tmp_path / "attacker-controlled" / "secret.jpg")

    assert root == Path("/Users/vidigal/codex/dantedash/uploads")
