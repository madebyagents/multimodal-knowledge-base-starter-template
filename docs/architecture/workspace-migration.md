# Workspace Migration

## Summary

The Dante Multimodal Dashboard was promoted from the Obsidian sidecar into its
own primary workspace:

```text
/Users/vidigal/codex/dantedash
```

The migration uses option 1 first: keep the old sidecar intact as rollback while
repointing service startup, MCP registrations, CLI behavior, and Electron
packaging to the new workspace after smoke validation.

## Compatibility Surfaces Kept In v1

- Backend port: `8035`
- Frontend port: `5173`
- LaunchAgent label: `com.vidigal.obsidian-dante-multimodal-rag`
- MCP server name: `dante-multimodal-rag`
- CLI aliases: `dantedash`, `dantedashboard`, `dantevision`, `dante-multi`,
  `dantego`, `multimodal-rag`
- Menu command: `dante menu`

Keeping these interfaces stable avoids breaking existing Codex, Claude, Chrome,
Electron, and launchd workflows while the workspace move settles.

## Old Path Kept As Rollback

The old checkout remains frozen at:

```text
/Users/vidigal/claude-code/Obsidian/sidecars/dante-multimodal-rag
```

It should not receive new dashboard feature work unless rollback is required.

## Runtime Data In v1

For the first migration phase, the Chroma DB and upload directories are copied
locally into the new workspace so the service can boot with the existing KB
state:

```text
/Users/vidigal/codex/dantedash/chroma_db
/Users/vidigal/codex/dantedash/uploads
```

These directories are gitignored and should not be treated as source.

## Option 3 Follow-Up

After a stable period, perform a cleanup migration:

1. Move Chroma, uploads, logs, and generated analysis runtime state fully under
   the Dante data directory.
2. Rename the LaunchAgent label from the legacy Obsidian label to a dashboard
   specific label.
3. Replace the old sidecar checkout with an explicit archive or symlink only
   after all configs and memories have stopped referencing it.
4. Decide whether the git remote should remain the starter-template remote or
   move to a dedicated Dante Dashboard repository.

This cleanup is intentionally deferred because v1 prioritizes continuity and
rollback safety.
