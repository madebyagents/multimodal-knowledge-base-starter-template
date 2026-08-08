# DEEP MEMORY DANTEDASH 002

Snapshot date: 2026-06-15 01:59:38 -03
Workspace: `/Users/vidigal/codex/dantedash`
Status: Second Dante Multimodal Dashboard thread snapshot after tightening `AGENTS.md` and `CLAUDE.md` with app-specific operating rules and verification gates.

## Resume Output Contract

When the user returns with `continue`, `continua`, `retoma`, or a context-loss
recovery request, read `snapshots/LATEST.md` first, then this snapshot, then
answer with exactly two humanized PT-BR summary lines followed by a short
`Next Steps` list grouped by priority.

Use this shape:

```text
O Dante Multimodal Dashboard está separado em /Users/vidigal/codex/dantedash, com handoff local, snapshots, index.json e instruções específicas para agentes.
O serviço estava saudável no último check com 4188 itens, e o contrato atual é não tocar em Knowledge Hub, Obsidian vault, assets fonte ou segredos sem pedido explícito.

Next Steps:
P0 - Estado vivo
- Rodar scripts/smoke-dante-dashboard.sh e dantedash --status antes de mexer em runtime ou app.

P1 - Próxima mudança
- Trabalhar só em /Users/vidigal/codex/dantedash e criar nova snapshot antes de mudanças globais, runtime cleanup ou reindex.
```

Do not mutate files during recovery until the user gives a new instruction,
unless the user explicitly says to continue execution.

## Verified On Filesystem

| Path / Surface | Verified State |
|---|---|
| `/Users/vidigal/codex/dantedash` | Primary dashboard workspace and active target for this snapshot. |
| `snapshots/LATEST.md` | Points to `DEEP_MEMORY_DANTEDASH_002.md`. |
| `snapshots/index.md` | Includes `DEEP_MEMORY_DANTEDASH_001.md` and `DEEP_MEMORY_DANTEDASH_002.md`. |
| `AGENTS.md` | Rewritten with app-specific operating style, scope boundaries, health gates, frontend rules, global-surface safety, and snapshot protocol. |
| `CLAUDE.md` | Rewritten to mirror the same app-specific rules for Claude Code. |
| `GEMINI.md` | Already contains app-only scope guard and snapshot protocol pointer. |
| `README.md` | Dashboard-specific handoff entrypoint exists. |
| `index.json` | Machine-readable map exists and now includes the latest deep-memory file. |
| Backend `http://127.0.0.1:8035/api/stats` | Last verified response: `4188` total, `2094` image, `2094` text. |
| `dantedash --status` | Last verified healthy; reports project root `/Users/vidigal/codex/dantedash`. |
| LaunchAgent `com.vidigal.obsidian-dante-multimodal-rag` | Last verified running with working directory `/Users/vidigal/codex/dantedash`. |

## User Intent / Not Yet Verified

- User asked to save a snapshot "here for our thread"; interpreted as the
  Dante Multimodal Dashboard workspace because this thread has been promoting
  and organizing that app.
- User wants future agents in this workspace to be precise, effective, and safe
  for this app specifically.
- User repeatedly clarified that the move is only for the app and app-related
  work, not the canonical Knowledge Hub, Obsidian vault, or source image assets.
- Not yet verified in this snapshot: actual MCP tool calls from every external
  client after client reload. Configs were repointed earlier, but clients may
  need restart/reload.

## Current State

The Dante Multimodal Dashboard is now treated as its own primary workspace:

```text
/Users/vidigal/codex/dantedash
```

The current local memory protocol is:

```text
snapshots/LATEST.md
snapshots/index.md
snapshots/DEEP_MEMORY_DANTEDASH_001.md
snapshots/DEEP_MEMORY_DANTEDASH_002.md
```

The app remains live on stable ports:

- Backend: `http://127.0.0.1:8035`
- Frontend: `http://127.0.0.1:5173`

The expected app-sidecar collection is:

```text
dante_multimodal_kb
```

Expected current KB shape:

```json
{"total":4188,"by_modality":{"image":2094,"text":2094}}
```

The old Obsidian sidecar remains intact as rollback:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

The repo is intentionally dirty/uncommitted because the work so far promoted the
app, copied existing sidecar changes, added docs/snapshots, and adjusted local
instructions. No commit or staging has been performed in this thread.

## Items Already Done

### P0

- Promoted the Dante Multimodal Dashboard app into `/Users/vidigal/codex/dantedash`.
- Kept the canonical Knowledge Hub out of scope and did not move it.
- Kept the Obsidian vault and source high-resolution assets out of scope.
- Confirmed live app health after migration:
  - Backend stats: `4188` total, `2094` image, `2094` text.
  - `dantedash --status` reports backend healthy and project root
    `/Users/vidigal/codex/dantedash`.
  - LaunchAgent runs with working directory `/Users/vidigal/codex/dantedash`.
- Created first app-only snapshot:
  `snapshots/DEEP_MEMORY_DANTEDASH_001.md`.

### P1

- Created or updated handoff/navigation files:
  - `README.md`
  - `index.md`
  - `index.json`
  - `README-DANTE.md`
  - `docs/runbooks/dante-dashboard-operations.md`
  - `docs/architecture/workspace-migration.md`
  - `docs/dante-multimodal-mcp.md`
- Added snapshot protocol files:
  - `snapshots/LATEST.md`
  - `snapshots/index.md`
  - `snapshots/TEMPLATE_DEEP_MEMORY.md`
  - `settings/snapshot-memory.md`
- Updated local agent instruction files:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `GEMINI.md`
- Read and incorporated useful global conventions from:
  - `/Users/vidigal/.codex/AGENTS.md`
  - `/Users/vidigal/.claude/CLAUDE.md`
  - `/Users/vidigal/AGENTS.md`

### P2

- Tightened `AGENTS.md` and `CLAUDE.md` with:
  - PT-BR conversation / English artifacts.
  - VESPER identity.
  - app-only workspace boundary.
  - hard scope boundaries for Knowledge Hub, Obsidian vault, source assets, and
    secrets.
  - stable runtime contract for ports, LaunchAgent label, MCP name, aliases, and
    Electron app.
  - data and secret safety rules.
  - architecture pointers for backend, frontend, Electron, MCP, scripts, and
    docs.
  - verification gates for backend/frontend/smoke/tests.
  - frontend quality rules for the Slack-inspired dark dashboard UI.
  - global-surface change protocol with backups and rollback notes.
  - resume behavior and snapshot protocol.

## Items To Do

### P0

- On any future resume, read `snapshots/LATEST.md`, then
  `DEEP_MEMORY_DANTEDASH_002.md`, then run read-only health checks before
  touching runtime:
  - `scripts/smoke-dante-dashboard.sh`
  - `dantedash --status`
  - `curl -fsS http://127.0.0.1:8035/api/stats`
- Keep future edits scoped to `/Users/vidigal/codex/dantedash` unless Andre
  explicitly names another target.
- Stop and report exact path/surface before any task could affect Knowledge Hub,
  Obsidian, global configs, source assets, or secrets.

### P1

- For the next app feature or UI change, run the smallest relevant checks:
  - `pnpm typecheck`
  - `pnpm build`
  - focused `uv run pytest` for touched backend/MCP areas.
- For any MCP work, smoke `stats`, `search`, `get_item`, `preview`, and `chat`
  from actual clients after restart/reload when feasible.
- Create a new snapshot before:
  - option 3 cleanup,
  - moving runtime data out of the repo,
  - renaming LaunchAgent labels,
  - changing MCP names/ports/aliases,
  - deleting/archive/symlinking the old sidecar.

### P2

- Consider updating `README.md` and `index.json` after any future structure or
  runtime change so handoff stays accurate.
- Consider adding a dedicated non-secret status endpoint that reports project
  root, collection, provider status, and model contract.
- Consider later cleaning bootstrap README/index files in runtime folders after
  runtime data is externalized.

## Installed Skills And Commands

### Workspace-local

- `scripts/start-dante-multimodal-rag.sh`
- `scripts/smoke-dante-dashboard.sh`
- `scripts/build-electron-app.sh`
- `scripts/dante_visual_analysis_harness.py`
- `scripts/dante_visual_vector_ingest.py`
- `scripts/dante_visual_full_auto_harness.py`
- `backend/app/mcp_server.py`

### Global commands

- `dantedash`
- `dantedashboard`
- `dantevision`
- `dante-multi`
- `dantego`
- `multimodal-rag`
- `dante menu`

### Codex

- Snapshot skill used:
  `/Users/vidigal/.codex/skills/snapshot/SKILL.md`
- Codex MCP config was previously repointed to:
  `/Users/vidigal/codex/dantedash/backend`

### Claude Code / Claude Desktop

- Claude Desktop MCP config was previously repointed to:
  `/Users/vidigal/codex/dantedash/backend`
- Claude Code config path was previously updated in `/Users/vidigal/.claude.json`.

## Pending Decisions

- When to perform option 3 cleanup and move runtime data out of the repo.
- Whether to rename LaunchAgent label away from the legacy Obsidian name.
- Whether to change the git remote away from the upstream starter template.
- Whether to preserve the old sidecar as a long-lived archive or replace it with
  a symlink/README after the new workspace is stable.
- Whether to commit the promoted workspace state in this repo, and if so, how to
  split the commit logically given the large inherited sidecar changes.

## Next Safe Step

Run read-only health checks and then wait for Andre's next instruction:

```bash
cd /Users/vidigal/codex/dantedash
scripts/smoke-dante-dashboard.sh
dantedash --status
```

If healthy, continue app work only inside `/Users/vidigal/codex/dantedash`.

## Do Not Do Automatically

- Do not move, delete, reindex, merge, or mutate the canonical Knowledge Hub.
- Do not move or rewrite the Obsidian vault.
- Do not move source high-resolution assets into this repo.
- Do not run ingest, clear, delete, or reindex as part of recovery.
- Do not print or persist raw API keys, tokens, `.env` contents, sessions, or
  provider credentials.
- Do not delete the old sidecar without explicit approval.
- Do not rename LaunchAgent labels, change MCP names, change ports, or change
  global command behavior without a rollback plan and explicit request.

## Evidence Commands

```bash
cd /Users/vidigal/codex/dantedash

find snapshots -maxdepth 1 -type f | sort
sed -n '1,120p' snapshots/LATEST.md
sed -n '1,180p' snapshots/index.md
sed -n '1,220p' snapshots/DEEP_MEMORY_DANTEDASH_002.md

curl -fsS --max-time 3 http://127.0.0.1:8035/api/stats
dantedash --status
scripts/smoke-dante-dashboard.sh

launchctl print "gui/$(id -u)/com.vidigal.obsidian-dante-multimodal-rag" \
  | rg -n "state =|pid =|working directory =|runs ="

rg -n "Hard Scope Boundaries|Verification Gates|Snapshot Memory Protocol" AGENTS.md CLAUDE.md
git status --short --branch
git check-ignore -v backend/.env chroma_db/chroma.sqlite3 uploads logs backend/.venv node_modules
```
