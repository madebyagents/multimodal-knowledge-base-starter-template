from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dantedash_kh_parity_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dantedash_kh_parity_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_parser_reads_json_assets_envelope(tmp_path: Path) -> None:
    module = _load_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assets": [
                    {"source_sha256": "sha-a"},
                    {"dante_image_id": "img-b"},
                    {"relative_path": "film/image-c.jpg"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert module._read_manifest_keys(manifest) == {"sha-a", "img-b", "film/image-c.jpg"}


def test_manifest_parser_reads_tsv_rows(tmp_path: Path) -> None:
    module = _load_module()
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text("source_sha256\tdante_image_id\nsha-a\timg-a\n\timg-b\n", encoding="utf-8")

    assert module._read_manifest_keys(manifest) == {"sha-a", "img-b"}
