#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.kb_cutover_score import score_cutover_certification  # noqa: E402
from app.kb_parity import evaluate_result_parity  # noqa: E402
from app.knowledge_hub_client import sanitize_public_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate dry-run search result parity between Chroma and Knowledge Hub.")
    parser.add_argument("--chroma-results", help="JSON file containing Chroma result objects.")
    parser.add_argument("--knowledge-hub-results", help="JSON file containing Knowledge Hub result objects.")
    parser.add_argument("--min-asset-overlap", type=float, default=0.8, help="Minimum Chroma asset recall required.")
    parser.add_argument("--certification-input", help="JSON evidence payload for full cutover certification scoring.")
    parser.add_argument("--output-json", help="Optional path to write the evaluation payload.")
    args = parser.parse_args()

    if args.certification_input:
        try:
            payload = json.loads(Path(args.certification_input).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = _safe_failure("invalid_certification_input")
            _emit_payload(result, args.output_json)
            return 2
        if not isinstance(payload, dict):
            result = _safe_failure("certification_input_must_be_object")
            _emit_payload(result, args.output_json)
            return 2
        if isinstance(payload.get("scoring_payload"), dict):
            payload = payload["scoring_payload"]
        result = score_cutover_certification(payload).to_payload()
        _emit_payload(result, args.output_json)
        return 0 if result["passed"] else 2

    if not args.chroma_results or not args.knowledge_hub_results:
        raise SystemExit("--chroma-results and --knowledge-hub-results are required without --certification-input")

    chroma_results = _read_results(Path(args.chroma_results))
    kh_results = _read_results(Path(args.knowledge_hub_results))
    result = evaluate_result_parity(
        chroma_results,
        kh_results,
        min_asset_overlap=args.min_asset_overlap,
    )

    _emit_payload(result, args.output_json)
    return 0 if result["passed"] else 2


def _emit_payload(result: dict[str, Any], output_json: str | None) -> None:
    public_result = sanitize_public_payload(result)
    payload = json.dumps(public_result, indent=2, sort_keys=True)
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        output_path.chmod(0o600)
    print(payload)


def _safe_failure(reason: str) -> dict[str, Any]:
    return {
        "score": 0.0,
        "raw_weighted_score": 0.0,
        "gate": 0.89,
        "passed": False,
        "decision": "no_go_continue_repairs",
        "dimensions": [],
        "hard_cap": 0.88,
        "hard_cap_reasons": [reason],
        "blockers": [reason],
        "next_actions": ["Fix the certification input shape and rerun scoring."],
    }


def _read_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError(f"Unsupported result JSON shape in {path}")


if __name__ == "__main__":
    raise SystemExit(main())
