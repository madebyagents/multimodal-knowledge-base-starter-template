"""Read-only canonical comparison for governed corpus dry-run artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import docling_kh_lightrag_cag_harness as p0p8


CANONICAL_ARTIFACT_BASENAMES = (
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

RUN_LOCAL_JSON_POINTERS: Mapping[str, tuple[str, ...]] = {
    "black-label-certification.json": ("/run_id", "/source_run"),
    "p0-p8-certification.json": ("/run_id",),
    "phase-ledger.json": ("/run_id",),
}

_JSON_ARTIFACTS = frozenset(RUN_LOCAL_JSON_POINTERS)
_JSONL_ARTIFACTS = frozenset(
    basename for basename in CANONICAL_ARTIFACT_BASENAMES if basename.endswith(".jsonl")
)
_RUN_LOCAL_SENTINEL = "<run-local>"
_REPORT_RUN_ID_LINE = re.compile(rb"(?m)^- Run id: `([^`\r\n]+)`(?=\r?$)")
_REPORT_RUN_ID_CANONICAL = b"- Run id: `<run-local>`"


class GovernedRunDeterminismError(ValueError):
    """Raised when a run cannot satisfy the canonical determinism contract."""


@dataclass(frozen=True)
class GovernedRunDeterminismResult:
    """Canonical digests shared by two equivalent governed runs."""

    artifact_sha256: dict[str, str]
    aggregate_sha256: str


def compare_governed_runs(
    run_one: Path,
    run_two: Path,
    *,
    before_run_one_recheck: Callable[[], None] | None = None,
) -> GovernedRunDeterminismResult:
    """Compare two run directories without writing to either directory.

    ``before_run_one_recheck`` exists so callers can deterministically exercise
    the immutable-run guard. The comparator itself remains read-only.
    """

    run_one_path = Path(run_one)
    run_two_path = Path(run_two)
    _require_distinct_run_roots(run_one_path, run_two_path)
    run_one_snapshot = _read_artifact_snapshot(run_one_path)
    run_one_id = _validated_run_id(run_one_path, run_one_snapshot)
    run_one_raw_hashes = _raw_hashes(run_one_snapshot)
    run_one_canonical = _canonical_hashes(run_one_snapshot)

    comparison_error: GovernedRunDeterminismError | None = None
    run_two_canonical: dict[str, str] | None = None
    try:
        run_two_snapshot = _read_artifact_snapshot(run_two_path)
        run_two_id = _validated_run_id(run_two_path, run_two_snapshot)
        if run_two_id == run_one_id:
            raise GovernedRunDeterminismError("run_ids_must_be_distinct")
        run_two_canonical = _canonical_hashes(run_two_snapshot)
        mismatched = [
            basename
            for basename in CANONICAL_ARTIFACT_BASENAMES
            if run_one_canonical[basename] != run_two_canonical[basename]
        ]
        if mismatched:
            comparison_error = GovernedRunDeterminismError(
                f"canonical_artifact_mismatch:{','.join(mismatched)}"
            )
    except GovernedRunDeterminismError as exc:
        comparison_error = exc

    if before_run_one_recheck is not None:
        before_run_one_recheck()

    try:
        run_one_final_hashes = _raw_hashes(_read_artifact_snapshot(run_one_path))
    except GovernedRunDeterminismError as exc:
        raise GovernedRunDeterminismError(f"run_one_mutated:{exc}") from exc

    if run_one_final_hashes != run_one_raw_hashes:
        changed = sorted(
            basename
            for basename in set(run_one_raw_hashes) | set(run_one_final_hashes)
            if run_one_raw_hashes.get(basename) != run_one_final_hashes.get(basename)
        )
        raise GovernedRunDeterminismError(f"run_one_mutated:{','.join(changed)}")

    if comparison_error is not None:
        raise comparison_error
    if run_two_canonical is None:  # Defensive: every non-error path assigns it.
        raise GovernedRunDeterminismError("run_two_comparison_incomplete")

    aggregate_sha256 = p0p8.stable_hash(dict(sorted(run_one_canonical.items())))
    return GovernedRunDeterminismResult(
        artifact_sha256=dict(run_one_canonical),
        aggregate_sha256=aggregate_sha256,
    )


def _require_distinct_run_roots(run_one: Path, run_two: Path) -> None:
    one = _lstat(run_one, error_code="run_directory_missing")
    two = _lstat(run_two, error_code="run_directory_missing")
    if stat.S_ISLNK(one.st_mode) or stat.S_ISLNK(two.st_mode):
        raise GovernedRunDeterminismError("run_directory_symlink_not_allowed")
    if (one.st_dev, one.st_ino) == (two.st_dev, two.st_ino):
        raise GovernedRunDeterminismError("run_roots_must_be_distinct")


def _validated_run_id(run_dir: Path, snapshot: Mapping[str, bytes]) -> str:
    black = _load_json_object(
        snapshot["black-label-certification.json"],
        "black-label-certification.json",
    )
    p0p8_certification = _load_json_object(
        snapshot["p0-p8-certification.json"],
        "p0-p8-certification.json",
    )
    ledger = _load_json_object(snapshot["phase-ledger.json"], "phase-ledger.json")
    report_matches = list(_REPORT_RUN_ID_LINE.finditer(snapshot["report.md"]))
    if len(report_matches) != 1:
        raise GovernedRunDeterminismError(
            f"report_run_id_line_count:{len(report_matches)}"
        )
    try:
        report_run_id = report_matches[0].group(1).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GovernedRunDeterminismError("report_run_id_not_utf8") from exc
    run_id_values = (
        black.get("run_id"),
        p0p8_certification.get("run_id"),
        ledger.get("run_id"),
        report_run_id,
    )
    if not all(isinstance(value, str) and value for value in run_id_values):
        raise GovernedRunDeterminismError("run_id_internal_mismatch")
    run_ids = set(run_id_values)
    if len(run_ids) != 1:
        raise GovernedRunDeterminismError("run_id_internal_mismatch")
    run_id = next(iter(run_ids))
    if run_dir.name != run_id:
        raise GovernedRunDeterminismError("run_id_directory_mismatch")
    source_run = black.get("source_run")
    source_run_path = PurePosixPath(source_run) if isinstance(source_run, str) else None
    if (
        not isinstance(source_run, str)
        or not source_run
        or "\\" in source_run
        or source_run_path is None
        or source_run_path.is_absolute()
        or any(part in {"", ".", ".."} for part in source_run_path.parts)
        or source_run_path.name != run_id
    ):
        raise GovernedRunDeterminismError("source_run_binding_mismatch")
    return run_id


def _read_artifact_snapshot(run_dir: Path) -> dict[str, bytes]:
    directory_stat = _lstat(run_dir, error_code="run_directory_missing")
    if stat.S_ISLNK(directory_stat.st_mode):
        raise GovernedRunDeterminismError("run_directory_symlink_not_allowed")
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise GovernedRunDeterminismError("run_directory_not_directory")

    entries = {entry.name: entry for entry in run_dir.iterdir()}
    expected = set(CANONICAL_ARTIFACT_BASENAMES)
    actual = set(entries)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise GovernedRunDeterminismError(f"artifact_set_mismatch:{':'.join(details)}")

    return {
        basename: _read_regular_artifact(entries[basename], basename)
        for basename in CANONICAL_ARTIFACT_BASENAMES
    }


def _read_regular_artifact(path: Path, basename: str) -> bytes:
    before = _lstat(path, error_code=f"artifact_missing:{basename}")
    if stat.S_ISLNK(before.st_mode):
        raise GovernedRunDeterminismError(f"artifact_symlink_not_allowed:{basename}")
    if not stat.S_ISREG(before.st_mode):
        raise GovernedRunDeterminismError(f"artifact_not_regular_file:{basename}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GovernedRunDeterminismError(f"artifact_open_failed:{basename}") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise GovernedRunDeterminismError(f"artifact_not_regular_file:{basename}")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise GovernedRunDeterminismError(
                f"artifact_changed_during_read:{basename}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    after_path = _lstat(path, error_code=f"artifact_changed_during_read:{basename}")
    if _artifact_identity(before) != _artifact_identity(after_open):
        raise GovernedRunDeterminismError(f"artifact_changed_during_read:{basename}")
    if _artifact_identity(after_open) != _artifact_identity(after_path):
        raise GovernedRunDeterminismError(f"artifact_changed_during_read:{basename}")
    return content


def _artifact_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def _lstat(path: Path, *, error_code: str) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise GovernedRunDeterminismError(error_code) from exc


def _raw_hashes(snapshot: Mapping[str, bytes]) -> dict[str, str]:
    return {
        basename: hashlib.sha256(content).hexdigest()
        for basename, content in snapshot.items()
    }


def _canonical_hashes(snapshot: Mapping[str, bytes]) -> dict[str, str]:
    return {
        basename: hashlib.sha256(
            _canonical_bytes(basename, snapshot[basename])
        ).hexdigest()
        for basename in CANONICAL_ARTIFACT_BASENAMES
    }


def _canonical_bytes(basename: str, content: bytes) -> bytes:
    if basename in _JSON_ARTIFACTS:
        payload = _load_json_object(content, basename)
        _normalize_json_pointers(payload, RUN_LOCAL_JSON_POINTERS[basename], basename)
        return _encode_json(payload)
    if basename in _JSONL_ARTIFACTS:
        return _canonical_jsonl(content, basename)
    if basename == "report.md":
        return _canonical_report(content)
    raise GovernedRunDeterminismError(f"unsupported_canonical_artifact:{basename}")


def _canonical_jsonl(content: bytes, basename: str) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GovernedRunDeterminismError(f"artifact_not_utf8:{basename}") from exc
    if not text:
        return b""

    encoded_rows: list[bytes] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            raise GovernedRunDeterminismError(
                f"jsonl_blank_row:{basename}:{line_number}"
            )
        row = _load_json_object(line.encode("utf-8"), basename, line_number=line_number)
        encoded_rows.append(_encode_json(row))
    return b"".join(row + b"\n" for row in encoded_rows)


def _load_json_object(
    content: bytes, basename: str, *, line_number: int | None = None
) -> dict[str, Any]:
    label = f"{basename}:{line_number}" if line_number is not None else basename
    try:
        text = content.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=lambda pairs: _mapping_without_duplicates(pairs, label),
            parse_constant=lambda value: _reject_json_constant(value, label),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedRunDeterminismError(f"invalid_json:{label}") from exc
    if not isinstance(payload, dict):
        raise GovernedRunDeterminismError(f"json_object_required:{label}")
    return payload


def _mapping_without_duplicates(
    pairs: Sequence[tuple[str, Any]], label: str
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise GovernedRunDeterminismError(f"duplicate_json_key:{label}:{key}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str, label: str) -> Any:
    raise GovernedRunDeterminismError(f"nonfinite_json_number:{label}:{value}")


def _normalize_json_pointers(
    payload: dict[str, Any], pointers: Sequence[str], basename: str
) -> None:
    for pointer in pointers:
        key = pointer.removeprefix("/")
        if pointer != f"/{key}" or "/" in key or key not in payload:
            raise GovernedRunDeterminismError(
                f"run_local_pointer_missing:{basename}:{pointer}"
            )
        if not isinstance(payload[key], str):
            raise GovernedRunDeterminismError(
                f"run_local_pointer_not_string:{basename}:{pointer}"
            )
        payload[key] = _RUN_LOCAL_SENTINEL


def _encode_json(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GovernedRunDeterminismError("json_canonicalization_failed") from exc
    return encoded.encode("utf-8")


def _canonical_report(content: bytes) -> bytes:
    matches = list(_REPORT_RUN_ID_LINE.finditer(content))
    if len(matches) != 1:
        raise GovernedRunDeterminismError(f"report_run_id_line_count:{len(matches)}")
    match = matches[0]
    return content[: match.start()] + _REPORT_RUN_ID_CANONICAL + content[match.end() :]
