# Dante Multimodal Dashboard Index

## Navigation

| Path | Purpose | Open |
|---|---|---|
| `README.md` | Primary context and handoff overview | `README.md` |
| `index.json` | Machine-readable path map and compatibility surfaces | `index.json` |
| `snapshots/` | Deep memories, latest pointer, template, and continuation rules | `snapshots/LATEST.md` |
| `AGENTS.md` | Codex/local agent instructions | `AGENTS.md` |
| `CLAUDE.md` | Claude Code workspace instructions | `CLAUDE.md` |
| `README-DANTE.md` | Model contract, visual harness, and MCP details | `README-DANTE.md` |
| `docs/runbooks/` | Operator runbooks | `docs/runbooks/dante-dashboard-operations.md` |
| `docs/architecture/` | Migration and architecture notes | `docs/architecture/workspace-migration.md` |
| `backend/` | FastAPI backend and MCP wrapper | `backend/` |
| `frontend/` | Vite/React dashboard frontend | `frontend/` |
| `electron/` | Electron shell and app assets | `electron/` |
| `scripts/` | Startup, smoke, visual-analysis, and packaging scripts | `scripts/` |
| `chroma_db/` | Ignored local app Chroma runtime copy for v1 | `chroma_db/` |
| `uploads/` | Ignored app upload/runtime directory | `uploads/` |

## Snapshot Memory

- Latest pointer: `snapshots/LATEST.md`
- Snapshot index: `snapshots/index.md`
- Template: `snapshots/TEMPLATE_DEEP_MEMORY.md`
- Settings: `settings/snapshot-memory.md`

## Scope Boundary

- This workspace owns the Dante Multimodal Dashboard app only.
- It does not own or move the canonical Knowledge Hub runtime.
- It does not own or move the Obsidian vault or source high-resolution image library.
- Runtime data copied into `chroma_db/` and `uploads/` is ignored by git and exists only to keep v1 bootable.
