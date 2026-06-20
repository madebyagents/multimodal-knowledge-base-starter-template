from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.chat_workers import validate_judge_result, validate_worker_result


def test_worker_result_accepts_schema_payload() -> None:
    result = validate_worker_result(
        {
            "status": "ok",
            "assigned_subtask": "extract product facts",
            "salient_claims": [
                {
                    "claim": "The dashboard uses retrieved source cards.",
                    "source_ids": ["1"],
                    "supporting_quotes": [{"source_id": "1", "quote": "retrieved source cards"}],
                    "confidence": 0.92,
                }
            ],
            "relevance": "high",
            "gaps": [],
            "media_handles": [],
            "query_used": "dashboard",
            "reason": "",
        }
    )
    assert result.status == "ok"
    assert result.salient_claims[0].source_ids == ["1"]


def test_worker_result_rejects_final_prose_payload() -> None:
    with pytest.raises(ValidationError):
        validate_worker_result("Here is the final answer for the user.")


def test_judge_result_accepts_schema_payload() -> None:
    result = validate_judge_result(
        {
            "score": 0.91,
            "verdict": "pass",
            "dimension_notes": {
                "grounding": "grounded",
                "citation_accuracy": "valid",
                "faithfulness": "faithful",
                "completeness": "complete",
                "refusal_calibration": "not needed",
            },
            "revision_notes": [],
            "unknown": False,
            "iteration": 0,
        }
    )
    assert result.verdict == "pass"
    assert result.score == 0.91


def test_judge_result_rejects_worker_payload() -> None:
    with pytest.raises(ValidationError):
        validate_judge_result({"status": "ok", "assigned_subtask": "x"})
