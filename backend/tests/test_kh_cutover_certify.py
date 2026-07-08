from __future__ import annotations

import importlib.util
from pathlib import Path

from app.kb import SearchResult


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dantedash_kh_cutover_certify.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dantedash_kh_cutover_certify", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _EmptyKb:
    def search_text(self, _query: str, *, top_k: int):
        return []


class _FailingKb:
    def search_text(self, _query: str, *, top_k: int):
        raise RuntimeError("boom")


class _HitKb:
    def search_text(self, _query: str, *, top_k: int):
        return [
            SearchResult(
                node_id="node-a",
                score=0.9,
                modality="image",
                metadata={"id": "file-a", "source_sha256": "sha-a", "original_name": "A", "modality": "image"},
                snippet="alpha",
            )
        ]


class _ImageCollection:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path

    def get(self, **_kwargs):
        return {
            "metadatas": [
                {
                    "id": "file-a",
                    "source_sha256": "sha-a",
                    "modality": "image",
                    "file_path": str(self.image_path),
                }
            ]
        }


class _ImageHitKb(_HitKb):
    def __init__(self, image_path: Path) -> None:
        self.collection = _ImageCollection(image_path)

    def search_image(self, _image_path: str, *, top_k: int):
        return self.search_text("image", top_k=top_k)


class _Client:
    def __init__(self, items):
        self.items = items

    def retrieve(self, _payload):
        return {"ok": True, "data": {"items": self.items}}


class _ImageClient(_Client):
    def dantedash_search_packages_by_image(self, _image_path: str, *, top_k: int):
        del top_k
        return {"ok": True, "data": {"items": self.items}}


def test_query_suite_fails_when_chroma_baseline_is_empty_or_errors() -> None:
    module = _load_module()

    empty_rows = module._run_query_suite(_EmptyKb(), _Client([]), top_k=1)
    failing_rows = module._run_query_suite(_FailingKb(), _Client([]), top_k=1)

    assert all(row["score"] == 0.0 and row["passed"] is False for row in empty_rows)
    assert {row["chroma_baseline_status"] for row in empty_rows} == {"empty"}
    assert all(row["score"] == 0.0 and row["passed"] is False for row in failing_rows)
    assert {row["chroma_baseline_status"] for row in failing_rows} == {"failed"}


def test_query_suite_can_pass_when_assets_overlap() -> None:
    module = _load_module()

    rows = module._run_query_suite(_HitKb(), _Client([{"metadata": {"source_sha256": "sha-a"}}]), top_k=1)

    assert all(row["score"] == 1.0 and row["passed"] is True for row in rows)


def test_image_query_suite_can_pass_when_assets_overlap(tmp_path: Path) -> None:
    module = _load_module()
    image_path = tmp_path / "query.jpg"
    image_path.write_bytes(b"fake-image")

    rows = module._run_image_query_suite(
        _ImageHitKb(image_path),
        _ImageClient([{"metadata": {"source_sha256": "sha-a"}}]),
        top_k=1,
    )

    assert rows == [
        {
            "name": "image_query_sample_1",
            "query": "file-a",
            "query_type": "image",
            "critical": True,
            "threshold": 0.8,
            "chroma_returned": 1,
            "knowledge_hub_ok": True,
            "knowledge_hub_route": "dantedash_packages_search_image",
            "knowledge_hub_returned": 1,
            "asset_recall": 1.0,
            "asset_precision": 1.0,
            "score": 1.0,
            "passed": True,
            "chroma_error": None,
            "chroma_baseline_status": "ok",
            "missing_from_knowledge_hub_count": 0,
        }
    ]


def test_image_query_suite_failure_marks_compatibility_reason(tmp_path: Path) -> None:
    module = _load_module()
    image_path = tmp_path / "query.jpg"
    image_path.write_bytes(b"fake-image")

    rows = module._run_image_query_suite(
        _ImageHitKb(image_path),
        _ImageClient([{"metadata": {"source_sha256": "other-sha"}}]),
        top_k=1,
    )
    assert rows[0]["passed"] is False
    assert rows[0]["missing_from_knowledge_hub_count"] == 1

    reason = module._image_query_compatibility_reason(
        route_available=True,
        image_query_rows=rows,
    )

    assert "image_query_sample_1" in reason
    assert "score=0.0" in reason
    assert "missing=1" in reason


def test_public_no_leak_scan_detects_sensitive_strings() -> None:
    module = _load_module()

    clean = module._scan_public_no_leak({"status": "ok", "relative_path": "safe/file.md"})
    dirty = module._scan_public_no_leak({"status": "ok", "message": "postgresql://secret.example"})

    assert clean["checks_complete"] is True
    assert clean["leak_count"] == 0
    assert dirty["leak_count"] >= 1
    assert dirty["public_errors_safe"] is False
