# Docling Black Label Packages

This runbook covers the package builder and staged apply harness that starts
from a certified post-Docling P0-P8 harness run and creates Black Label
multimodal package plans. It does not run Docling, does not call Qwen/Gemini,
and does not write to Knowledge Hub or CAG stores. LightRAG writes are available
only through explicit staged apply commands with preflight, ledgers, query
recovery, and service-enforced single-use fencing. The currently audited
LightRAG adapter does not expose that fencing contract, so live apply fails
closed before insertion.

## Safe Default

Run from the repository root:

```bash
uv run --project backend python scripts/docling_black_label_package.py \
  --source-run logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>
```

Legacy authorization requires two independent operator-supplied values. The
certification hash is the repository `stable_hash` of the parsed
`p0-p8-certification.json`, not the byte hash of its formatting. The composite
bundle hash binds that certification, the ordered normalized output, crosswalk,
CAG candidates, and every referenced text artifact verified against its
declared SHA-256. Compute both from the exact source run before supplying the
flags:

```bash
uv run --project backend python -c \
  'import json,sys; from pathlib import Path; sys.path.insert(0,"backend"); from app.docling_black_label_package import BlackLabelConfig,load_source_bundle,stable_hash; source=load_source_bundle(BlackLabelConfig(run_id="binding-only",source_run=Path(sys.argv[1]))); print(json.dumps({"legacy_source_certification_hash":stable_hash(source.certification),"legacy_source_bundle_hash":source.binding["source_bundle_hash"]},sort_keys=True))' \
  logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z
```

Both hash flags are required for explicit legacy authorization. A provenance
marker inside the source file or the certification hash alone is insufficient,
and neither flag can override a governed source whose controller authorization
is not green.

The command writes a new run directory under `logs/black-label-docling/` with:

```text
black-label-asset-registry.jsonl
docling-pdf-page-image-crosswalk.jsonl
visual-enrichment-queue.jsonl
black-label-card-manifest.jsonl
kh-multimodal-apply-plan.jsonl
lightrag-card-apply-plan.jsonl
cag-pack-manifest.jsonl
black-label-eval-suite.jsonl
black-label-certification.json
phase-ledger.json
report.md
```

`--apply` is intentionally fail-closed. The builder creates plans and
certification evidence only. Staged LightRAG apply uses explicit commands below
instead of `--apply`.

## Source Contract

The input run must contain a green P0-P8 certification plus these files:

```text
p0-p8-certification.json
docling-normalized-output.jsonl
package-crosswalk.jsonl
cag-pack-candidates.jsonl
```

The current canonical source run is:

```text
logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z
```

It represents the already-completed 84-PDF Docling corpus. Do not rerun Docling
to operate this workflow.

## Provider Contract

Visual enrichment is planned, not executed. Queue rows use:

```text
primary provider: qwen
primary model: qwen-3.7-max
ocr model: qwen-ocr
endpoint region: cn-beijing
fallback provider: gemini
```

Credentials may be present in `backend/.env`, but public artifacts only report
whether the base URL and API key are configured. Raw keys and full private URLs
must never appear in reports.

## Certification Meaning

A green `black-label-certification.json` means:

- the source P0-P8 run was certified and non-mutating;
- all PDF/image/table/page/text assets were registered with stable package IDs;
- all extracted images are linkable through `image_package_id`;
- cards are rights-safe planning records, not raw source-text inserts;
- Qwen visual work is represented as a dry-run queue;
- KH, visual, and CAG outputs are apply plans only;
- LightRAG staged ledgers, when present, have been folded into rollout gates;
- public leak scanning found zero local paths or secrets.

Rows whose source text triggers rights-risk patterns are kept as blocked cards
and excluded from LightRAG apply planning. They remain visible in certification
counts as `rights_blocked_cards`.

## Current Full Dry-Run Evidence

The first full run after implementation completed at:

```text
logs/black-label-docling/black-label-full-dryrun-20260708T072250Z
```

It certified:

```json
{
  "pdf_assets": 84,
  "image_assets": 8185,
  "registry_assets": 12974,
  "visual_requests": 8200,
  "cards": 13226,
  "kh_plan_rows": 26200,
  "lightrag_plan_rows": 13226,
  "cag_packs": 5,
  "eval_queries": 29,
  "rights_blocked_cards": 7,
  "leaks": 0
}
```

## Current Staged Apply Evidence

The first-card, five-source, and topic-cluster LightRAG samples have been
applied and recovered on the current full dry-run:

```text
logs/black-label-docling/black-label-full-dryrun-20260708T072250Z/lightrag-sample-apply-ledger.json
logs/black-label-docling/black-label-full-dryrun-20260708T072250Z/lightrag-five-document-sample-apply-ledger.json
logs/black-label-docling/black-label-full-dryrun-20260708T072250Z/lightrag-topic-cluster-sample-apply-ledger.json
```

The topic-cluster stage inserted and processed 100 curated cards, then the
ledger was refreshed with bounded isolated query recovery. Recovery evidence
stores only public-safe match markers and counts, not retrieved context text.

Current live LightRAG status after the topic stage:

```json
{
  "processed": 10939,
  "failed": 0,
  "pending": 0,
  "processing": 0
}
```

The refreshed certification currently reports:

```text
gate_0_dry_run_registry: pass
gate_1_lightrag_one_card_sample: pass
gate_2_lightrag_five_source_sample: pass
gate_3_lightrag_topic_cluster: pass
gate_4_qwen_priority_visuals: pending_live_operator_gate
gate_5_kh_cag_handoff: pending_reviewed_apply_client
gate_6_full_84_pdf_apply: ready_for_operator_gate
```

## Next Safe Apply Boundary

The next logical LightRAG mutation gate is `full_corpus_after_certification`.
It remains a no-go in the current runtime because the insert API has no
service-enforced single-use fencing contract. Do not run it until a reviewed
adapter advertises the exact fencing fields, atomically rejects token replay,
and returns a bound receipt. After that capability exists,
refresh certification and verify `quality_bar.full_corpus_apply_allowed=true`,
`gate_6_full_84_pdf_apply=ready_for_operator_gate`, LightRAG is idle, failed
count is zero, and the duplicate-source index can be fetched.

Use `--source-run` for the exact P0-P8 source on every build, refresh, and apply
so authorization is derived from the current source rather than copied Black
Label fields. Use `--black-label-run` for staged apply and certification
refresh. Every operation against this legacy run must repeat both verified
hashes. The Black Label certification also persists the versioned generation
recipe used for canonical card and plan regeneration. Current runs emit recipe
`v2`, including the evaluation threshold. Apply and refresh retain compatibility
with prior `v1` and recipe-absent certifications by preserving the certified
`quality_bar.target_eval_threshold`; malformed versions fail closed.

For the legacy `--source-run <black-label-run>` alias, supply `--source-root`
pointing to the parent of the certified P0-P8 runs. The alias resolves only one
exact match for both the recorded source-certification hash and composite bundle
hash. Missing or ambiguous matches block before client creation.

Before client creation, apply checks explicit-versus-certified source identity
and canonically regenerates the card manifest and LightRAG plan from that exact
source in a contained temporary directory. A different authorized source cannot
rebind an existing Black Label plan.

```bash
uv run --project backend python scripts/docling_black_label_package.py \
  refresh-certification \
  --source-run logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z \
  --black-label-run logs/black-label-docling/black-label-full-dryrun-20260708T072250Z \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>

uv run --project backend python scripts/docling_black_label_package.py \
  apply-lightrag-stage \
  --source-run logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z \
  --black-label-run logs/black-label-docling/black-label-full-dryrun-20260708T072250Z \
  --lightrag-stage full_corpus_after_certification \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>

uv run --project backend python scripts/docling_black_label_package.py \
  refresh-certification \
  --source-run logs/post-docling-p0-p8-harness/post-docling-p0-p8-smoke-20260708T024207Z \
  --black-label-run logs/black-label-docling/black-label-full-dryrun-20260708T072250Z \
  --legacy-source-certification-hash <verified-canonical-source-hash> \
  --legacy-source-bundle-hash <verified-composite-source-bundle-hash>
```

The stage order is:

```text
one_document_sample -> five_document_sample -> topic_cluster_sample -> full_corpus_after_certification
```

`one_document_sample` is the compatibility name for the first-card sample: one
curated card from one source document. Full-corpus apply is implemented as a
gated stage and requires refreshed certification evidence before mutation.

Required evidence before scaling:

- LightRAG health and status preflight are idle and failed count is zero.
- Inserted card count matches the stage ledger after duplicate-source skips.
- Query context recovers the new card/package references.
- Query recovery ledgers contain only match booleans, hashes, reference counts,
  and package/source refs; they must not persist retrieved context content.
- No rights-blocked card is inserted.
- `black-label-certification.json` remains green after each stage ledger is
  attached and certification is refreshed.

KH multimodal, Qwen visual enrichment, and CAG materialization remain reviewed
handoff surfaces. Their manifests expose readiness and package refs, but this
runbook does not authorize broad writes outside the staged LightRAG path.
