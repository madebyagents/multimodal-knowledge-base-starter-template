# Dante Dashboard Gemini Workspace Instructions

This workspace owns the Dante Multimodal Dashboard app only:

```text
/Users/vidigal/codex/dantedash
```

Start with:

```text
README.md
index.json
snapshots/LATEST.md
docs/architecture/visual-asset-package-contract.md
```

Do not move or mutate the canonical Knowledge Hub, the Obsidian vault, source
high-resolution visual assets, or provider secrets.

<!-- SNAPSHOT-MEMORY-PROTOCOL:START -->
## Snapshot Memory Protocol

- Save deep memories for this workspace under `snapshots/`.
- Use sequential names: `DEEP_MEMORY_DANTEDASH_001.md`, `DEEP_MEMORY_DANTEDASH_002.md`, etc.
- This sequence is shared across agents. Codex, Claude Code, Gemini, and other agents must continue from the highest existing number; do not create agent-specific numbering.
- Use `snapshots/TEMPLATE_DEEP_MEMORY.md` for new snapshots.
- Every deep memory must include complete working context for resumption, verified facts, items already done, items to do grouped by priority, pending decisions, next safe step, and evidence commands.
- Keep `snapshots/index.md` updated with every new deep memory.
- Keep `snapshots/LATEST.md` pointing to the newest deep memory.
- On `continue`, `continua`, `retoma`, or any fatigue/context-loss recovery request, read `snapshots/LATEST.md` first, then read the snapshot it points to.
- After reading the newest deep memory, respond in PT-BR with exactly two humanized summary lines and a short `Next Steps` list organized in groups and priority order.
- Wait for user instruction before mutating files, unless the user explicitly asks to continue execution.
- Create a new pre-change snapshot before global skill installation, large folder reorganization, deletion/quarantine work, auth/provider/default changes, or long-running lab work.
<!-- SNAPSHOT-MEMORY-PROTOCOL:END -->
