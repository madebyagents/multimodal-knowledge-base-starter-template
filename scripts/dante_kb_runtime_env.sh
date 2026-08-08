#!/usr/bin/env bash

dante_truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

dante_default_chroma_fallback_for_backend() {
  printf 'false'
}

dante_export_kb_runtime_defaults() {
  export DANTEDASH_KB_BACKEND="${DANTEDASH_KB_BACKEND:-knowledge_hub}"
  export DANTEDASH_CHROMA_FALLBACK_ENABLED="${DANTEDASH_CHROMA_FALLBACK_ENABLED:-false}"
}
