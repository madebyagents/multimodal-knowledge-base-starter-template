# DEEP MEMORY DANTEDASH 003

Snapshot date: 2026-06-15 21:24:57 -03
Workspace: `/Users/vidigal/codex/dantedash`
Status: Visual asset package contract documented before decoupage ingest

## Resume Output Contract

When the user returns with `continue`, `continua`, `retoma`, or fatigue/context
recovery, give exactly two humanized PT-BR summary lines first, then a short
`Next Steps` list grouped by priority, then wait unless execution is explicitly
requested:

```text
O pacote visual do Dante foi formalizado: cada imagem deve ser tratada como um asset com camadas linkadas, não como documentos soltos no KB.
Agora existe um contrato em docs/architecture/visual-asset-package-contract.md; o próximo passo é implementar o ingest decoupage quando Andre disser que está pronto para testes.

Next Steps:
P0 - Decoupage ingest contract
- Implement `visual_decoupage_bundle` ingest using `source_sha256`, `linked_image_file_id`, and `preview_image_file_id`.
- Do not run live model calls, Chroma ingest, delete, clear, or reindex until Andre says the system is ready for tests.

P1 - Dashboard/package surfacing
- After ingest exists, add grouped display/search behavior so image, Gemini card, and decoupage sidecar are shown as one linked visual asset package.
```

Do not mutate files during recovery until the user gives a new instruction, unless the user explicitly says to continue execution.

## Verified On Filesystem

| Path / Surface | Verified State |
|---|---|
| `docs/architecture/visual-asset-package-contract.md` | Created. Defines current package shape, target package shape, ingest rules, dashboard behavior, status, and do-not-run-tests gate. |
| `docs/architecture/README.md` | Created. Points to `workspace-migration.md` and `visual-asset-package-contract.md`. |
| `AGENTS.md` | Updated with pointer to the visual asset package contract. |
| `CLAUDE.md` | Updated with pointer to the visual asset package contract. |
| `GEMINI.md` | Updated with pointer to the visual asset package contract. |
| `docs/index.md` and `docs/README.md` | Updated with the contract pointer. |
| `index.json` | Updated with `visual_asset_package_contract`. |
| `snapshots/LATEST.md` | Points to `DEEP_MEMORY_DANTEDASH_003.md`. |
| `snapshots/index.md` | Includes `DEEP_MEMORY_DANTEDASH_003.md`. |
| Dashboard KB stats | Verified via `curl`: `{"total":4188,"by_modality":{"image":2094,"text":2094}}`. |
| Example image file | `aftersun-2022-001.jpg` exists under `/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets/film-stills/aftersun-2022/`. |
| Example Gemini card files | `aftersun-2022-001.json` and `.md` exist under `/Users/vidigal/Dante/.../analysis-cards/cards/film-stills/aftersun-2022/`. |
| Example decoupage files | Mock smoke JSON and Markdown exist under `/Users/vidigal/Dante/.../analysis-cards/decoupage/sidecars|markdown/film-stills/aftersun-2022/`. |

## User Intent / Not Yet Verified

- Andre wants all agents caring for Dante Multimodal Dashboard to understand the current and target package shape for each image.
- The key product requirement is that every visual artifact remains tied together by image identity, not scattered as unrelated KB documents.
- Andre explicitly said he will notify the agent when it is ready to run tests. Future agents should not proactively run live model calls, Chroma ingest, delete, clear, or reindex just because this contract exists.
- The real OpenAI decoupage run is not done yet. Only a zero-cost mock sidecar exists for `aftersun-2022-001`.
- The decoupage ingest into Chroma is not implemented yet.

## Current State

The Dante visual corpus currently has 2,094 image vectors and 2,094 text nodes
from the existing Gemini visual card ingest, for a total of 4,188 KB items.

For `aftersun-2022-001`, the current verified package is:

```text
aftersun-2022-001
├── original image / preview
│   ├── source file exists outside the app workspace
│   ├── source_sha256: 0d25ee0747336d6011c0e137427b6acae705a0826a1196e233266d84544c90c2
│   └── KB node: dante_visual_img_0d25ee0747336d6011c0e137427b6aca
│
├── visual embedding
│   ├── provider/model: Voyage voyage-multimodal-3.5
│   ├── dimensions: 1024
│   └── status: indexed in Chroma as image
│
├── current Gemini analysis
│   ├── JSON and Markdown card files exist
│   ├── schema: image_analysis_card.v1
│   ├── artifact_type: visual_analysis_bundle
│   ├── KB node: dante_visual_card_0d25ee0747336d6011c0e137427b6aca
│   ├── linked_image_file_id: dante_visual_img_0d25ee0747336d6011c0e137427b6aca
│   └── preview_image_file_id: dante_visual_img_0d25ee0747336d6011c0e137427b6aca
│
└── premium decoupage analysis
    ├── JSON and Markdown sidecars exist from mock smoke only
    ├── profile_id: art_grade_decoupage_vision_analyst.gpt55_port.v1
    ├── lens: solo
    ├── frame_type: film_frame
    └── status: exists on disk but not indexed in Chroma yet
```

The target package after the next implementation units is documented in:

```text
docs/architecture/visual-asset-package-contract.md
```

## Items Already Done

### P0

- Created the visual asset package contract for current and target state:
  `docs/architecture/visual-asset-package-contract.md`.
- Documented that every image package must be tied by `dante_image_id`,
  `source_sha256`, `linked_image_file_id`, and `preview_image_file_id`.
- Documented current package state for `aftersun-2022-001`.
- Documented target package state with image node, visual embedding, Gemini
  card node, and future decoupage node.
- Captured the explicit no-tests/no-ingest gate until Andre says the system is
  ready.

### P1

- Updated agent discovery surfaces: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`,
  `docs/index.md`, `docs/README.md`, `docs/architecture/README.md`, and
  `index.json`.
- Preserved the existing workspace snapshot protocol and created
  `DEEP_MEMORY_DANTEDASH_003.md`.

### P2

- The decoupage profile/provider/harness work from the previous step remains in
  place:
  - prompt: `backend/app/dante_visual/prompts/art_grade_decoupage_vision_analyst.md`;
  - schema: `backend/app/dante_visual/schemas/decoupage_sidecar.schema.json`;
  - helper: `backend/app/dante_visual/decoupage.py`;
  - provider: `backend/app/dante_visual/openai_decoupage_provider.py`;
  - harness: `scripts/dante_visual_decoupage_harness.py`;
  - docs: `docs/prompts/art-grade-decoupage-vision-analyst.md`.

## Items To Do

### P0

- Implement decoupage ingest into Chroma, mirroring the existing
  `visual_analysis_bundle` link strategy:
  - collect decoupage JSON/Markdown sidecars;
  - resolve `source_sha256` and `dante_image_id`;
  - verify linked image node exists;
  - create `visual_decoupage_bundle` text nodes;
  - store `linked_image_file_id` and `preview_image_file_id`;
  - write run manifest and summary;
  - keep ingest idempotent by node id / source hash.
- Wait for Andre's explicit "ready for tests" before running live ingest or
  provider tests that mutate Chroma or call paid APIs.

### P1

- Add dashboard grouping behavior so image, Gemini analysis, and decoupage
  analysis can be inspected as one linked visual asset package.
- Add search/chat behavior that can cite the best layer for the question while
  preserving shared image preview context.
- Decide whether the primary decoupage node id remains:
  `dante_visual_decoupage_<source_sha256[:32]>`, with optional lens-specific
  suffixes later for multi-lens expansion.

### P2

- Run a real OpenAI decoupage smoke after credentials and cost are approved.
- Scale from 1 image to a small stratified batch, then to 100, then to all
  2,094 images only after schema, cost, and visual QA are accepted.
- Consider multi-lens decoupage later (`judge`, `confrontador`, `dp`,
  `art_cast`, `critic`) without disrupting the primary `solo` package.

## Installed Skills And Commands

### Workspace-local

- `scripts/smoke-dante-dashboard.sh`
- `scripts/dante_visual_analysis_harness.py`
- `scripts/dante_visual_full_auto_harness.py`
- `scripts/dante_visual_vector_ingest.py`
- `scripts/dante_visual_card_ingest.py`
- `scripts/dante_visual_decoupage_harness.py`

### Codex

- `snapshot` skill used from `/Users/vidigal/.codex/skills/snapshot/SKILL.md`.
- Standard local commands available: `rg`, `uv`, `pnpm`, `curl`, `python`.

### Claude Code

- Claude Code should read `CLAUDE.md`, `snapshots/LATEST.md`, and
  `docs/architecture/visual-asset-package-contract.md` before working on this
  visual package lane.

### OpenClaw

- No OpenClaw-specific command was configured in this turn.

## Pending Decisions

- Andre must say when the system is ready for tests.
- Whether to implement only primary `solo` decoupage ingest first, or include a
  future-proof lens suffix strategy immediately.
- Whether the dashboard grouped view should be implemented before or after the
  first decoupage Chroma ingest.
- Which approved OpenAI vision reasoning model to use for the real decoupage
  run if `gpt-5.5` is unavailable or not configured.

## Next Safe Step

- Wait for Andre's readiness signal. Then implement the decoupage ingest module
  and tests without running live model calls or mutating Chroma until the test
  gate is explicitly opened.

## Do Not Do Automatically

- Do not persist API keys, tokens, shell profile exports, or provider credentials.
- Do not mutate unrelated workspaces or global agent runtimes unless explicitly requested.
- Do not claim current pricing, model availability, or provider behavior without fresh verification.
- Do not run live OpenAI decoupage calls before Andre confirms readiness.
- Do not run Chroma ingest, delete, clear, or reindex before Andre confirms readiness.
- Do not merge all visual layers into one giant text document. Preserve image,
  Gemini card, and decoupage as separate but linked KB nodes.
- Do not treat mock decoupage output as real premium analysis.
- Do not move or rewrite source high-resolution assets.

## Evidence Commands

```bash
cd /Users/vidigal/codex/dantedash
sed -n '1,260p' docs/architecture/visual-asset-package-contract.md
sed -n '1,140p' AGENTS.md
sed -n '1,140p' CLAUDE.md
sed -n '1,80p' GEMINI.md
sed -n '1,120p' index.json
curl -fsS http://127.0.0.1:8035/api/stats
find snapshots -maxdepth 1 -type f -name 'DEEP_MEMORY_DANTEDASH_*.md' | sort
sed -n '1,160p' snapshots/LATEST.md
sed -n '1,220p' snapshots/DEEP_MEMORY_DANTEDASH_003.md
```
