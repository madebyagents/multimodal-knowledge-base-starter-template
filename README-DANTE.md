# Dante Multimodal Dashboard

This workspace is the primary home for the Dante Multimodal Dashboard:

```text
/Users/vidigal/codex/dantedash
```

The former Obsidian sidecar remains available only as a rollback path during the
v1 migration:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

## Active Model Contract

- Multimodal embeddings: `voyage-multimodal-3.5` at 1024 dimensions.
- Chat model: `deepseek-v4-pro` through the DeepSeek OpenAI-compatible chat API.
- Text reranker: Cohere `rerank-v4.0-pro`.
- Vision analysis cards: optional Gemini provider, currently `gemini-3-flash-preview`.

The existing Dante LightRAG and Smart Connections text stacks continue to use
`voyage-4-large` at 2048 dimensions. This sidecar uses a separate 1024-dim
Chroma collection because multimodal and text-only 2048 vectors cannot be mixed
in one vector store collection.

## Local Ports

- Backend: `http://127.0.0.1:8035`
- Frontend: `http://127.0.0.1:5173`

Port `8000` was already occupied on this machine, so Vite is launched with:

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8035 pnpm --filter frontend dev --host 127.0.0.1 --port 5173
```

## Start Commands

Single command:

```bash
/Users/vidigal/codex/dantedash/scripts/start-dante-multimodal-rag.sh
```

Backend:

```bash
cd /Users/vidigal/codex/dantedash/backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8035
```

Frontend:

```bash
cd /Users/vidigal/codex/dantedash
VITE_API_PROXY_TARGET=http://127.0.0.1:8035 pnpm --filter frontend dev --host 127.0.0.1 --port 5173
```

## Smoke Checks

```bash
curl -sS http://127.0.0.1:5173/api/stats
curl -sS -H 'Content-Type: application/json' \
  -d '{"query":"Dante visual RAG smoke fixture","top_k":5}' \
  http://127.0.0.1:8035/api/search
```

The local `backend/.env` is intentionally ignored by git and must not be
printed or committed.

## Visual Analysis Harness

The visual-analysis harness creates schema-valid JSON/Markdown cards and a
static review contact sheet for Dante's canonical film stills. The default
provider is deterministic mock. The opt-in Gemini provider sends image bytes and
analysis prompts to the configured Google Gemini API key. Markdown cards keep
the structured fields first, then add anti-fatigue director, DOP/art-director,
and additional interpretive paragraphs.

The premium `Art-Grade Decoupage Vision Analyst` prompt from the current thread
is now stored as a separate local profile, with a strict Responses API
`text.format` schema and Python loaders. It is not yet the production analysis
provider and it does not reindex the KB by itself.

```text
backend/app/dante_visual/prompts/art_grade_decoupage_vision_analyst.md
backend/app/dante_visual/schemas/decoupage_sidecar.schema.json
backend/app/dante_visual/decoupage.py
scripts/dante_visual_decoupage_harness.py
docs/prompts/art-grade-decoupage-vision-analyst.md
```

Safe decoupage mock smoke:

```bash
uv run --project backend python scripts/dante_visual_decoupage_harness.py --run-id visual-decoupage-smoke generate --provider mock --sample 1 --lens solo --force
```

```bash
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke preflight
python scripts/dante_visual_analysis_harness.py --run-id visual-smoke generate --sample 10 --max-premium 2
uv run --project backend python scripts/dante_visual_analysis_harness.py --run-id visual-gemini-premium-smoke-codex generate --provider gemini --sample 1 --max-premium 1
uv run --project backend python scripts/dante_visual_analysis_harness.py --run-id visual-gemini-batch100-stratified-compressed-20260613-codex generate --provider gemini --sample 100 --sample-mode stratified --max-premium 15 --continue-on-error --gemini-timeout 45 --gemini-max-retries 1 --gemini-max-output-tokens 4096
uv run --project backend python scripts/dante_visual_full_auto_harness.py --run-id visual-gemini-full-auto-20260614-codex --all-premium --concurrency 6 --retry-passes 3 --gemini-timeout 75 --gemini-max-retries 3 --gemini-max-output-tokens 6144
```

`gemini-3.5-flash` was not listed by the Gemini API for the configured key at
setup time; `gemini-3-flash-preview` is the configured Flash vision model.

The separate vector-ingest slice embeds the canonical JPG corpus into this
sidecar's Chroma collection with Voyage multimodal embeddings. It is idempotent
by `source_sha256` and does not copy the source images into `backend/uploads`.

```bash
uv run --project backend python scripts/dante_visual_vector_ingest.py --run-id visual-vector-full-20260613-codex ingest --batch-size 12 --max-batch-mb 8
uv run --project backend python scripts/dante_visual_vector_ingest.py --run-id visual-vector-final-validation-codex preflight
```

Current validation: 2,094 image vectors, 2,094 unique Dante visual hashes, 0
duplicate hash rows, 0 failed rows. Current Gemini analysis-card validation:
2,094 all-premium cards, 2,094 Markdown sidecars, 12,468 redacted raw-run
records, 0 remaining errors after retry.

Review output is written under:

```text
/Users/vidigal/Dante/commercial-film-production-kb/13-visual-reference-assets/review/index.html
```

Operational details live in `docs/dante-visual-analysis-harness.md`.

## MCP Wrapper

This sidecar also includes a dedicated read-only MCP server named
`dante-multimodal-rag`. It exposes the live Dante multimodal KB through tools
for `stats`, `search`, `chat`, `get_item`, and `preview`, so Codex, Claude Code,
and other MCP clients do not need to know the raw HTTP endpoints.

```bash
cd /Users/vidigal/codex/dantedash/backend
uv run python -m app.mcp_server
```

Registration and smoke-test details live in `docs/dante-multimodal-mcp.md`.
