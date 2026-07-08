from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import docling_cinema_batch as subject


def make_pdf(root: Path, relative: str, body: bytes = b"%PDF fixture") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def patch_probe_and_hash(monkeypatch, probes: dict[str, subject.PdfProbe]) -> None:
    def fake_probe(path: Path, *, max_pages: int = subject.DEFAULT_PROBE_PAGES) -> subject.PdfProbe:
        return probes[path.name]

    def fake_hash(path: Path) -> str:
        digest = f"{path.name}:hash"
        return digest.encode().hex().ljust(64, "0")[:64]

    monkeypatch.setattr(subject, "probe_pdf", fake_probe)
    monkeypatch.setattr(subject, "sha256_file", fake_hash)


def make_row(**overrides) -> subject.InventoryRow:
    values = {
        "row_number": 1,
        "source_relative_path": "topic/file.pdf",
        "topic_folder": "topic",
        "source_root_label": "cinema",
        "source_sha256": "a" * 64,
        "bytes": 10,
        "page_count": 10,
        "sampled_text_chars": 1_000,
        "docling_level": "A",
        "selection_reason": "clean_short_text_first",
        "is_large": False,
        "text_probe_status": "healthy",
    }
    values.update(overrides)
    return subject.InventoryRow(**values)


def test_inventory_classifies_a_c_b_and_large_rows(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    clean = make_pdf(root, "teaching/glossary.pdf", b"a" * 100)
    canonical = make_pdf(root, "history/canonical.pdf", b"b" * 100)
    weak = make_pdf(root, "scans/scan.pdf", b"c" * 100)
    probes = {
        clean.name: subject.PdfProbe(page_count=30, sampled_text_chars=2_000),
        canonical.name: subject.PdfProbe(page_count=320, sampled_text_chars=3_000),
        weak.name: subject.PdfProbe(page_count=80, sampled_text_chars=10),
    }
    patch_probe_and_hash(monkeypatch, probes)

    rows = subject.inventory_source(root)

    by_name = {Path(row.source_relative_path).name: row for row in rows}
    assert by_name["glossary.pdf"].docling_level == "A"
    assert by_name["glossary.pdf"].selection_reason == "clean_short_text_first"
    assert by_name["canonical.pdf"].docling_level == "C"
    assert by_name["canonical.pdf"].is_large is True
    assert by_name["scan.pdf"].docling_level == "B"
    assert by_name["scan.pdf"].text_probe_status == "weak"


def test_inventory_blocks_path_outside_source_root(tmp_path: Path) -> None:
    root = tmp_path / "cinema"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"pdf")

    try:
        subject.inventory_source(root, only_relative_paths=["../outside.pdf"])
    except ValueError as exc:
        assert "path_outside_source_root" in str(exc)
    else:
        raise AssertionError("expected outside path rejection")


def test_discover_pdfs_empty_explicit_selection_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")

    assert subject.discover_pdfs(root, only_relative_paths=[]) == []


def test_inventory_marks_duplicate_hashes_visible(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    first = make_pdf(root, "a/first.pdf")
    second = make_pdf(root, "b/second.pdf")
    probes = {
        first.name: subject.PdfProbe(page_count=40, sampled_text_chars=2_000),
        second.name: subject.PdfProbe(page_count=40, sampled_text_chars=2_000),
    }
    monkeypatch.setattr(subject, "probe_pdf", lambda path, *, max_pages=3: probes[path.name])
    monkeypatch.setattr(subject, "sha256_file", lambda _path: "a" * 64)

    rows = subject.inventory_source(root)

    assert [row.status for row in rows] == ["queued", "skipped_duplicate_in_run"]
    assert len(rows) == 2


def test_inventory_force_level_changes_resume_key(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "teaching/glossary.pdf")
    patch_probe_and_hash(monkeypatch, {"glossary.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})
    existing_successes = {(subject.sha256_file(root / "teaching/glossary.pdf"), "A")}

    rows = subject.inventory_source(root, existing_successes=existing_successes, force_level="C")

    assert rows[0].docling_level == "C"
    assert rows[0].status == "queued"
    assert rows[0].selection_reason.startswith("operator_forced_level_c_from_a:")


def test_inventory_manifest_level_preserves_retry_lane_and_order(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "z/second.pdf")
    make_pdf(root, "a/first.pdf")
    patch_probe_and_hash(
        monkeypatch,
        {
            "first.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000),
            "second.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000),
        },
    )

    rows = subject.inventory_source(
        root,
        only_relative_paths=["z/second.pdf", "a/first.pdf"],
        manifest_levels={"z/second.pdf": "C", "a/first.pdf": "A"},
    )

    assert [row.source_relative_path for row in rows] == ["z/second.pdf", "a/first.pdf"]
    assert [row.docling_level for row in rows] == ["C", "A"]
    assert rows[0].selection_reason.startswith("manifest_prior_level_c_from_a:")


def test_select_manifest_rows_filters_status_and_level(tmp_path: Path) -> None:
    rows = [
        make_row(
            row_number=1,
            source_relative_path="topic/converted.pdf",
            source_sha256="a" * 64,
            docling_level="A",
            status="converted",
        ),
        make_row(
            row_number=2,
            source_relative_path="topic/pending.pdf",
            source_sha256="b" * 64,
            page_count=300,
            docling_level="C",
            selection_reason="main_cinema_hybrid_default",
            is_large=True,
            status="queued",
        ),
    ]
    run_dir = tmp_path / "previous-run"
    subject.write_artifacts(run_dir, rows, subject.summary_payload(rows, run_dir=run_dir, apply=True, smoke=False))

    selected = subject.select_manifest_rows(
        run_dir,
        statuses={"queued"},
        levels={"C"},
    )

    assert selected == [
        subject.ManifestSelection(
            row_number=2,
            source_relative_path="topic/pending.pdf",
            source_sha256="b" * 64,
            docling_level="C",
        )
    ]


def test_select_manifest_rows_keeps_first_duplicate_relative_path(tmp_path: Path) -> None:
    rows = [
        make_row(
            row_number=1,
            source_relative_path="topic/dupe.pdf",
            source_sha256="a" * 64,
            docling_level="C",
            status="failed",
        ),
        make_row(
            row_number=2,
            source_relative_path="topic/dupe.pdf",
            source_sha256="b" * 64,
            docling_level="B",
            status="failed",
        ),
    ]
    run_dir = tmp_path / "previous-run"
    subject.write_artifacts(run_dir, rows, subject.summary_payload(rows, run_dir=run_dir, apply=True, smoke=False))

    selected = subject.select_manifest_rows(run_dir, statuses={"failed"})

    assert selected == [
        subject.ManifestSelection(
            row_number=1,
            source_relative_path="topic/dupe.pdf",
            source_sha256="a" * 64,
            docling_level="C",
        )
    ]


def test_select_manifest_rows_missing_manifest_fails_closed(tmp_path: Path) -> None:
    try:
        subject.select_manifest_rows(tmp_path / "missing-run", statuses={"failed"})
    except FileNotFoundError as exc:
        assert "docling-cinema-batch-manifest.tsv" in str(exc)
    else:
        raise AssertionError("expected missing manifest failure")


def test_inventory_manifest_hash_mismatch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_probe_and_hash(monkeypatch, {"file.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})

    try:
        subject.inventory_source(
            root,
            only_relative_paths=["topic/file.pdf"],
            expected_hashes={"topic/file.pdf": "b" * 64},
        )
    except ValueError as exc:
        assert str(exc) == "manifest_source_hash_mismatch: topic/file.pdf"
    else:
        raise AssertionError("expected manifest hash mismatch failure")


def test_select_smoke_rows_picks_one_per_lane(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/clean.pdf")
    make_pdf(root, "b/main.pdf")
    make_pdf(root, "c/scan.pdf")
    probes = {
        "clean.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000),
        "main.pdf": subject.PdfProbe(page_count=220, sampled_text_chars=2_000),
        "scan.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2),
    }
    patch_probe_and_hash(monkeypatch, probes)

    rows = subject.inventory_source(root)
    smoke = subject.select_smoke_rows(rows)

    assert [row.docling_level for row in smoke] == ["A", "C", "B"]


def test_run_batch_dry_run_writes_manifests_without_runner(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/clean.pdf")
    patch_probe_and_hash(monkeypatch, {"clean.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})
    rows = subject.inventory_source(root)

    def failing_runner(*_args, **_kwargs):
        raise AssertionError("runner should not be called")

    result = subject.run_batch(root, rows, tmp_path / "run", runner=failing_runner)

    assert Path(result["manifest_path"]).exists()
    assert Path(result["retry_path"]).read_text(encoding="utf-8") == ""
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["apply"] is False
    assert summary["by_status"] == {"queued": 1}


def test_run_batch_apply_uses_fake_runner_and_validates_output(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/clean.pdf")
    patch_probe_and_hash(monkeypatch, {"clean.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})
    rows = subject.inventory_source(root)

    def fake_runner(
        row: subject.InventoryRow,
        _source: Path,
        output_root: Path,
        _level: subject.DoclingLevel,
    ) -> subject.RunnerResult:
        output_dir = output_root / row.source_sha256[:8]
        output_dir.mkdir(parents=True)
        (output_dir / "document.md").write_text("Good extracted text. " * 40, encoding="utf-8")
        return subject.RunnerResult(ok=True, output_dir=output_dir)

    result = subject.run_batch(root, rows, tmp_path / "run", apply=True, runner=fake_runner)

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["by_status"] == {"converted": 1}
    output_index = Path(result["output_index_path"]).read_text(encoding="utf-8")
    assert "clean.pdf" in output_index


def test_run_batch_failed_runner_writes_retry_manifest(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/clean.pdf")
    patch_probe_and_hash(monkeypatch, {"clean.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})
    rows = subject.inventory_source(root)

    def fake_runner(
        row: subject.InventoryRow,
        _source: Path,
        output_root: Path,
        _level: subject.DoclingLevel,
    ) -> subject.RunnerResult:
        return subject.RunnerResult(ok=False, output_dir=output_root / row.source_sha256[:8], stderr="boom")

    result = subject.run_batch(root, rows, tmp_path / "run", apply=True, runner=fake_runner)

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    retry = Path(result["retry_path"]).read_text(encoding="utf-8")
    assert summary["by_status"] == {"failed": 1}
    assert "boom" in retry


def test_run_batch_checkpoints_after_failed_row(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/first.pdf")
    make_pdf(root, "a/second.pdf")
    patch_probe_and_hash(
        monkeypatch,
        {
            "first.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000),
            "second.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000),
        },
    )
    rows = subject.inventory_source(root)
    run_dir = tmp_path / "run"
    calls = 0

    def fake_runner(
        row: subject.InventoryRow,
        _source: Path,
        output_root: Path,
        _level: subject.DoclingLevel,
    ) -> subject.RunnerResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subject.RunnerResult(ok=False, output_dir=output_root / row.source_sha256[:8], stderr="boom")
        checkpoint = (run_dir / "docling-cinema-batch-manifest.tsv").read_text(encoding="utf-8")
        checkpoint_summary = json.loads((run_dir / "docling-cinema-batch-summary.json").read_text(encoding="utf-8"))
        checkpoint_retry = (run_dir / "docling-cinema-batch-retry.jsonl").read_text(encoding="utf-8")
        checkpoint_index = (run_dir / "docling-cinema-batch-output-index.jsonl").read_text(encoding="utf-8")
        assert "failed" in checkpoint
        assert checkpoint_summary["by_status"] == {"failed": 1, "queued": 1}
        assert "boom" in checkpoint_retry
        assert checkpoint_index == ""
        output = output_root / row.source_sha256[:8]
        output.mkdir(parents=True)
        (output / "document.md").write_text("Extracted. " * 80, encoding="utf-8")
        original_write_artifacts = subject.write_artifacts

        def checkpoint_success(*args, **kwargs):
            original_write_artifacts(*args, **kwargs)
            success_summary = json.loads((run_dir / "docling-cinema-batch-summary.json").read_text(encoding="utf-8"))
            success_index = (run_dir / "docling-cinema-batch-output-index.jsonl").read_text(encoding="utf-8")
            assert success_summary["by_status"] == {"converted": 1, "failed": 1}
            assert "second.pdf" in success_index

        monkeypatch.setattr(subject, "write_artifacts", checkpoint_success)
        return subject.RunnerResult(ok=True, output_dir=output)

    result = subject.run_batch(root, rows, run_dir, apply=True, runner=fake_runner)

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["by_status"] == {"converted": 1, "failed": 1}


def test_inventory_resume_skips_existing_success_from_manifest(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "a/clean.pdf")
    patch_probe_and_hash(monkeypatch, {"clean.pdf": subject.PdfProbe(page_count=20, sampled_text_chars=2_000)})
    initial_rows = subject.inventory_source(root)
    initial_rows[0].status = "converted"
    run_dir = tmp_path / "run"
    subject.write_artifacts(run_dir, initial_rows, subject.summary_payload(initial_rows, run_dir=run_dir, apply=True, smoke=False))

    resumed_rows = subject.inventory_source(root, existing_successes=subject.load_existing_successes(run_dir))

    assert resumed_rows[0].status == "skipped_existing"


def test_write_artifacts_preserves_previous_summary_when_atomic_write_fails(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    initial_rows = [make_row(status="queued")]
    subject.write_artifacts(
        run_dir,
        initial_rows,
        subject.summary_payload(initial_rows, run_dir=run_dir, apply=False, smoke=False),
    )
    original_summary = (run_dir / "docling-cinema-batch-summary.json").read_text(encoding="utf-8")

    monkeypatch.setattr(subject.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("disk unavailable")))

    try:
        subject.write_artifacts(
            run_dir,
            [make_row(status="failed", error="boom")],
            subject.summary_payload([make_row(status="failed")], run_dir=run_dir, apply=True, smoke=False),
        )
    except OSError as exc:
        assert "disk unavailable" in str(exc)
    else:
        raise AssertionError("expected atomic write failure")

    assert (run_dir / "docling-cinema-batch-summary.json").read_text(encoding="utf-8") == original_summary


def test_validate_output_warns_on_tiny_markdown(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "document.md").write_text("tiny", encoding="utf-8")
    row = subject.InventoryRow(
        row_number=1,
        source_relative_path="topic/long.pdf",
        topic_folder="topic",
        source_root_label="cinema",
        source_sha256="a" * 64,
        bytes=10,
        page_count=50,
        sampled_text_chars=1_000,
        docling_level="C",
        selection_reason="main_cinema_hybrid_default",
        is_large=False,
        text_probe_status="healthy",
    )

    result = subject.validate_output(row, output)

    assert result.status == "validation_warning"
    assert result.reason == "markdown_too_small_for_pdf"


def test_run_docling_passes_level_output_root_and_extra_args(tmp_path: Path, monkeypatch) -> None:
    source = make_pdf(tmp_path, "cinema/topic/file.pdf")
    row = subject.InventoryRow(
        row_number=1,
        source_relative_path="topic/file.pdf",
        topic_folder="topic",
        source_root_label="cinema",
        source_sha256="a" * 64,
        bytes=10,
        page_count=10,
        sampled_text_chars=1_000,
        docling_level="C",
        selection_reason="main_cinema_hybrid_default",
        is_large=False,
        text_probe_status="healthy",
    )
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(subject.shutil, "which", lambda name: "/bin/docling" if name == "docling" else None)
    monkeypatch.setattr(subject.subprocess, "run", fake_run)

    result = subject.run_docling(
        row,
        source,
        tmp_path / "run" / "outputs",
        "C",
        extra_args=["--document-timeout", "7200"],
    )

    assert result.ok is True
    assert calls == [["/bin/docling", "C", str(source), "--document-timeout", "7200", "--output", str(result.output_dir)]]
    assert result.output_dir.is_relative_to(tmp_path / "run" / "outputs")


def test_run_docling_returns_failed_result_on_parent_timeout(tmp_path: Path, monkeypatch) -> None:
    source = make_pdf(tmp_path, "cinema/topic/file.pdf")
    row = subject.InventoryRow(
        row_number=1,
        source_relative_path="topic/file.pdf",
        topic_folder="topic",
        source_root_label="cinema",
        source_sha256="a" * 64,
        bytes=10,
        page_count=10,
        sampled_text_chars=1_000,
        docling_level="C",
        selection_reason="main_cinema_hybrid_default",
        is_large=False,
        text_probe_status="healthy",
    )

    def fake_run(cmd, _timeout):
        raise subprocess.TimeoutExpired(cmd, timeout=12, output="partial stdout", stderr=b"partial stderr")

    monkeypatch.setattr(subject.shutil, "which", lambda name: "/bin/docling" if name == "docling" else None)
    monkeypatch.setattr(subject, "_run_docling_command", fake_run)

    result = subject.run_docling(row, source, tmp_path / "run" / "outputs", "C", process_timeout_s=12)

    assert result.ok is False
    assert result.returncode == -9
    assert result.stdout == "partial stdout"
    assert "timeout_after_12s" in result.stderr
    assert "partial stderr" in result.stderr


def test_run_docling_redacts_absolute_paths_from_failure(tmp_path: Path, monkeypatch) -> None:
    source = make_pdf(tmp_path, "cinema/topic/file.pdf")
    row = make_row(source_relative_path="topic/file.pdf", docling_level="C")

    def fake_run(cmd, _timeout):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr=f"failed input={source} output={tmp_path / 'run' / 'outputs'}",
        )

    monkeypatch.setattr(subject.shutil, "which", lambda name: "/bin/docling" if name == "docling" else None)
    monkeypatch.setattr(subject, "_run_docling_command", fake_run)

    result = subject.run_docling(row, source, tmp_path / "run" / "outputs", "C")

    assert result.ok is False
    assert "<local_path>" in result.stderr
    assert str(tmp_path) not in result.stderr


def test_run_docling_command_kills_process_group_on_timeout(monkeypatch) -> None:
    calls = {}
    signals = []

    class FakeProcess:
        pid = 1234
        returncode = -15

        def __init__(self) -> None:
            self.communicate_calls = 0

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(["docling"], timeout, output="partial stdout", stderr="partial stderr")
            return ("partial stdout", "partial stderr")

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(subject.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subject.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    try:
        subject._run_docling_command(["docling", "C", "file.pdf"], 12)
    except subprocess.TimeoutExpired as exc:
        assert exc.output == "partial stdout"
        assert exc.stderr == "partial stderr"
    else:
        raise AssertionError("expected timeout")

    assert calls["kwargs"]["start_new_session"] is True
    assert signals == [(1234, subject.signal.SIGTERM)]


def test_make_docling_runner_captures_extra_args(tmp_path: Path, monkeypatch) -> None:
    source = make_pdf(tmp_path, "cinema/topic/file.pdf")
    row = subject.InventoryRow(
        row_number=1,
        source_relative_path="topic/file.pdf",
        topic_folder="topic",
        source_root_label="cinema",
        source_sha256="a" * 64,
        bytes=10,
        page_count=10,
        sampled_text_chars=1_000,
        docling_level="B",
        selection_reason="weak_text_probe_rescue",
        is_large=False,
        text_probe_status="weak",
    )
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(subject.shutil, "which", lambda name: "/bin/docling" if name == "docling" else None)
    monkeypatch.setattr(subject.subprocess, "run", lambda cmd, **_kwargs: calls.append(cmd) or Result())

    result = subject.make_docling_runner(extra_args=["--document-timeout", "7200"])(row, source, tmp_path / "outputs", "B")

    assert result.ok is True
    assert calls[0][0:5] == ["/bin/docling", "B", str(source), "--document-timeout", "7200"]
