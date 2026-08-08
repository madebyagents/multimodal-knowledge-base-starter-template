# Snapshot Memory Settings

## Workspace

- Active workspace: `/Users/vidigal/codex/dantedash`
- Snapshot directory: `snapshots/`
- Deep-memory filename pattern: `DEEP_MEMORY_DANTEDASH_<NNN>.md`
- Shared sequence: all agents must use the highest existing number and save the next sequential file.

## Save Requirements

Whenever a new deep memory is saved:

- Create the next sequential file, for example `DEEP_MEMORY_DANTEDASH_002.md`.
- Update `snapshots/LATEST.md` to point to the new file.
- Update `snapshots/index.md` with the new file, date, theme, and use case.
- Include complete continuation context, verified filesystem facts, user intent, current state, items already done, items to do, pending decisions, next safe step, do-not-do rules, and evidence commands.
- Keep items already done and items to do grouped by priority.

## Continue Requirements

On `continue`, `continua`, `retoma`, or fatigue/context-loss recovery:

1. Read `snapshots/LATEST.md`.
2. Read the snapshot file it points to.
3. Answer in PT-BR with exactly two humanized summary lines.
4. Add a short `Next Steps` list organized in groups and priority order.
5. Wait for user instruction before mutating files unless execution was explicitly requested.

## Safety

- Do not persist secrets, API keys, tokens, auth sessions, shell profile exports, or provider credentials.
- Do not mutate global agent runtimes or unrelated workspaces unless Vidigal explicitly asks for that exact target.
- Create a pre-change snapshot before global skill installation, large folder reorganization, deletion/quarantine work, auth/provider/default changes, or long-running lab work.
