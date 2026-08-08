# Post-Docling KH, LightRAG, And CAG Harness

This runbook covers the safe P0-P8 harness that starts after Docling has already
finished. It does not run Docling conversion, does not write to Knowledge Hub,
does not write to LightRAG, and does not materialize CAG packs unless a future
apply path is explicitly implemented and reviewed.

## Safe Default

Run the harness from the repository root:

```bash
uv run --project backend python scripts/docling_kh_lightrag_cag_harness.py
```

The default run reads the existing Docling run ledgers, normalizes downstream
records, builds KH multimodal candidates, builds LightRAG graph candidates,
creates a package crosswalk, creates CAG pack candidates, and writes a final
certification report under `logs/post-docling-p0-p8-harness/`.

`--apply` is intentionally fail-closed for this version.

## Canonical Inputs

The default inputs are the already-completed Docling artifacts:

```text
logs/docling-runs/docling-cinema-full-20260703-ptbr-resumable
logs/docling-runs/docling-cinema-pending-c-20260704-ready
logs/docling-runs/docling-cinema-failed-retry-chunked5-b-20260705
logs/docling-runs/docling-cinema-enrichment-overlay-20260706
```

Certification expects 84 converted PDF rows across the three Docling runs.

## Provider Defaults

Visual analysis candidates use Qwen as the primary provider and Gemini only as
fallback metadata:

```text
primary visual provider: qwen
primary visual model: qwen-3.7-max
endpoint region: cn-beijing
fallback provider: gemini
ocr-specialized model: qwen-ocr
```

Provider credentials must live in a gitignored local environment file such as
`backend/.env`. The CLI wrapper loads that file before building the provider
contract. The harness never prints or writes raw keys. Public artifacts only
record whether the base URL and API key were configured.

Supported local environment variable names:

```dotenv
QWEN_VISION_MODEL=qwen-3.7-max
QWEN_OCR_MODEL=qwen-ocr
QWEN_ENDPOINT_REGION=cn-beijing
QWEN_BASE_URL=<alibaba-openai-compatible-base-url>
QWEN_API_KEY=<secret>
```

`DASHSCOPE_BASE_URL`, `ALIBABA_QWEN_BASE_URL`, `DASHSCOPE_API_KEY`,
`ALIBABA_QWEN_API_KEY`, and `ALIBABA_API_KEY` are also recognized for presence
checks.

## Outputs

Each run writes:

```text
p0-docling-proof.json
p1-package-contract.json
docling-normalized-output.jsonl
docling-normalized-summary.json
kh-multimodal-candidates.jsonl
lightrag-graph-candidates.jsonl
package-crosswalk.jsonl
cag-pack-candidates.jsonl
p0-p8-certification.json
phase-ledger.json
report.md
```

The certification passes only when the run has no mutation, no public leaks,
normalized Docling coverage, package crosswalk rows, and CAG candidate rows.

Heavy duplicate Docling renderings such as `.html`, `.json`, `.yaml`, and
`.yml` files are registered as skipped metadata by default instead of being
hashed. Markdown, text, DocTags, extracted images, and CSV table outputs remain
lightweight downstream candidates.

## Next Safe Apply Boundary

The next implementation step after a certified dry-run is not to run Docling
again. It is to add a reviewed apply stage that consumes these candidate files
and writes to one downstream surface at a time, starting with a bounded sample.
Each apply stage must have its own preflight, mutation ledger, rollback notes,
and certification gate.
