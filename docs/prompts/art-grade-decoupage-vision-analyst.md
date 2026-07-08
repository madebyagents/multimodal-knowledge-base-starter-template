# Art-Grade Decoupage Vision Analyst

This document tracks the premium decoupage profile imported from the operator
prompt named `Art-Grade Decoupage Vision Analyst - GPT-5.5 Port`.

## Purpose

The profile is a second, higher-bar visual analysis contract for Dante visual
assets. It is meant to produce one strict JSON sidecar per image with:

- controlled vocabulary fields for camera, lighting, color, art direction,
  costume, performance, lineage, and distinction;
- explicit evidence planes: visible, inferred, uncertain, and not visible;
- a `markdown_handoff` string that can be indexed as human-readable curator
  prose after review;
- confidence-bearing language for technical claims so lenses, stock, Kelvin,
  focal length, and production facts are not asserted as fact from pixels alone.

## Runtime Assets

Prompt:

```text
backend/app/dante_visual/prompts/art_grade_decoupage_vision_analyst.md
```

Responses API `text.format` schema:

```text
backend/app/dante_visual/schemas/decoupage_sidecar.schema.json
```

Python helper:

```text
backend/app/dante_visual/decoupage.py
```

Unit tests:

```text
backend/tests/test_dante_visual_decoupage.py
backend/tests/test_dante_visual_openai_decoupage_provider.py
```

## Current Boundary

This profile is registered as a local prompt/schema asset only. It does not
replace the existing Gemini card run, does not mutate Chroma, does not reindex
the KB, and does not touch the canonical Knowledge Hub or Obsidian vault.

The current production dashboard remains backed by:

- 2,094 image vectors;
- 2,094 text cards;
- existing `image_analysis_card.v1` Markdown/JSON sidecars;
- the live local backend at `127.0.0.1:8035`.

## Provider Integration Plan

The intended next implementation unit is a bounded provider adapter that:

1. loads `build_decoupage_instructions(asset_id=..., lens=...)`;
2. sends one resized image plus the prompt to the selected vision model;
3. requests strict structured output with `decoupage_sidecar.schema.json`;
4. writes reviewed decoupage sidecars into a separate run directory;
5. indexes only approved `markdown_handoff` text and linked metadata.

Do not run this over the full corpus until a smoke set passes schema validation,
visual QA, and cost checks.

## Safe Commands

Zero-cost mock preflight:

```bash
uv run --project backend python scripts/dante_visual_decoupage_harness.py --run-id visual-decoupage-smoke preflight
```

Zero-cost mock sidecar generation:

```bash
uv run --project backend python scripts/dante_visual_decoupage_harness.py --run-id visual-decoupage-smoke generate --provider mock --sample 1 --lens solo --force
```

Bounded OpenAI smoke, only after `OPENAI_API_KEY` is configured in
`backend/.env` and cost is approved:

```bash
uv run --project backend python scripts/dante_visual_decoupage_harness.py --run-id visual-decoupage-openai-smoke generate --provider openai --sample 1 --lens solo --continue-on-error
```

Output is isolated under:

```text
commercial-film-production-kb/13-visual-reference-assets/analysis-cards/decoupage/
```

The harness writes JSON sidecars and Markdown handoff files, but does not ingest
them into Chroma or LightRAG.
