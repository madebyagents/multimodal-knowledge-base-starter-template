#!/usr/bin/env python3
"""Offline DanteDash chat eval gate for active DanteDash chat modes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.chat_eval import QUALITY_GATE, score_answer  # noqa: E402
from app.chat_profiles import active_profile_ids  # noqa: E402

DEFAULT_FIXTURES = BACKEND_ROOT / "testdata" / "chat_eval" / "non_anthropic_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--threshold", type=float, default=QUALITY_GATE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = json.loads(args.fixtures.read_text(encoding="utf-8"))
    model_ids = _fixture_model_ids(cases)
    model_scores: dict[str, list[float]] = {model_id: [] for model_id in model_ids}
    results: list[dict[str, object]] = []

    for case in cases:
        answers = case["answers"]
        for model_id in model_ids:
            scores = score_answer(
                answer=answers[model_id],
                source_count=int(case["source_count"]),
                source_panel_count=int(case["source_panel_count"]),
                expected_insufficient=bool(case.get("expected_insufficient", False)),
            )
            model_scores[model_id].append(scores.total)
            results.append(
                {
                    "case_id": case["case_id"],
                    "model_id": model_id,
                    **scores.to_payload(),
                }
            )

    summary = {
        model_id: {
            "mean_score": round(sum(scores) / len(scores), 4),
            "min_score": min(scores),
            "passes_gate": min(scores) >= args.threshold,
        }
        for model_id, scores in model_scores.items()
    }
    payload = {
        "threshold": args.threshold,
        "summary": summary,
        "results": results,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"DanteDash non-Anthropic chat eval threshold: {args.threshold:.2f}")
        for model_id, row in summary.items():
            status = "PASS" if row["passes_gate"] else "FAIL"
            print(f"{status} {model_id}: min={row['min_score']:.4f} mean={row['mean_score']:.4f}")

    return 0 if all(row["passes_gate"] for row in summary.values()) else 1


def _fixture_model_ids(cases: list[dict[str, object]]) -> tuple[str, ...]:
    fixture_ids = set(active_profile_ids())
    for case in cases:
        answers = case.get("answers")
        if isinstance(answers, dict):
            fixture_ids &= set(answers)
    model_ids = tuple(model_id for model_id in active_profile_ids() if model_id in fixture_ids)
    if not model_ids:
        raise SystemExit("No active chat models are present in the eval fixture answers.")
    return model_ids


if __name__ == "__main__":
    raise SystemExit(main())
