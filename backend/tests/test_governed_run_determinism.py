from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import docling_kh_lightrag_cag_harness as p0p8
from app import governed_run_determinism as subject


EXPECTED_ARTIFACTS = (
    "black-label-asset-registry.jsonl",
    "black-label-card-manifest.jsonl",
    "black-label-certification.json",
    "black-label-eval-suite.jsonl",
    "cag-pack-candidates.jsonl",
    "cag-pack-manifest.jsonl",
    "docling-normalized-output.jsonl",
    "docling-pdf-page-image-crosswalk.jsonl",
    "governed-rights-registry.jsonl",
    "governed-source-inventory.jsonl",
    "kh-multimodal-apply-plan.jsonl",
    "lightrag-card-apply-plan.jsonl",
    "p0-p8-certification.json",
    "package-crosswalk.jsonl",
    "phase-ledger.json",
    "report.md",
    "visual-enrichment-queue.jsonl",
)


def _write_run(run_dir: Path, run_id: str, *, alternate_encoding: bool = False) -> None:
    run_dir.mkdir(parents=True)
    for basename in EXPECTED_ARTIFACTS:
        path = run_dir / basename
        if basename == "black-label-certification.json":
            payload = {
                "run_id": run_id,
                "source_run": f"logs/governed-corpus-rollout/{run_id}",
                "stable": {"z": "café", "a": [1, 2]},
            }
            _write_json(path, payload, alternate_encoding=alternate_encoding)
        elif basename in {"p0-p8-certification.json", "phase-ledger.json"}:
            payload = {
                "run_id": run_id,
                "stable": {"z": "café", "a": [1, 2]},
            }
            _write_json(path, payload, alternate_encoding=alternate_encoding)
        elif basename == "report.md":
            path.write_bytes(
                (
                    "# Governed Corpus P0 Report\n\n"
                    f"- Run id: `{run_id}`\n"
                    "- Stable result: `blocked_no_mutation`\n"
                ).encode("utf-8")
            )
        else:
            rows = [
                {"artifact": basename, "position": 1, "value": "café"},
                {"artifact": basename, "position": 2, "nested": {"z": 2, "a": 1}},
            ]
            _write_jsonl(path, rows, alternate_encoding=alternate_encoding)


def _write_json(path: Path, payload: object, *, alternate_encoding: bool) -> None:
    if alternate_encoding:
        content = json.dumps(payload, ensure_ascii=False, indent=3) + "\n"
    else:
        content = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    path.write_text(content, encoding="utf-8")


def _write_jsonl(
    path: Path, rows: list[dict[str, object]], *, alternate_encoding: bool
) -> None:
    encoded_rows: list[str] = []
    for row in rows:
        if alternate_encoding:
            reordered = dict(reversed(list(row.items())))
            encoded_rows.append(
                json.dumps(reordered, ensure_ascii=False, separators=(", ", ": "))
            )
        else:
            encoded_rows.append(
                json.dumps(row, ensure_ascii=True, separators=(",", ":"))
            )
    terminator = "\n" if alternate_encoding else ""
    path.write_text("\n".join(encoded_rows) + terminator, encoding="utf-8")


def _raw_bytes(run_dir: Path) -> dict[str, bytes]:
    return {
        basename: (run_dir / basename).read_bytes() for basename in EXPECTED_ARTIFACTS
    }


def test_distinct_runs_have_equal_canonical_digests_without_writes(
    tmp_path: Path,
) -> None:
    run_one = tmp_path / "first-root" / "run-alpha"
    run_two = tmp_path / "second-root" / "run-beta"
    _write_run(run_one, "run-alpha")
    _write_run(run_two, "run-beta", alternate_encoding=True)
    before_one = _raw_bytes(run_one)
    before_two = _raw_bytes(run_two)

    result = subject.compare_governed_runs(run_one, run_two)

    assert subject.CANONICAL_ARTIFACT_BASENAMES == EXPECTED_ARTIFACTS
    assert set(result.artifact_sha256) == set(EXPECTED_ARTIFACTS)
    assert result.aggregate_sha256 == p0p8.stable_hash(
        dict(sorted(result.artifact_sha256.items()))
    )
    assert _raw_bytes(run_one) == before_one
    assert _raw_bytes(run_two) == before_two


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        ("missing", "missing=visual-enrichment-queue.jsonl"),
        ("extra", "extra=unexpected.json"),
    ],
)
def test_rejects_missing_or_extra_artifacts(
    tmp_path: Path,
    mutation: str,
    expected_fragment: str,
) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    if mutation == "missing":
        (run_two / "visual-enrichment-queue.jsonl").unlink()
    else:
        (run_two / "unexpected.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(subject.GovernedRunDeterminismError, match=expected_fragment):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_unlisted_json_field_drift(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "black-label-certification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stable"]["a"] = [1, 3]
    _write_json(path, payload, alternate_encoding=False)

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="canonical_artifact_mismatch:black-label-certification.json",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_jsonl_order_drift(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "governed-source-inventory.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="canonical_artifact_mismatch:governed-source-inventory.jsonl",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_report_drift_outside_run_id_line(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "report.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "blocked_no_mutation", "green_dry_run"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="canonical_artifact_mismatch:report.md",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_detects_run_one_mutation_before_final_recheck(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")

    def mutate_run_one() -> None:
        path = run_one / "black-label-card-manifest.jsonl"
        path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="run_one_mutated:black-label-card-manifest.jsonl",
    ):
        subject.compare_governed_runs(
            run_one,
            run_two,
            before_run_one_recheck=mutate_run_one,
        )


def test_rejects_the_same_physical_run_root(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-one"
    _write_run(run_dir, "run-one")

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="run_roots_must_be_distinct",
    ):
        subject.compare_governed_runs(run_dir, run_dir)


def test_rejects_distinct_roots_with_the_same_run_id(tmp_path: Path) -> None:
    run_one = tmp_path / "first-root" / "same-run"
    run_two = tmp_path / "second-root" / "same-run"
    _write_run(run_one, "same-run")
    _write_run(run_two, "same-run")

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="run_ids_must_be_distinct",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_internally_incoherent_run_ids(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "p0-p8-certification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_id"] = "another-run"
    _write_json(path, payload, alternate_encoding=False)

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="run_id_internal_mismatch",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_source_run_not_bound_to_run_id(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "black-label-certification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_run"] = "logs/governed-corpus-rollout/not-run-two"
    _write_json(path, payload, alternate_encoding=False)

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="source_run_binding_mismatch",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_source_run_traversal_even_when_basename_matches(
    tmp_path: Path,
) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "black-label-certification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_run"] = "../../outside/run-two"
    _write_json(path, payload, alternate_encoding=False)

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="source_run_binding_mismatch",
    ):
        subject.compare_governed_runs(run_one, run_two)


def test_rejects_unhashable_run_id_without_crashing(tmp_path: Path) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "p0-p8-certification.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_id"] = []
    _write_json(path, payload, alternate_encoding=False)

    with pytest.raises(
        subject.GovernedRunDeterminismError,
        match="run_id_internal_mismatch",
    ):
        subject.compare_governed_runs(run_one, run_two)


@pytest.mark.parametrize("artifact_kind", ["symlink", "directory"])
def test_rejects_symlink_and_nonregular_artifacts(
    tmp_path: Path, artifact_kind: str
) -> None:
    run_one = tmp_path / "run-one"
    run_two = tmp_path / "run-two"
    _write_run(run_one, "run-one")
    _write_run(run_two, "run-two")
    path = run_two / "black-label-eval-suite.jsonl"
    path.unlink()
    if artifact_kind == "symlink":
        path.symlink_to(run_two / "black-label-card-manifest.jsonl")
        expected = "artifact_symlink_not_allowed:black-label-eval-suite.jsonl"
    else:
        path.mkdir()
        expected = "artifact_not_regular_file:black-label-eval-suite.jsonl"

    with pytest.raises(subject.GovernedRunDeterminismError, match=expected):
        subject.compare_governed_runs(run_one, run_two)
