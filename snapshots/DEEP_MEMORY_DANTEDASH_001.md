# DEEP MEMORY DANTEDASH 001

Snapshot date: 2026-06-15 01:39:40 -03
Workspace: `/Users/vidigal/codex/dantedash`
Status: First app-only handoff snapshot after promoting Dante Multimodal Dashboard into its own workspace.

## Resume Output Contract

When the user returns with `continue`, `continua`, `retoma`, or a context-loss
recovery request, read `snapshots/LATEST.md` first, then this snapshot, then
answer with exactly two humanized PT-BR summary lines followed by a short
`Next Steps` list grouped by priority.

Use this shape:

```text
O Dante Multimodal Dashboard agora tem workspace próprio em /Users/vidigal/codex/dantedash, com snapshot local, README, index.json e ponteiros de handoff.
O app está separado do Knowledge Hub; o serviço vivo estava saudável no último check com 4188 itens e o sidecar antigo ficou preservado como rollback.

Next Steps:
P0 - [highest priority group]
- [next action]

P1 - [next priority group]
- [next action]
```

Do not mutate files during recovery until the user gives a new instruction,
unless the user explicitly asks to continue execution.

## Verified On Filesystem

| Path / Surface | Verified State |
|---|---|
| `/Users/vidigal/codex/dantedash` | Primary dashboard workspace exists and is a git working copy. |
| `/Users/vidigal/codex/dantedash/AGENTS.md` | Declares this workspace owns the dashboard app and contains the snapshot protocol. |
| `/Users/vidigal/codex/dantedash/CLAUDE.md` | Created for Claude Code continuity and points to the same snapshot sequence. |
| `/Users/vidigal/codex/dantedash/snapshots/` | Created as the app-specific local deep-memory directory. |
| `/Users/vidigal/codex/dantedash/snapshots/LATEST.md` | Points to `DEEP_MEMORY_DANTEDASH_001.md`. |
| `/Users/vidigal/codex/dantedash/snapshots/index.md` | Lists the first dashboard snapshot. |
| `/Users/vidigal/codex/dantedash/index.json` | Created as the machine-readable handoff/path map. |
| `/Users/vidigal/codex/dantedash/README.md` | Rewritten as the dashboard-specific README and handoff entrypoint. |
| `/Users/vidigal/codex/dantedash/chroma_db` | Local app Chroma runtime copy exists; it is ignored by git. |
| `/Users/vidigal/codex/dantedash/backend/.env` | Exists locally and points `KB_PERSIST_DIR`/`KB_UPLOAD_DIR` at this workspace; raw contents must not be printed. |
| `/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag` | Old sidecar remains intact as rollback. |
| LaunchAgent `com.vidigal.obsidian-dante-multimodal-rag` | Last verified running with working directory `/Users/vidigal/codex/dantedash`. |
| Backend `http://127.0.0.1:8035/api/stats` | Last verified response: `4188` total, `2094` image, `2094` text. |
| Frontend `http://127.0.0.1:5173/` | Last verified via smoke script and HTTP HEAD. |

## User Intent / Not Yet Verified

- User wants the Dante Multimodal Dashboard to become its own well-organized
  workspace while preserving the Obsidian thread continuity.
- User explicitly clarified that only the app and work related to the app should
  move. The canonical Knowledge Hub, Obsidian vault, source assets, and other KBs
  must not be moved.
- User wants a first snapshot and durable handoff artifacts: `snapshots/`,
  `AGENTS.md` pointer, `CLAUDE.md`, `index.json`, `README.md`, and enough
  context for future agents.
- Not yet verified in this snapshot: live MCP tool calls through every external
  client after their next restart. Config paths were repointed, but clients may
  need restart/reload to pick them up.

## Current State

The Dante Multimodal Dashboard app has been promoted into:

```text
/Users/vidigal/codex/dantedash
```

The old Obsidian sidecar was not deleted and remains the rollback path:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

The live app still uses the same stable local ports:

- Backend: `http://127.0.0.1:8035`
- Frontend: `http://127.0.0.1:5173`

The app-specific Chroma runtime was copied into the new workspace for v1
continuity:

```text
/Users/vidigal/codex/dantedash/chroma_db
/Users/vidigal/codex/dantedash/uploads
```

This is not the canonical Knowledge Hub. It is the dashboard sidecar collection:

```text
dante_multimodal_kb
```

The expected live shape is:

```json
{"total":4188,"by_modality":{"image":2094,"text":2094}}
```

## Items Already Done

### P0

- Promoted the dashboard app workspace into `/Users/vidigal/codex/dantedash`
  without deleting the old Obsidian sidecar.
- Copied app source, docs, tests, Electron wrapper, scripts, git metadata where
  useful, and local v1 runtime Chroma/uploads data.
- Excluded rebuildable dependency/caches from the initial copy:
  `node_modules/`, `backend/.venv/`, `__pycache__/`, `.pytest_cache/`,
  `.ruff_cache/`, logs, and generated build noise.
- Updated `backend/.env` in the new workspace so `KB_PERSIST_DIR` and
  `KB_UPLOAD_DIR` point to `/Users/vidigal/codex/dantedash`.
- Added/updated `.gitignore` so `backend/.env`, `chroma_db/`, `uploads/`,
  `logs/`, dependency folders, and generated build output stay out of git.
- Kept the canonical Knowledge Hub out of scope and did not move it.

### P1

- Added app workspace identity and operator docs:
  - `AGENTS.md`
  - `README-DANTE.md`
  - `docs/runbooks/dante-dashboard-operations.md`
  - `docs/architecture/workspace-migration.md`
  - `docs/dante-multimodal-mcp.md`
- Added read-only smoke validation:
  - `scripts/smoke-dante-dashboard.sh`
- Installed dependencies in the new workspace after copying without caches.
- Ran frontend typecheck successfully.
- Ran frontend production build successfully.
- Ran backend focused tests successfully:
  - `tests/test_mcp_server.py`
  - `tests/test_mcp_preview.py`
  - `tests/test_library_get_item.py`
  - `tests/test_schemas.py`
  - Result: 17 passed.
- Rebuilt `/Applications/Dante Multimodal Dashboard.app` from the new workspace.
- Improved `scripts/build-electron-app.sh` so it attempts Electron postinstall
  if the runtime app bundle is missing.

### P2

- Repointed the external launch runner:
  `/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/bin/run-dante-multimodal-rag.sh`
  now defaults to `/Users/vidigal/codex/dantedash` and has an explicit fallback
  to the old sidecar.
- Repointed LaunchAgent `WorkingDirectory` to `/Users/vidigal/codex/dantedash`
  while preserving the legacy label:
  `com.vidigal.obsidian-dante-multimodal-rag`.
- Repointed MCP client configs for:
  - Codex: `/Users/vidigal/.codex/config.toml`
  - Claude Desktop:
    `/Users/vidigal/Library/Application Support/Claude/claude_desktop_config.json`
  - Claude Code:
    `/Users/vidigal/.claude.json`
- Updated `dantedash --status` so it reports the active project root.
- Created the first snapshot protocol and handoff artifacts:
  - `snapshots/DEEP_MEMORY_DANTEDASH_001.md`
  - `snapshots/LATEST.md`
  - `snapshots/index.md`
  - `snapshots/TEMPLATE_DEEP_MEMORY.md`
  - `settings/snapshot-memory.md`
  - `README.md`
  - `index.md`
  - `index.json`
  - `CLAUDE.md`

## Items To Do

### P0

- Before any future migration/cleanup, confirm the live health again with:
  `scripts/smoke-dante-dashboard.sh`, `dantedash --status`, and backend stats.
- Keep Knowledge Hub and Obsidian vault out of scope unless Andre explicitly
  asks for those systems.
- If there is any doubt about app vs Knowledge Hub, stop and report the exact
  path/surface being changed before mutating.

### P1

- After a stable period, plan option 3 cleanup:
  - Move Chroma/uploads/logs fully outside the repo into the Dante data
    directory.
  - Rename the legacy LaunchAgent label from `obsidian` to a dashboard-specific
    label.
  - Replace the old sidecar checkout with an intentional archive or symlink
    only after every reference has been repointed and verified.
- Re-run a full MCP smoke from actual clients after client restart/reload:
  `stats`, `search`, `get_item`, `preview`, `chat`.
- Decide whether the git remote should remain the starter-template remote or be
  changed to a dedicated Dante Dashboard repository.

### P2

- Consider cleaning or replacing bootstrap READMEs generated in ignored runtime
  folders (`chroma_db/`, `uploads/`) after option 3 externalizes runtime data.
- Consider splitting large frontend bundle if chunk size matters; current build
  passed with a Vite warning about a chunk above 500 kB.
- Consider adding a dedicated dashboard status endpoint that reports active
  project root, model contract, and non-secret provider status.

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

- Snapshot skill used for this memory:
  `/Users/vidigal/.codex/skills/snapshot/SKILL.md`
- Codex MCP config now points `dante-multimodal-rag` at:
  `/Users/vidigal/codex/dantedash/backend`

### Claude Code / Claude Desktop

- Claude Desktop MCP config now points `dante-multimodal-rag` at:
  `/Users/vidigal/codex/dantedash/backend`
- Claude Code config path updated in `/Users/vidigal/.claude.json`.

## Pending Decisions

- When to perform option 3 cleanup and move runtime data out of the repo.
- Whether to rename LaunchAgent label away from the legacy Obsidian name.
- Whether to change the git remote away from the upstream starter template.
- Whether to preserve the old sidecar as a long-lived archive or replace it with
  a symlink/README after the new workspace is stable.

## Next Safe Step

Run a read-only health check from the new workspace:

```bash
cd /Users/vidigal/codex/dantedash
scripts/smoke-dante-dashboard.sh
dantedash --status
```

If healthy, continue feature work only in `/Users/vidigal/codex/dantedash`.

## Do Not Do Automatically

- Do not move, delete, reindex, or merge the canonical Knowledge Hub.
- Do not move or rewrite the Obsidian vault.
- Do not move source high-resolution assets into this repo.
- Do not run ingest, clear, delete, or reindex as part of recovery.
- Do not print or persist raw API keys, tokens, `.env` contents, sessions, or
  provider credentials.
- Do not delete the old sidecar without explicit approval.
- Do not rename LaunchAgent labels or global commands without a rollback plan.

## Evidence Commands

```bash
cd /Users/vidigal/codex/dantedash

find snapshots -maxdepth 1 -type f | sort
sed -n '1,160p' snapshots/LATEST.md
sed -n '1,220p' snapshots/DEEP_MEMORY_DANTEDASH_001.md

curl -fsS --max-time 3 http://127.0.0.1:8035/api/stats
curl -fsSI --max-time 3 http://127.0.0.1:5173/
scripts/smoke-dante-dashboard.sh
dantedash --status

launchctl print "gui/$(id -u)/com.vidigal.obsidian-dante-multimodal-rag" \
  | rg -n "state =|pid =|working directory =|runs ="

git status --short --branch
git check-ignore -v backend/.env chroma_db/chroma.sqlite3 uploads logs
```
