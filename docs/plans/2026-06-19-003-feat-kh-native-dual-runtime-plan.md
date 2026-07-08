---
title: "feat: KH-native dual runtime"
type: feat
status: active
date: 2026-06-19
---

# feat: KH-native Dual Runtime

## Summary

Move DanteDash operation to Knowledge Hub-native reads for text search, chat
retrieval source cards, library stats/items, and preview resolution while
keeping Chroma intact as the fallback for image-query search and any temporary
KH outage. This is an operational cutover step only; it does not remove Chroma
or decide the future image-query implementation.

---

## Problem Frame

The parity and import work already proved Knowledge Hub/Qdrant can represent
the DanteDash visual packages, but the app still defaults to Chroma when no
backend mode is configured. Andre has now approved running the read path in
KH-native mode, with Chroma preserved until image-query search has its own
decision.

---

## Requirements

- R1. Make KH-native the explicit operating mode for text search, chat source
  retrieval, stats, item lookup, and preview resolution.
- R2. Keep Chroma data, code paths, and runtime directory untouched.
- R3. Preserve Chroma fallback for `/api/search/image` because Knowledge Hub
  does not yet serve image-query search.
- R4. Preserve Chroma fallback for temporary KH read failures when fallback is
  enabled, but make the fallback visible to backend logs/tests.
- R5. Keep write-scope routes safe in KH-primary operation: no upload, clear,
  delete, ingest, or Chroma mutation should be silently routed through KH.
- R6. Update smoke/docs so the active backend mode is observable and reversible.
- R7. Verify no local absolute paths, credentials, DSNs, or backend traces leak
  through KH-native result DTOs.

---

## Scope Boundaries

- Do not delete, clear, migrate away from, or disable `chroma_db/`.
- Do not implement KH image-query search in this pass.
- Do not mutate Knowledge Hub Postgres, Qdrant, Redis, or manifests.
- Do not change model/provider routing, chat prompts, OAuth clients, or
  retrieval answer style.
- Do not change visual package identity fields such as `source_sha256`,
  `dante_image_id`, `linked_image_file_id`, or `preview_image_file_id`.

### Deferred to Follow-Up Work

- Decide the future image-query search path: KH image vector endpoint,
  Chroma fallback, or separate visual-search service.
- Remove Chroma fallback after image-query parity and rollback window.
- Add operator UI for toggling backend modes if Andre wants runtime controls.

---

## Context & Research

### Relevant Code and Patterns

- `backend/app/kb_gateway.py` already supports Chroma, Chroma-primary dual
  shadow reads, and KH-primary reads with Chroma fallback.
- `backend/app/kb_backends.py` contains `KnowledgeHubKbBackend`, whose text,
  list, item, stats, and preview methods use KH package routes while
  `search_image` intentionally raises `knowledge_hub_image_search_not_available`.
- `backend/app/deps.py` currently defaults `DANTEDASH_KB_BACKEND` to `chroma`
  when the env var is absent.
- `backend/app/routes/search.py`, `backend/app/routes/chat.py`,
  `backend/app/routes/library.py`, and `backend/app/routes/preview.py` already
  consume `KbGateway`, so a gateway-mode switch affects the right surfaces.
- `scripts/smoke-dante-dashboard.sh` verifies counts and Chroma directory
  health, but does not yet verify the active backend mode.

### Institutional Learnings

- The visual corpus must remain layered and linked by `source_sha256` /
  `dante_image_id`, with image preview linkage preserved. The runtime mode
  switch must not collapse package layers into one text document.

### External References

- None. This cutover is grounded in local code, previous certification reports,
  and live local endpoints.

---

## Key Technical Decisions

- Use `knowledge_hub` mode as the KH-native dual operating mode. The current
  gateway semantics already mean KH is primary and Chroma is fallback when
  `DANTEDASH_CHROMA_FALLBACK_ENABLED=true`.
- Keep `dual` unchanged as Chroma-primary shadow mode. Renaming it now would
  blur prior certification semantics and could confuse rollback.
- Make the startup script export KH-native defaults only when the caller has
  not provided an override. This keeps local rollback to Chroma as a one-line
  env override.
- Add an API-observable backend status surface rather than relying on process
  environment inspection.

---

## Open Questions

### Resolved During Planning

- Should Chroma be removed now? No. It remains intact and active as fallback.
- Should image-query search move to KH now? No. This pass preserves Chroma for
  image-query search until that path is designed.

### Deferred to Implementation

- Whether smoke can exercise live `/api/search/image` depends on an available
  local sample image and app process state; focused unit coverage is required
  regardless.

---

## Implementation Units

### U1. Make Backend Mode Observable

**Goal:** Expose the selected backend mode and fallback posture in a safe API
payload and reusable gateway helpers.

**Requirements:** R1, R4, R6, R7

**Dependencies:** None

**Files:**
- Modify: `backend/app/kb_gateway.py`
- Modify: `backend/app/routes/library.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_kb_gateway.py`

**Approach:**
- Add gateway helpers for `is_knowledge_hub_primary`, `is_chroma_fallback_enabled`,
  and a safe status payload.
- Expose status through a read-only route adjacent to existing stats.
- Keep the payload free of URLs, file paths, DSNs, tokens, or local roots.

**Patterns to follow:**
- `StatsResponse` and route-level `KbBackendUnavailable` handling in
  `backend/app/routes/library.py`.
- Existing safety stripping through `sanitize_public_payload`.

**Test scenarios:**
- Happy path: `knowledge_hub` mode reports KH as primary and fallback enabled.
- Happy path: `chroma` mode reports Chroma as primary and fallback status
  false or irrelevant.
- Edge case: status payload never includes local path or KH base URL.

**Verification:**
- `/api/kb/status` returns safe mode diagnostics without changing `/api/stats`.

### U2. Promote Startup Defaults To KH-Native With Fallback

**Goal:** Make local DanteDash startup run in KH-native reads by default while
preserving one-command Chroma rollback.

**Requirements:** R1, R2, R3, R4, R6

**Dependencies:** U1

**Files:**
- Modify: `scripts/start-dante-multimodal-rag.sh`
- Modify: `backend/app/deps.py`
- Modify: `scripts/smoke-dante-dashboard.sh`
- Test: `backend/tests/test_kb_gateway.py`

**Approach:**
- Export `DANTEDASH_KB_BACKEND=knowledge_hub` and
  `DANTEDASH_CHROMA_FALLBACK_ENABLED=true` from the startup script only when
  not already set by the caller.
- Keep `backend/app/deps.py` default conservative for test and direct API
  starts, or make any default change explicit in tests and docs if needed.
- Extend smoke to assert the active mode when the endpoint is available.

**Patterns to follow:**
- Existing smoke strict/warn style in `scripts/smoke-dante-dashboard.sh`.
- Existing env-default style in `scripts/start-dante-multimodal-rag.sh`.

**Test scenarios:**
- Happy path: default startup environment selects KH-primary with Chroma fallback.
- Edge case: caller-provided `DANTEDASH_KB_BACKEND=chroma` is not overwritten.
- Integration: smoke fails clearly if the app is expected to be KH-primary but
  status reports Chroma.

**Verification:**
- Runtime status and smoke both show `knowledge_hub` with fallback enabled.

### U3. Preserve Image-Query Fallback Explicitly

**Goal:** Make the image-query fallback intentional and tested instead of an
accidental generic fallback.

**Requirements:** R2, R3, R4

**Dependencies:** U1

**Files:**
- Modify: `backend/app/kb_gateway.py`
- Test: `backend/tests/test_kb_gateway.py`

**Approach:**
- Keep `KnowledgeHubKbBackend.search_image` unavailable until KH implements
  image-query search.
- Ensure `knowledge_hub` mode with fallback enabled serves `search_image` from
  Chroma and records the method-level fallback through logs/status metadata.
- Keep fallback disabled behavior fail-closed for certification and future
  cutover tests.

**Patterns to follow:**
- Existing `_read` fallback behavior in `KbGateway`.

**Test scenarios:**
- Happy path: `knowledge_hub` mode uses KH for text search but Chroma for image
  search when KH image search is unavailable.
- Error path: disabling fallback makes image search raise
  `KbBackendUnavailable`.
- Edge case: text search does not call Chroma when KH succeeds.

**Verification:**
- Focused tests prove text/chat retrieval can be KH-native while image-query
  remains Chroma-backed.

### U4. Document The Runtime Boundary

**Goal:** Update operations docs and reports so the current operating state is
clear: KH-native reads, Chroma fallback retained, image-query unresolved.

**Requirements:** R2, R3, R6

**Dependencies:** U1, U2, U3

**Files:**
- Modify: `README.md`
- Modify: `docs/runbooks/dante-dashboard-operations.md`
- Modify: `docs/reports/knowledge-hub-cutover-certification.md`

**Approach:**
- Record the rollback env override and the reason Chroma remains on disk.
- State that text search, chat source cards, stats, library, and preview are
  intended to run KH-native after this GO.
- State that image-query search remains Chroma fallback until a separate plan.

**Patterns to follow:**
- Existing operations runbook sections for smoke, runtime data, and KH cockpit.

**Test scenarios:**
- Test expectation: none -- documentation-only change.

**Verification:**
- Docs match the implemented env defaults and `/api/kb/status` payload.

---

## System-Wide Impact

- **Interaction graph:** Existing Search, Chat, Library, Preview, MCP, and Hub
  surfaces continue through the gateway; no route should call KH stores
  directly.
- **Error propagation:** KH outages remain provider-neutral 503s unless Chroma
  fallback is enabled and can serve the request.
- **State lifecycle risks:** Chroma remains present and mutable only through
  pre-existing Chroma-mode write routes. KH-primary operation should keep write
  routes blocked.
- **API surface parity:** `/api/search`, `/api/search/image`, `/api/chat`,
  `/api/items`, `/api/items/lookup`, `/api/stats`, and `/api/preview/{file_id}`
  remain stable.
- **Unchanged invariants:** Layered visual packages, preview URLs, source card
  DTOs, and top-k behavior are unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| KH process is down while app starts | Chroma fallback remains enabled and smoke reports KH health separately. |
| The active app is launched outside `scripts/start-dante-multimodal-rag.sh` | Add `/api/kb/status` and docs so mode can be inspected and corrected. |
| Image-query fallback hides future KH image-search gaps | Keep this gap explicit in status/docs and add focused tests for the fallback. |
| Dirty worktree contains unrelated UI/runtime changes | Stage only files touched by this plan and do not revert unrelated changes. |

---

## Documentation / Operational Notes

- Rollback to Chroma remains: set `DANTEDASH_KB_BACKEND=chroma` before launch.
- Certification remains valid only for the live imported KH package state; if
  KH manifests are rebuilt, rerun parity certification before disabling Chroma.
- Chroma removal requires a separate GO after the image-query search decision.

---

## Sources & References

- Related plan: `docs/plans/2026-06-19-001-feat-knowledge-hub-parity-chroma-sunset-plan.md`
- Related plan: `docs/plans/2026-06-19-002-feat-knowledge-hub-cutover-certification-plan.md`
- Related report: `docs/reports/knowledge-hub-cutover-certification.md`
- Related code: `backend/app/kb_gateway.py`
- Related code: `backend/app/kb_backends.py`
- Related code: `scripts/smoke-dante-dashboard.sh`
