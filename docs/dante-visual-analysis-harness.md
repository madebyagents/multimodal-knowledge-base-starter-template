# Dante Visual Analysis Harness

This harness creates reviewable visual-analysis sidecars for the canonical Dante film stills.

The semantic analysis-card slice is intentionally separated from textual
LightRAG ingest. JSON/Markdown cards support both the deterministic mock
provider and a real Gemini vision provider. The vector ingest slice embeds the
canonical JPG corpus into the Dante multimodal Chroma sidecar with Voyage.

## Source

Canonical manifest:

```text
commercial-film-production-kb/13-visual-reference-assets/source-assets/asset-manifest.tsv
```

The manifest is the source of truth. The harness validates every row against the image on disk with SHA-256, byte size, dimensions, safe relative paths, category/group slugs, and JPG extension checks.

## Safe Commands

Preflight only:

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke preflight
```

Generate a bounded mock sample:

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke generate --sample 10 --max-premium 2
```

Generate a bounded Gemini vision sample:

```bash
uv run --project backend python scripts/dante_visual_analysis_harness.py --run-id visual-gemini-smoke generate --provider gemini --sample 1 --max-premium 1
```

Generate a bounded stratified Gemini vision batch:

```bash
uv run --project backend python scripts/dante_visual_analysis_harness.py --run-id visual-gemini-batch100-stratified-compressed-20260613-codex generate --provider gemini --sample 100 --sample-mode stratified --max-premium 15 --continue-on-error --gemini-timeout 45 --gemini-max-retries 1 --gemini-max-output-tokens 4096
```

Run the full corpus with all six Gemini roles per image:

```bash
uv run --project backend python scripts/dante_visual_full_auto_harness.py --run-id visual-gemini-full-auto-20260614-codex --all-premium --concurrency 6 --retry-passes 3 --gemini-timeout 75 --gemini-max-retries 3 --gemini-max-output-tokens 6144
```

Regenerate the contact sheet:

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke contact-sheet
```

Record one decision:

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke decide aftersun-2022-001 approved --reviewer operator --reason "approved from sample review"
```

Bulk approve currently pending cards:

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke bulk-approve --limit 25 --reviewer operator
```

Run idempotent Voyage vector ingest:

```bash
uv run --project backend python scripts/dante_visual_vector_ingest.py --run-id visual-vector-smoke-codex ingest --limit 3 --batch-size 2 --max-batch-mb 4
uv run --project backend python scripts/dante_visual_vector_ingest.py --run-id visual-vector-full-20260613-codex ingest --batch-size 12 --max-batch-mb 8
uv run --project backend python scripts/dante_visual_vector_ingest.py --run-id visual-vector-final-validation-codex preflight
```

## Output

Cards:

```text
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/cards/<category>/<group>/<image-id>.json
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/cards/<category>/<group>/<image-id>.md
```

Markdown cards keep the structured fields first. They then add anti-fatigue
interpretive notes: one paragraph from a director's point of view, one from a
DOP/art-director point of view, and one additional free read that preserves the
card's editorial signal without collapsing the analysis into a generic summary.

## Premium Decoupage Profile

The `Art-Grade Decoupage Vision Analyst` prompt is stored as an isolated
profile for a future higher-bar visual pass. It uses a strict structured-output
contract named `decoupage_sidecar` and adds deeper fields for camera grammar,
lighting, color, art direction, costume, performance, lineage, distinction, and
grounding planes.

Runtime assets:

```text
backend/app/dante_visual/prompts/art_grade_decoupage_vision_analyst.md
backend/app/dante_visual/schemas/decoupage_sidecar.schema.json
backend/app/dante_visual/decoupage.py
scripts/dante_visual_decoupage_harness.py
```

This profile is not automatically run by the existing Gemini harness. It should
be integrated through a separate provider adapter and smoke-tested on a bounded
set before any full-corpus run. Approved `markdown_handoff` text can then be
ingested as an additional text layer linked to the image sidecar.

Safe mock smoke:

```bash
uv run --project backend python scripts/dante_visual_decoupage_harness.py --run-id visual-decoupage-smoke generate --provider mock --sample 1 --lens solo --force
```

Promote and ingest the verified Gemini production decoupage run:

```bash
uv run --project backend python scripts/dante_visual_decoupage_ingest.py \
  --vault-root /Users/vidigal/Dante \
  --dataset-root /Users/vidigal/Dante/commercial-film-production-kb/13-visual-reference-assets \
  --source-run-id visual-decoupage-gemini31-production-20260616-codex \
  --run-id visual-decoupage-ingest-20260616-codex
```

Current production decoupage validation:

- source run id: `visual-decoupage-gemini31-production-20260616-codex`;
- provider: Gemini Developer API, not Vertex;
- model: `gemini-3.1-pro-preview`;
- target count: 2,093;
- OK count: 2,093;
- error count: 0;
- average confidence: 0.9031;
- ingest run id: `visual-decoupage-ingest-20260616-codex`;
- Chroma decoupage nodes embedded: 2,093;
- missing linked image rows: 0;
- failed rows: 0.

Manifests and decisions:

```text
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/manifests/<run-id>/preflight.json
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/manifests/<run-id>/analysis-manifest.tsv
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/review-decisions.jsonl
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/review-state.tsv
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/manifests/<run-id>/vector-ingest-manifest.tsv
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/manifests/<run-id>/vector-ingest-summary.json
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/decoupage/manifests/<run-id>/decoupage-promotion-manifest.tsv
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/decoupage/manifests/<run-id>/decoupage-promotion-summary.json
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/decoupage/manifests/<run-id>/decoupage-ingest-manifest.tsv
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/decoupage/manifests/<run-id>/decoupage-ingest-summary.json
```

Review:

```text
commercial-film-production-kb/13-visual-reference-assets/review/index.html
```

## Provider Boundary

The default provider is the deterministic mock provider. It does not call
OpenAI, Google, Voyage, Gemini, DeepSeek, Cohere, or any other paid cloud model
for analysis cards.

The Gemini provider is opt-in via `--provider gemini`. It sends image bytes,
image metadata, and an analysis prompt to the configured Google Gemini API key.
The configured model is `gemini-3-flash-preview`; `gemini-3.5-flash` was not
listed by the Gemini API for the available key during configuration.

Current Gemini validation:

- run id: `visual-gemini-premium-smoke-codex`;
- model: `gemini-3-flash-preview`;
- cards written: 1;
- premium selected: 1;
- roles generated: technical, cinematography, narrative/editorial, OCR/facts, judge, confrontation.
- batch run id: `visual-gemini-batch100-stratified-compressed-20260613-codex`;
- batch cards written: 100;
- batch premium selected: 15;
- batch remaining errors after focused retry: 0;
- batch redacted raw-run records: 430.
- full run id: `visual-gemini-full-auto-20260614-codex`;
- full cards ready: 2,094;
- full premium targets: 2,094;
- full remaining errors after retry: 0;
- full redacted raw-run records: 12,468;
- full contact-sheet cards: 2,094.

## Ingest Boundary

The vector-ingest script writes to Chroma and does not copy assets into
`backend/uploads`. It uses `source_sha256` for dedupe/resume, so repeated runs
skip already-ingested images.

Current production vector-ingest validation:

- run id: `visual-vector-full-20260613-codex`;
- Chroma image vectors: 2,094;
- unique Dante visual hashes: 2,094;
- duplicate hash rows: 0;
- failed rows: 0.

This harness does not write to the text-only LightRAG runtime. Future slices may use the approved `review-state.tsv` to:

- stage approved Markdown cards for the text-only LightRAG harness.

Raw JPGs must not be staged into textual LightRAG.
