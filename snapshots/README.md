# dantedash Snapshots

This folder stores durable deep-memory snapshots for:

```text
/Users/vidigal/codex/dantedash
```

## Resume Protocol

On `continue`, `continua`, `retoma`, or recovery after context loss/fatigue:

1. Read `LATEST.md`.
2. Read the snapshot it points to.
3. Respond in PT-BR with exactly two humanized summary lines.
4. Add a short `Next Steps` list organized in groups and priority order.
5. Wait for user instruction before mutating files unless execution was explicitly requested.

## Naming

```text
DEEP_MEMORY_DANTEDASH_001.md
DEEP_MEMORY_DANTEDASH_002.md
DEEP_MEMORY_DANTEDASH_003.md
```

Use `TEMPLATE_DEEP_MEMORY.md` for new snapshots.
Update `LATEST.md` and `index.md` whenever a new snapshot is created.
Each new deep memory must include complete working context, verified facts, items already done, and items to do grouped by priority.
