from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import docling_cinema_batch as subject


def make_pdf(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF fixture")


def patch_healthy_probe_and_hash(monkeypatch, hash_func=None) -> None:
    monkeypatch.setattr(
        subject,
        "probe_pdf",
        lambda _path, *, max_pages=subject.DEFAULT_PROBE_PAGES: subject.PdfProbe(page_count=10, sampled_text_chars=2_000),
    )
    monkeypatch.setattr(subject, "sha256_file", hash_func or (lambda _path: "a" * 64))


def write_previous_run(run_dir: Path, rows: list[subject.InventoryRow], *, apply: bool = True) -> None:
    subject.write_artifacts(
        run_dir,
        rows,
        subject.summary_payload(rows, run_dir=run_dir, apply=apply, smoke=False),
    )


def failing_runner(*_args, **_kwargs):
    raise AssertionError("runner should not be called")


def successful_runner(calls=None):
    def _runner(
        row: subject.InventoryRow,
        _source: Path,
        output_root: Path,
        level: subject.DoclingLevel,
    ) -> subject.RunnerResult:
        if calls is not None:
            calls.append((row.source_relative_path, level))
        output = output_root / row.source_sha256[:8]
        output.mkdir(parents=True)
        (output / "document.md").write_text("Extracted. " * 80, encoding="utf-8")
        return subject.RunnerResult(ok=True, output_dir=output)

    return _runner


def test_cli_dry_run_does_not_call_runner(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/clean.pdf")
    patch_healthy_probe_and_hash(monkeypatch)

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "test-run",
        ],
        runner=failing_runner,
    )

    assert code == 0
    assert '"apply": false' in capsys.readouterr().out


def test_cli_apply_uses_fake_runner(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/clean.pdf")
    patch_healthy_probe_and_hash(monkeypatch)

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "test-run",
            "--apply",
        ],
        runner=successful_runner(),
    )

    assert code == 0
    assert (tmp_path / "runs" / "test-run" / "docling-cinema-batch-summary.json").exists()


def test_cli_selects_prior_failed_rows_and_force_level(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/failed.pdf")
    make_pdf(root, "topic/done.pdf")
    patch_healthy_probe_and_hash(monkeypatch, lambda path: f"{path.name}:hash".encode().hex().ljust(64, "0")[:64])
    previous_rows = subject.inventory_source(root)
    for row in previous_rows:
        row.status = "failed" if row.source_relative_path.endswith("failed.pdf") else "converted"
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows)

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "retry-run",
            "--from-manifest",
            str(previous_run),
            "--prior-status",
            "failed",
            "--force-level",
            "C",
        ],
        runner=failing_runner,
    )

    manifest = tmp_path / "runs" / "retry-run" / "docling-cinema-batch-manifest.tsv"
    text = manifest.read_text(encoding="utf-8")
    assert code == 0
    assert "topic/failed.pdf" in text
    assert "topic/done.pdf" not in text
    assert "operator_forced_level_c_from_a" in text


def test_cli_filters_prior_level_but_runs_forced_level(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/failed.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_rows[0].status = "failed"
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows)
    calls = []

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "retry-run",
            "--from-manifest",
            str(previous_run),
            "--prior-status",
            "failed",
            "--level",
            "A",
            "--force-level",
            "C",
            "--document-timeout-s",
            "7",
            "--apply",
        ],
        runner=successful_runner(calls),
    )

    assert code == 0
    assert calls == [("topic/failed.pdf", "C")]


def test_cli_preserves_prior_manifest_level_without_force_level(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/was-c.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_rows[0].docling_level = "C"
    previous_rows[0].status = "failed"
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows)
    calls = []

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "retry-run",
            "--from-manifest",
            str(previous_run),
            "--prior-status",
            "failed",
            "--level",
            "C",
            "--document-timeout-s",
            "7",
            "--apply",
        ],
        runner=successful_runner(calls),
    )

    manifest = tmp_path / "runs" / "retry-run" / "docling-cinema-batch-manifest.tsv"
    summary = json.loads((tmp_path / "runs" / "retry-run" / "docling-cinema-batch-summary.json").read_text(encoding="utf-8"))
    assert code == 0
    assert calls == [("topic/was-c.pdf", "C")]
    assert "manifest_prior_level_c_from_a" in manifest.read_text(encoding="utf-8")
    assert summary["schema_version"] == subject.SCHEMA_VERSION


def test_cli_preserves_mixed_prior_manifest_levels_in_manifest_order(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "z/first-in-manifest.pdf")
    make_pdf(root, "a/second-in-manifest.pdf")
    patch_healthy_probe_and_hash(monkeypatch, lambda path: f"{path.name}:hash".encode().hex().ljust(64, "0")[:64])
    previous_rows = subject.inventory_source(root, only_relative_paths=["z/first-in-manifest.pdf", "a/second-in-manifest.pdf"])
    previous_rows[0].docling_level = "C"
    previous_rows[1].docling_level = "A"
    for row in previous_rows:
        row.status = "failed"
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows)
    calls = []

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "retry-run",
            "--from-manifest",
            str(previous_run),
            "--prior-status",
            "failed",
            "--document-timeout-s",
            "7",
            "--apply",
        ],
        runner=successful_runner(calls),
    )

    assert code == 0
    assert calls == [("z/first-in-manifest.pdf", "C"), ("a/second-in-manifest.pdf", "A")]


def test_cli_from_manifest_requires_prior_status(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_rejects_manual_relative_path(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
                "--prior-status",
                "queued",
                "--only-relative-path",
                "topic/file.pdf",
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_zero_selection_fails(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_rows[0].status = "converted"
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
                "--prior-status",
                "failed",
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_refuses_same_run_dir(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    run_dir = tmp_path / "runs" / "same-run"
    write_previous_run(run_dir, previous_rows, apply=False)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "same-run",
                "--from-manifest",
                str(run_dir),
                "--prior-status",
                "queued",
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_refuses_existing_target_without_resume(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)
    target_run = tmp_path / "runs" / "retry-run"
    write_previous_run(target_run, previous_rows, apply=False)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
                "--prior-status",
                "queued",
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_rejects_source_hash_mismatch(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch, lambda _path: "a" * 64)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)
    patch_healthy_probe_and_hash(monkeypatch, lambda _path: "b" * 64)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
                "--prior-status",
                "queued",
            ],
        )

    assert exc.value.code == 2


def test_cli_from_manifest_apply_requires_timeout(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--from-manifest",
                str(previous_run),
                "--prior-status",
                "queued",
                "--apply",
            ],
            runner=successful_runner(),
        )

    assert exc.value.code == 2


def test_cli_level_with_force_level_requires_manifest(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        subject.main(
            [
                "--source-root",
                str(root),
                "--artifact-root",
                str(tmp_path / "runs"),
                "--run-id",
                "retry-run",
                "--level",
                "A",
                "--force-level",
                "C",
            ],
        )

    assert exc.value.code == 2


def test_cli_forwards_docling_args_and_parent_timeout(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "cinema"
    make_pdf(root, "topic/file.pdf")
    patch_healthy_probe_and_hash(monkeypatch)
    previous_rows = subject.inventory_source(root)
    previous_run = tmp_path / "previous-run"
    write_previous_run(previous_run, previous_rows, apply=False)
    calls = []

    def fake_run(cmd, timeout):
        calls.append((cmd, timeout))
        output = Path(cmd[cmd.index("--output") + 1])
        output.mkdir(parents=True)
        (output / "document.md").write_text("Extracted. " * 80, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(subject.shutil, "which", lambda name: "/bin/docling" if name == "docling" else None)
    monkeypatch.setattr(subject, "_run_docling_command", fake_run)

    code = subject.main(
        [
            "--source-root",
            str(root),
            "--artifact-root",
            str(tmp_path / "runs"),
            "--run-id",
            "retry-run",
            "--from-manifest",
            str(previous_run),
            "--prior-status",
            "queued",
            "--document-timeout-s",
            "7",
            "--docling-arg=--page-batch-size",
            "--docling-arg=4",
            "--apply",
        ],
    )

    assert code == 0
    cmd, timeout = calls[0]
    assert cmd[0:5] == ["/bin/docling", "A", str(root / "topic/file.pdf"), "--page-batch-size", "4"]
    assert "--document-timeout" in cmd
    assert timeout == 7 + subject.PROCESS_TIMEOUT_GRACE_S
