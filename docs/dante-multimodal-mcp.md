# Dante Multimodal RAG MCP

This workspace exposes a dedicated MCP server named `dante-multimodal-rag`.
It adapts the local Dante multimodal API and does not replace or merge with the
canonical `knowledge-hub` MCP runtime.

## Tools

| Tool | Purpose |
| --- | --- |
| `stats` | Return live sidecar status and modality counts. |
| `search` | Run text search over the multimodal Chroma collection. |
| `chat` | Ask a grounded RAG question and return the completed answer plus sources. |
| `get_item` | Fetch one grouped item by `file_id` or `node_id`. |
| `preview` | Return an absolute local preview URL, or capped base64 image payload. |

The wrapper is read-only. It intentionally does not expose ingest, delete,
clear, reindex, or provider-key management.

## Runtime

Start the backend first:

```bash
cd /Users/vidigal/codex/dantedash/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8035
```

Run the MCP server over stdio:

```bash
cd /Users/vidigal/codex/dantedash/backend
uv run python -m app.mcp_server
```

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DANTE_MULTIMODAL_API_BASE_URL` | `http://127.0.0.1:8035` | Sidecar API base URL. |
| `DANTE_MULTIMODAL_API_TIMEOUT_S` | `180` | HTTP timeout for sidecar calls. |
| `DANTE_MULTIMODAL_PREVIEW_MAX_BYTES` | `2097152` | Max bytes returned by `preview(mode="base64")`. |
| `DANTE_MULTIMODAL_MCP_TRANSPORT` | `stdio` | MCP transport for direct execution. |

## Registration

Codex:

```bash
codex mcp add dante-multimodal-rag -- /Users/vidigal/.local/bin/uv --directory /Users/vidigal/codex/dantedash/backend run python -m app.mcp_server
```

Claude Code CLI:

```bash
claude mcp add dante-multimodal-rag -- /Users/vidigal/.local/bin/uv --directory /Users/vidigal/codex/dantedash/backend run python -m app.mcp_server
```

If your shell resolves `uv` reliably, `/Users/vidigal/.local/bin/uv` can be
replaced with `uv`.

## Smoke Checklist

After registration, ask the MCP client to call:

1. `stats`
   - Expected: `ok=true`, sidecar base URL, and non-zero modality counts.
2. `search`
   - Input: `{"query":"Aguirre jungle river ritual dread cinematic composition","top_k":3}`
   - Expected: visual-analysis results with absolute preview URLs.
3. `get_item`
   - Input: a `file_id` from search results.
   - Expected: grouped item metadata, node IDs, snippets, no raw `file_path`.
4. `preview`
   - Input: same `file_id`, `mode="url"`.
   - Expected: absolute `http://127.0.0.1:8035/api/preview/...` URL.
5. `chat`
   - Input: a grounded visual reference question.
   - Expected: completed answer, source list, and visual attachment count.

## Notes

- `preview(mode="url")` is the default to avoid large binary payloads.
- `preview(mode="base64")` only supports image-backed items and is capped by
  `DANTE_MULTIMODAL_PREVIEW_MAX_BYTES`.
- `chat` returns a completed response in v1. It does not stream tokens through
  MCP yet.
