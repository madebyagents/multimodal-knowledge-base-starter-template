# Docling Cinema Batches

This runbook covers the safe Docling conversion layer for the external cinema PDF corpus. It prepares extraction outputs for later Knowledge Hub, LightRAG, multimodal, or CAG work. It does not ingest anything by itself.

## Scope

The batch runner reads an external source root, inventories PDFs, classifies each file into a Docling lane, writes manifests, and optionally runs bounded conversion jobs. Source PDFs are read-only inputs.

Do not use this workflow to mutate Knowledge Hub, LightRAG, multimodal, Qdrant, Postgres, Redis, Chroma, vault files, Notion, or CAG packs. Those surfaces need a separate ingest plan after Docling outputs are reviewed.

## Lanes

| Lane | Use | Selection signal |
|---|---|---|
| Level A | Clean short text-first PDFs | Healthy text probe, short page count, modest file size |
| Level C | Main cinema corpus | Default for books, manuals, visual theory, directing, editing, and layout-rich PDFs |
| Level B | Rescue and OCR-heavy PDFs | Weak text probe, probe errors, scanned PDFs, failed C output, or high-value OCR needs |

Large files are flagged separately even when their lane is C. Run them as isolated shards so a single slow conversion does not block the rest of the corpus.

## Safe Operating Shape

Start with inventory or dry-run. Review the manifest before any apply run. Then run a smoke set with one representative file per lane. Only after the smoke artifacts look healthy should an operator run bounded batches.

Generated artifacts live under `logs/docling-runs/<run-id>/`:

- `docling-cinema-batch-summary.json`
- `docling-cinema-batch-manifest.tsv`
- `docling-cinema-batch-retry.jsonl`
- `docling-cinema-batch-output-index.jsonl`
- `outputs/`

The manifest uses source-relative paths and source hashes. It should not expose machine-specific source roots.

## Resume From A Prior Manifest

Use `--from-manifest` to build a new dry-run from a previous run without hand-copying
long path lists. The argument can point either at a run directory or directly at
`docling-cinema-batch-manifest.tsv`.

`--from-manifest` always requires at least one `--prior-status`, and the new
`--run-id` must be different from the prior run directory. This protects the
original ledger from accidental overwrite and prevents an empty selection from
falling back to the whole source tree.

Rows selected from a prior manifest keep their prior `docling_level` by default,
even if the current classifier would choose a different lane. Use
`--force-level` only when the retry should intentionally run in a new lane.
Do not combine `--from-manifest` with `--only-relative-path`; manual path
selection is a separate non-manifest workflow. Apply runs created from a prior
manifest require a positive `--document-timeout-s` so the parent process can
bound each long Docling child process.

Manifest resumes also verify the current source file hash against the prior
manifest hash. If the relative path points to a different PDF under the selected
source root, the runner fails closed before writing a new ledger.

Target run directories are write-protected by default. Choose a fresh `--run-id`
for a new dry-run. To apply a reviewed dry-run using the same run id, add
`--resume-run` explicitly.

Dry-run the remaining queued level C rows from a previous run:

```bash
uv run --project backend python scripts/docling_cinema_batch.py \
  --source-root /Users/vidigal/Downloads/scribd/cinema \
  --artifact-root logs/docling-runs \
  --run-id docling-cinema-pending-c-YYYYMMDD \
  --from-manifest logs/docling-runs/docling-cinema-full-20260703-ptbr-resumable \
  --prior-status queued \
  --level C
```

Apply only after reviewing the generated manifest:

```bash
uv run --project backend python scripts/docling_cinema_batch.py \
  --source-root /Users/vidigal/Downloads/scribd/cinema \
  --artifact-root logs/docling-runs \
  --run-id docling-cinema-pending-c-YYYYMMDD \
  --from-manifest logs/docling-runs/docling-cinema-full-20260703-ptbr-resumable \
  --prior-status queued \
  --level C \
  --document-timeout-s 7200 \
  --limit 3 \
  --resume-run \
  --apply
```

For failed rows, use a fresh run id and an extended Docling document timeout.
If the prior lane was a poor fit, use `--force-level` so resume checks and output
directories are keyed to the retry lane instead of the old classifier result.
When both `--level` and `--force-level` are present with `--from-manifest`,
`--level` filters the previous manifest lane and `--force-level` chooses the
effective retry lane.

```bash
uv run --project backend python scripts/docling_cinema_batch.py \
  --source-root /Users/vidigal/Downloads/scribd/cinema \
  --artifact-root logs/docling-runs \
  --run-id docling-cinema-failed-retry-c-YYYYMMDD \
  --from-manifest logs/docling-runs/docling-cinema-full-20260703-ptbr-resumable \
  --prior-status failed \
  --force-level C \
  --document-timeout-s 7200
```

Add `--apply` only after the retry manifest shows the intended rows. Keep retries
in new run directories so the original full-run ledger remains auditable.
If applying an already reviewed retry dry-run with the same `--run-id`, add
`--resume-run`.

For arbitrary Docling flags, repeat `--docling-arg`. Use the equals form when
the forwarded value starts with a hyphen:

```bash
--docling-arg=--page-batch-size --docling-arg=4
```

## Review Checklist

- Every PDF has one manifest row.
- Level C is the dominant lane unless the corpus has changed materially.
- Level B rows are explainable by weak text probes, probe errors, scan-heavy content, or retries.
- Smoke includes A, C, and B when those lanes exist.
- Failed rows appear in the retry artifact.
- Validation warnings are reviewed before downstream ingest.
- Manifest resumes did not report `manifest_source_hash_mismatch`.
- A reused dry-run `--run-id` was applied only with explicit `--resume-run`.
- No downstream store was mutated by this workflow.

## Handoff

After conversion, a separate plan should decide what enters Knowledge Hub classic, LightRAG KH-native, multimodal, and CAG packs. That plan should use the output index, retry list, validation summary, source hashes, and any manual quality review notes from this run.
