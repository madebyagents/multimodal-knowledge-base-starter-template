from __future__ import annotations

import json

from app.kb_parity import (
    audit_kb,
    classify_rows,
    evaluate_result_parity,
    package_key_from_metadata,
    vector_provenance_status,
    write_audit_manifests,
)


class _FakeCollection:
    def __init__(self, ids, metadatas):
        self._ids = ids
        self._metadatas = metadatas

    def get(self, include=None):
        return {"ids": self._ids, "metadatas": self._metadatas}


class _FakeKb:
    def __init__(self, ids, metadatas):
        self.collection = _FakeCollection(ids, metadatas)

    def count_by_modality(self):
        return {"image": 1, "text": 2}


def test_classify_rows_marks_canonical_orphaned_duplicate_and_unsupported():
    ids = ["img-1", "card-1", "card-2", "local-1", "dup", "dup"]
    metadatas = [
        {
            "file_id": "img-1",
            "modality": "image",
            "source_sha256": "sha-1",
            "embedding_model": "voyage-multimodal-3.5",
            "embedding_dimensions": 1024,
        },
        {
            "file_id": "card-1",
            "modality": "text",
            "source_sha256": "sha-1",
            "linked_image_file_id": "img-1",
        },
        {
            "file_id": "card-2",
            "modality": "text",
            "source_sha256": "sha-2",
            "linked_image_file_id": "missing-image",
        },
        {"file_id": "local-1", "modality": "audio", "source_sha256": "sha-3"},
        {"file_id": "dup-a", "modality": "image", "source_sha256": "sha-4"},
        {"file_id": "dup-b", "modality": "image", "source_sha256": "sha-5"},
    ]

    rows = classify_rows(ids, metadatas)

    by_node = {row.node_id: row for row in rows}
    assert by_node["img-1"].row_class == "canonical"
    assert by_node["img-1"].vector_provenance == "verified"
    assert by_node["card-1"].row_class == "canonical"
    assert by_node["card-2"].row_class == "orphaned"
    assert by_node["local-1"].row_class == "unsupported"
    assert [row.row_class for row in rows if row.node_id == "dup"] == ["duplicate", "duplicate"]


def test_classify_rows_treats_metadata_id_as_link_target():
    rows = classify_rows(
        ["node-image", "node-card"],
        [
            {"id": "image-file-id", "modality": "image", "source_sha256": "sha-1"},
            {
                "id": "card-file-id",
                "modality": "text",
                "source_sha256": "sha-1",
                "linked_image_file_id": "image-file-id",
            },
        ],
    )

    assert [row.row_class for row in rows] == ["canonical", "canonical"]


def test_classify_rows_marks_knowledge_hub_relationships_when_manifest_keys_exist():
    rows = classify_rows(
        ["node-a", "node-b"],
        [
            {"id": "file-a", "modality": "image", "source_sha256": "sha-a"},
            {"id": "file-b", "modality": "image", "source_sha256": "sha-b"},
        ],
        kh_package_keys={"sha-a"},
    )

    assert [row.kh_relationship for row in rows] == ["matched", "missing_in_kh"]


def test_classify_rows_requires_layer_match_when_kh_layers_are_present():
    rows = classify_rows(
        ["node-image", "node-card"],
        [
            {"id": "file-image", "modality": "image", "source_sha256": "sha-a"},
            {
                "id": "file-card",
                "modality": "text",
                "artifact_type": "visual_analysis_bundle",
                "source_sha256": "sha-a",
                "linked_image_file_id": "file-image",
            },
        ],
        kh_package_layers={"sha-a": {"image:unknown"}},
    )

    assert [row.kh_relationship for row in rows] == ["matched", "missing_layer_in_kh"]


def test_vector_provenance_status_distinguishes_partial_and_unknown():
    assert vector_provenance_status({"source_sha256": "sha-a"}) == "partial"
    assert vector_provenance_status({}) == "embedding_provenance_unknown"


def test_audit_writes_private_summary_and_manifest(tmp_path):
    kb = _FakeKb(
        ["img-1", "card-1"],
        [
            {"file_id": "img-1", "modality": "image", "source_sha256": "sha-1"},
            {"file_id": "card-1", "modality": "text", "source_sha256": "sha-1", "linked_image_file_id": "img-1"},
        ],
    )

    audit = audit_kb(kb, run_id="test-run")
    paths = write_audit_manifests(audit, tmp_path)

    summary = json.loads((tmp_path / "kh-parity-audit-summary.json").read_text())
    manifest = (tmp_path / "kh-parity-audit-manifest.tsv").read_text()

    assert paths["summary"].endswith("kh-parity-audit-summary.json")
    assert summary["run_id"] == "test-run"
    assert summary["total_rows"] == 2
    assert summary["by_class"] == {"canonical": 2}
    assert "node_id\tfile_id\tmodality" in manifest
    assert "card-1" in manifest


def test_evaluate_result_parity_uses_visual_package_keys():
    chroma_results = [
        {"metadata": {"source_sha256": "sha-1"}},
        {"metadata": {"source_sha256": "sha-2"}},
        {"metadata": {"source_sha256": "sha-3"}},
    ]
    kh_results = [
        {"metadata": {"source_sha256": "sha-1"}},
        {"metadata": {"source_sha256": "sha-3"}},
        {"metadata": {"source_sha256": "sha-extra"}},
    ]

    result = evaluate_result_parity(chroma_results, kh_results, min_asset_overlap=0.7)

    assert result["asset_recall"] == 2 / 3
    assert result["asset_precision"] == 2 / 3
    assert result["passed"] is False
    assert result["missing_from_knowledge_hub"] == ["sha-2"]
    assert result["extra_in_knowledge_hub"] == ["sha-extra"]


def test_package_key_prefers_stable_visual_package_metadata():
    assert package_key_from_metadata({"source_sha256": "sha-a", "file_id": "file-a"}) == "sha-a"
    assert package_key_from_metadata({"dante_image_id": "barry-001", "id": "node-a"}) == "barry-001"
