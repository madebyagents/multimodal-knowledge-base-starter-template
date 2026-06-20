# Dante Multimodal Dashboard Operations

## Purpose

`/Users/vidigal/codex/dantedash` is the primary workspace for the Dante
Multimodal Dashboard. It serves a local multimodal RAG knowledge base through a
FastAPI backend, a Vite frontend, an Electron application, CLI aliases, and a
read-only MCP wrapper.

## Stable Interfaces

- Backend: `http://127.0.0.1:8035`
- Frontend: `http://127.0.0.1:5173`
- MCP server: `dante-multimodal-rag`
- Knowledge Hub cockpit: `/api/knowledge-hub/*`
- KB backend status: `/api/kb/status`
- LaunchAgent label: `com.vidigal.obsidian-dante-multimodal-rag`
- Electron app: `/Applications/Dante Multimodal Dashboard.app`
- Global aliases: `dantedash`, `dantedashboard`, `dantevision`,
  `dante-multi`, `dantego`, `multimodal-rag`
- Menu command: `dante menu`

The LaunchAgent label intentionally keeps the old `obsidian` name during v1 so
existing aliases and Electron health checks keep working.

## Model Contract

- Multimodal embeddings: Voyage `voyage-multimodal-3.5`, 1024 dimensions.
- Chat model: DeepSeek `deepseek-v4-pro`.
- Text reranker: Cohere `rerank-v4.0-pro`.
- Visual analysis cards: Gemini vision provider where configured.
- Black Label graph view: read-only LightRAG GraphML explorer where the local
  graph source is configured or present.
- Knowledge Hub cockpit: read-only inspection of the external KH API, Actions
  bridge, KB catalog, topology, retrieval, Graph, Vault Index, and multimodal
  Chroma search.
- DanteDash KB reads: KH-native for text search, chat source cards, stats,
  library, previews, and image-query search; Chroma fallback is disabled by
  default and kept only as an explicit rollback mode.

The backend process is the only service that should read provider credentials.
MCP clients and launchers must not receive raw provider secrets.

## Start And Stop

Start through launchd:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vidigal.obsidian-dante-multimodal-rag.plist
launchctl kickstart -k gui/$(id -u)/com.vidigal.obsidian-dante-multimodal-rag
```

Stop through launchd:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.vidigal.obsidian-dante-multimodal-rag.plist
```

Manual foreground start:

```bash
/Users/vidigal/codex/dantedash/scripts/start-dante-multimodal-rag.sh
```

The launcher defaults to KH-native reads with Chroma fallback disabled:

```bash
DANTEDASH_KB_BACKEND=knowledge_hub
DANTEDASH_CHROMA_FALLBACK_ENABLED=false
```

To temporarily run the old Chroma-primary mode for a session:

```bash
DANTEDASH_KB_BACKEND=chroma /Users/vidigal/codex/dantedash/scripts/start-dante-multimodal-rag.sh
```

## Health Checks

```bash
curl -fsS http://127.0.0.1:8035/api/stats
curl -fsS http://127.0.0.1:8035/api/kb/status
curl -fsSI http://127.0.0.1:5173/
dantedash --status
/Users/vidigal/codex/dantedash/scripts/smoke-dante-dashboard.sh
```

Expected current KB count:

```json
{"total":8099,"by_modality":{"image":2231,"text":4187,"video":1681}}
```

Graph health is read-only:

```bash
curl -fsS http://127.0.0.1:8035/api/graph/health
curl -fsS "http://127.0.0.1:8035/api/graph/search?q=treatment&limit=3"
```

Knowledge Hub cockpit health is read-only and KH is optional by default:

```bash
curl -fsS http://127.0.0.1:8035/api/knowledge-hub/health
curl -fsS http://127.0.0.1:8035/api/knowledge-hub/capabilities
```

Default dashboard smoke warns when the external KH API or Actions bridge is
down. Use strict KH smoke only on machines expected to have both services live:

```bash
DANTE_KH_STRICT_SMOKE=1 /Users/vidigal/codex/dantedash/scripts/smoke-dante-dashboard.sh
```

The GraphML source is backend configuration only. The default local source is
the Black Label LightRAG `graph_chunk_entity_relation.graphml`, and it can be
overridden with `DANTE_LIGHTRAG_GRAPHML_PATH`. The API returns redacted source
metadata and must not expose absolute local paths in normal HTTP payloads.

## Local App State

DanteDash keeps Knowledge Base data and chat workspace state separate:

- Chroma: `chroma_db/` stores indexed KB nodes, embeddings, and retrieval data.
- SQLite: `backend/app_state/chat.sqlite` stores projects, threads, messages,
  thread summaries, curated project memory, model/top_k choices, and persisted
  source snapshots for the chat Context panel.

Override the SQLite path with `CHAT_STATE_DB` when needed. Treat this file as
local user data: it is ignored by git and can contain chat text. To reset chat
workspaces only, stop the app and move or delete the SQLite file. Do not use KB
clear, ingest, delete, or reindex commands for a chat-state reset.

The smoke script performs one lightweight workspace write by creating and then
archiving a temporary thread under the default project. It does not ingest,
delete, clear, or reindex KB content.

The smoke script now expects `/api/kb/status` to report
`mode=knowledge_hub`, `chroma_available_as_fallback=false`, and
`image_query_search=knowledge_hub`. Override with
`DANTEDASH_CHROMA_FALLBACK_ENABLED=true` for temporary fallback testing, or
`DANTE_EXPECTED_KB_BACKEND=chroma` only when intentionally validating
Chroma-primary rollback.

The same smoke script checks `/api/graph/health`. Missing external GraphML is a
warning by default so unrelated dashboard health still passes. Use strict graph
smoke only on machines expected to have the Black Label graph:

```bash
DANTE_GRAPH_STRICT_SMOKE=1 /Users/vidigal/codex/dantedash/scripts/smoke-dante-dashboard.sh
```

## Workspace Shell

The left workspace sidebar is a client-side shell control. Users can hide or
restore it from the top bar, or with `Cmd+B` / `Ctrl+B` when focus is not inside
an editor control. The expanded sidebar width is adjustable by dragging its
right edge and is persisted locally. Collapsing or resizing the sidebar does not
change projects, threads, chat state, KB data, GraphML, ingest, or runtime
configuration.

## Graph View

The Graph tab is a read-only relationship map over the external LightRAG
GraphML. Search, route/entity filters, top nodes, source hints, and the
inspector use `/api/graph/*` endpoints and work without a canvas.

The visual renderer is opt-in:

1. Opening the Graph tab starts with the visual paused.
2. `Show visual` lazy-loads the renderer and mounts bounded graph canvases.
3. `Pause visual`, leaving the Graph tab, or unmounting the panel destroys the
   renderer and removes its canvases.

Graph focus mode is layout-only. `Focus graph` hides the Graph tab search/results
rail and inspector rail so the renderer can use the wider center area. `Exit
focus` restores both rails with the current search, filter, selection, and
visual pause state intact. The keyboard shortcut is `F` when focus is not inside
a text field.

Do not use Graph View operations for ingest, reindex, clear, delete, or vault
mutation. The graph source should remain an external read-only file.

## Knowledge Hub Cockpit

The Hub tab groups local read-only memory surfaces:

- DanteDash multimodal Chroma KB.
- External Knowledge Hub API at `KNOWLEDGE_HUB_BASE_URL`, default
  `http://127.0.0.1:8080`.
- Knowledge Hub Actions bridge at `KNOWLEDGE_HUB_ACTIONS_BASE_URL`, default
  `http://127.0.0.1:8098`.
- Black Label Graph View.
- External Vault Index.

The backend may use `KNOWLEDGE_HUB_ACTIONS_BEARER_TOKEN` for local Actions
bridge auth, but the token is backend-only and must never be sent to the
frontend. `KNOWLEDGE_HUB_TIMEOUT_S` keeps KH calls short. `KNOWLEDGE_HUB_STRICT_SMOKE`
or `DANTE_KH_STRICT_SMOKE=1` turns optional KH smoke into a required health
gate.

V1 is explicitly read-only. Do not add UI or proxy routes for KH ingest, phase2,
workspace sync, jobs, evals, inbox staging, start/stop, reindex, or vault
mutation without a separate operator-control plan.

## MCP Smoke

The MCP wrapper runs from:

```bash
cd /Users/vidigal/codex/dantedash/backend
uv run python -m app.mcp_server
```

Read-only tool smoke order:

1. `stats`
2. `search`
3. `get_item`
4. `preview`
5. `chat`

## Rollback

The old Obsidian sidecar remains intact at:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

Rollback for v1 is intentionally simple:

1. Restore the external runner or set `DANTE_MULTIMODAL_PROJECT_ROOT` to the old
   sidecar path.
2. Restore the LaunchAgent `WorkingDirectory` to the old sidecar path.
3. Restart the existing LaunchAgent label.

Do not delete the old sidecar until the option 3 cleanup phase is explicitly
approved.

## Secret Safety

Ignored local files include:

```text
backend/.env
chroma_db/
uploads/
logs/
backend/.venv/
node_modules/
```

Never print raw `.env` contents or API keys in logs, docs, commits, or MCP
configuration.
