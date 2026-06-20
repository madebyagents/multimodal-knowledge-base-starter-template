#!/usr/bin/env python3
"""Offline A/B comparison for active DanteDash chat modes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.chat_eval import QUALITY_GATE, compare_model_scores, score_answer  # noqa: E402
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
    if len(model_ids) != 2:
        raise SystemExit("A/B harness expects exactly two active fixture chat modes.")
    model_a, model_b = model_ids
    comparisons: list[dict[str, object]] = []
    model_scores: dict[str, list[float]] = {model_a: [], model_b: []}

    for case in cases:
        answers = case["answers"]
        scores_by_model = {}
        for model_id in model_ids:
            scores = score_answer(
                answer=answers[model_id],
                source_count=int(case["source_count"]),
                source_panel_count=int(case["source_panel_count"]),
                expected_insufficient=bool(case.get("expected_insufficient", False)),
            )
            scores_by_model[model_id] = scores
            model_scores[model_id].append(scores.total)

        comparison = compare_model_scores(
            model_a=model_a,
            score_a=scores_by_model[model_a].total,
            model_b=model_b,
            score_b=scores_by_model[model_b].total,
        )
        comparisons.append(
            {
                "case_id": case["case_id"],
                **comparison.to_payload(),
                "passes_gate": (
                    scores_by_model[model_a].passes_gate
                    and scores_by_model[model_b].passes_gate
                ),
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
        "model_a": model_a,
        "model_b": model_b,
        "summary": summary,
        "comparisons": comparisons,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"DanteDash non-Anthropic A/B threshold: {args.threshold:.2f}")
        for row in comparisons:
            status = "PASS" if row["passes_gate"] else "FAIL"
            print(
                f"{status} {row['case_id']}: "
                f"{model_a}={row['score_a']:.4f} "
                f"{model_b}={row['score_b']:.4f} "
                f"winner={row['winner']} delta={row['delta']:.4f}"
            )

    return 0 if all(row["passes_gate"] for row in comparisons) else 1


def _fixture_model_ids(cases: list[dict[str, object]]) -> tuple[str, ...]:
    fixture_ids = set(active_profile_ids())
    for case in cases:
        answers = case.get("answers")
        if isinstance(answers, dict):
            fixture_ids &= set(answers)
    return tuple(model_id for model_id in active_profile_ids() if model_id in fixture_ids)


if __name__ == "__main__":
    raise SystemExit(main())
