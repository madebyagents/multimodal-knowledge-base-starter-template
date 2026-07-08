# Dante Multimodal Dashboard

Primary workspace:

```text
/Users/vidigal/codex/dantedash
```

This repository owns the Dante Multimodal Dashboard app: FastAPI backend,
Vite/React frontend, Electron wrapper, launcher scripts, read-only MCP wrapper,
operator docs, and app-specific snapshot handoff files.

## Scope Boundary

This workspace is app-only.

In scope:

- Dashboard UI and Electron app.
- Backend API on `127.0.0.1:8035`.
- Frontend on `127.0.0.1:5173`.
- Local app Chroma collection `dante_multimodal_kb`.
- Read-only Knowledge Hub cockpit under `/api/knowledge-hub/*`.
- KH-native KB read operation for text search, chat source cards, stats,
  library, and previews through `DANTEDASH_KB_BACKEND=knowledge_hub`.
- MCP wrapper named `dante-multimodal-rag`.
- CLI launch aliases such as `dantedash`, `dantevision`, and `dante menu`.

Out of scope:

- Canonical `knowledge-hub` runtime.
- Obsidian vault content.
- Source high-resolution visual assets.
- Provider credentials and secret storage.

The previous Obsidian sidecar is kept as rollback only:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

## Current Stable Interfaces

| Surface | Value |
|---|---|
| Backend | `http://127.0.0.1:8035` |
| Frontend | `http://127.0.0.1:5173` |
| Knowledge Hub cockpit | `/api/knowledge-hub/*` |
| KB backend status | `/api/kb/status` |
| LaunchAgent label | `com.vidigal.obsidian-dante-multimodal-rag` |
| MCP server | `dante-multimodal-rag` |
| Electron app | `/Applications/Dante Multimodal Dashboard.app` |
| Main CLI | `dantedash --status` |

Expected current KB shape:

```json
{"total":8099,"by_modality":{"image":2231,"text":4187,"video":1681}}
```

The current KB includes the linked local media ingest for
`tim-black-vidigal-parte-01`: 374 unique source files, 137 image nodes, and
1,681 video frame/full-video nodes. The source media stays in the Dropbox inbox
folder and is not copied into `uploads/`.

## Local Data Stores

The dashboard now uses Knowledge Hub as the primary read backend for text
search, chat retrieval source cards, stats, item lookup, and previews. Chroma is
still kept on disk and available as fallback for image-query search until that
path is decided separately.

The dashboard uses two local app stores:

- `chroma_db/` stores the preserved Chroma KB content, embeddings, retrieval
  nodes, and image-query fallback path.
- `backend/app_state/chat.sqlite` stores product chat state: projects, threads,
  messages, thread summaries, curated project memory, selected model/top_k, and
  per-answer source snapshots.

`CHAT_STATE_DB` can override the SQLite path. The file is ignored by git and may
contain user chat text, so back it up before deleting or moving it. Resetting the
SQLite file resets chat workspaces only; it does not clear Chroma, uploads, or
indexed KB content.

## Knowledge Hub Cockpit

DanteDash can inspect the broader Knowledge Hub through a local read-only Hub
tab. The backend proxies safe health, topology, KB catalog, OpenAPI capability,
and retrieval calls from the external Knowledge Hub API and Actions bridge, then
groups those with the existing multimodal Chroma search, Vault Index, and Graph
surfaces.

This does not move or embed the canonical Knowledge Hub runtime. The cockpit
does not expose ingest, sync, jobs, evals, staging, start/stop, reindex, or vault
mutation controls.

## Model Contract

- Multimodal embeddings: Voyage `voyage-multimodal-3.5`, 1024 dimensions.
- Chat model: DeepSeek `deepseek-v4-pro`.
- Text reranker: Cohere `rerank-v4.0-pro`.
- Visual analysis cards: Gemini vision provider where configured.

The backend is the only process that should read provider credentials. MCP
clients, launchers, docs, and snapshots must never expose raw API keys.

## Navigation

- Machine-readable path map: `index.json`
- Human navigation index: `index.md`
- Latest snapshot pointer: `snapshots/LATEST.md`
- First app-only handoff snapshot:
  `snapshots/DEEP_MEMORY_DANTEDASH_001.md`
- Operator runbook: `docs/runbooks/dante-dashboard-operations.md`
- Migration note: `docs/architecture/workspace-migration.md`
- MCP docs: `docs/dante-multimodal-mcp.md`
- Visual analysis harness docs: `docs/dante-visual-analysis-harness.md`

## Start And Health

Open/status through the global launcher:

```bash
dantedash --status
```

Manual foreground start:

```bash
/Users/vidigal/codex/dantedash/scripts/start-dante-multimodal-rag.sh
```

The launcher defaults to:

```bash
DANTEDASH_KB_BACKEND=knowledge_hub
DANTEDASH_CHROMA_FALLBACK_ENABLED=true
```

Rollback for a session remains:

```bash
DANTEDASH_KB_BACKEND=chroma /Users/vidigal/codex/dantedash/scripts/start-dante-multimodal-rag.sh
```

Read-only smoke:

```bash
/Users/vidigal/codex/dantedash/scripts/smoke-dante-dashboard.sh
curl -fsS http://127.0.0.1:8035/api/stats
curl -fsS http://127.0.0.1:8035/api/kb/status
curl -fsSI http://127.0.0.1:5173/
```

## Snapshot Protocol

This repo uses local deep-memory snapshots under:

```text
snapshots/
```

Future agents should read `snapshots/LATEST.md` first, then the pointed
snapshot, before answering `continue`, `continua`, or `retoma`.

Resume answers must be in PT-BR with exactly two humanized summary lines
followed by a `Next Steps` list grouped by priority.

## Rollback

The old sidecar was not deleted. For v1 rollback, restore:

- External runner backup:
  `/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/bin/run-dante-multimodal-rag.sh.backup-20260615-011800`
- LaunchAgent backup:
  `/Users/vidigal/Library/LaunchAgents/com.vidigal.obsidian-dante-multimodal-rag.plist.backup-20260615-011800`
- Previous app backup:
  `/Applications/Dante Multimodal Dashboard.app.backup-20260615-012223`

Do not perform rollback automatically unless Andre explicitly asks.
