# DEEP MEMORY DANTEDASH XXX

Snapshot date: YYYY-MM-DD HH:MM:SS TZ
Workspace: `/Users/vidigal/codex/dantedash`
Status: [why this snapshot exists]

## Resume Output Contract

When the user returns, give this compact PT-BR output first and then wait:

```text
[Line 1: humanized summary of what was done.]
[Line 2: humanized summary of current state or where work paused.]

Next Steps:
P0 - [Highest priority group]
- [Most likely next action.]
- [Decision needed before mutation.]

P1 - [Next priority group]
- [Second likely next action.]
```

Do not mutate files during recovery until the user gives a new instruction, unless the user explicitly says to continue execution.

## Verified On Filesystem

| Path / Surface | Verified State |
|---|---|
| `README.md` | |
| `index.md` | |
| `AGENTS.md` | |
| `snapshots/` | |

## User Intent / Not Yet Verified

-

## Current State


## Items Already Done

### P0

-

### P1

-

### P2

-

## Items To Do

### P0

-

### P1

-

### P2

-

## Installed Skills And Commands

### Workspace-local

-

### Codex

-

### Claude Code

-

### OpenClaw

-

## Pending Decisions

-

## Next Safe Step

-

## Do Not Do Automatically

- Do not persist API keys, tokens, shell profile exports, or provider credentials.
- Do not mutate unrelated workspaces or global agent runtimes unless explicitly requested.
- Do not claim current pricing, model availability, or provider behavior without fresh verification.

## Evidence Commands

```bash
cd /Users/vidigal/codex/dantedash
find snapshots -maxdepth 1 -type f | sort
sed -n '1,160p' snapshots/LATEST.md
sed -n '1,160p' AGENTS.md
```
