from __future__ import annotations

import json

from app.chat_models import CHAT_MODEL_CLAUDE_OPUS
from app.kb import SearchResult
from app.rag import GroundedAnswer, _normalize_judge_payload, _parse_json_object, answer_with_vision


class ScriptedClient:
    def __init__(self, responses: list[str] | None = None, *, fail: bool = False) -> None:
        self.responses = list(responses or [])
        self.fail = fail
        self.messages: list[list[dict[str, str]]] = []

    def complete_chat(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if self.fail:
            raise RuntimeError("hidden helper failure")
        if not self.responses:
            raise RuntimeError("no scripted response")
        return self.responses.pop(0)


class FakePremiumKb:
    def __init__(self, *, helper_fails: bool = False) -> None:
        self.claude_premium_repair_cap = 1
        self.claude_opus_chat_client = ScriptedClient(
            [
                json.dumps(
                    {
                        "mode": "dispatch_planning",
                        "decision": "dispatch",
                        "reason": "multi-source synthesis",
                        "plan": [
                            {"cluster": "facts", "helper": "worker", "extract": "extract product facts"},
                            {"cluster": "synthesis", "helper": "chief", "extract": "reconcile facts"},
                        ],
                    }
                ),
                "The dashboard uses retrieved cards to ground chat answers [1].",
            ]
        )
        worker_payload = json.dumps(
            {
                "status": "ok",
                "assigned_subtask": "extract product facts",
                "salient_claims": [
                    {
                        "claim": "The dashboard uses retrieved cards.",
                        "source_ids": ["1"],
                        "supporting_quotes": [{"source_id": "1", "quote": "retrieved cards"}],
                        "confidence": 0.94,
                    }
                ],
                "relevance": "high",
                "gaps": [],
                "media_handles": [],
                "query_used": "dashboard",
                "reason": "",
            }
        )
        self.claude_haiku_worker_client = ScriptedClient([worker_payload], fail=helper_fails)
        self.claude_sonnet_chief_client = ScriptedClient([worker_payload], fail=helper_fails)
        self.claude_opus_judge_client = ScriptedClient(
            [
                json.dumps(
                    {
                        "score": 0.95,
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
            ]
        )

    def search_text(self, *args, **kwargs):
        return [
            SearchResult(
                node_id="node-1",
                score=0.91,
                modality="text",
                metadata={"id": "file-1", "original_name": "note.md", "modality": "text"},
                snippet="The dashboard uses retrieved cards to ground chat answers.",
            )
        ]


def test_claude_premium_runs_helpers_and_clean_judge_context() -> None:
    kb = FakePremiumKb()
    chunks = list(answer_with_vision(kb, "How does chat stay grounded?", chat_model=CHAT_MODEL_CLAUDE_OPUS))
    final = chunks[-1]

    assert isinstance(final, GroundedAnswer)
    assert final.citation_validation is not None
    assert final.citation_validation.ok
    assert chunks[0] == "The dashboard uses retrieved cards to ground chat answers [1]."

    opus_prompts = [messages[1]["content"] for messages in kb.claude_opus_chat_client.messages]
    assert "Mode: dispatch_planning" in opus_prompts[0]
    assert "Mode: final_answer" in opus_prompts[1]
    assert "Internal same-provider findings" in opus_prompts[1]

    judge_prompt = kb.claude_opus_judge_client.messages[0][1]["content"]
    assert "Candidate answer:" in judge_prompt
    assert "Internal same-provider findings" not in judge_prompt
    assert "dispatch_planning" not in judge_prompt
    assert "assigned_subtask" not in judge_prompt


def test_claude_premium_helper_failure_degrades_to_principal_only() -> None:
    kb = FakePremiumKb(helper_fails=True)
    chunks = list(answer_with_vision(kb, "How does chat stay grounded?", chat_model=CHAT_MODEL_CLAUDE_OPUS))
    final = chunks[-1]

    assert isinstance(final, GroundedAnswer)
    opus_final_prompt = kb.claude_opus_chat_client.messages[1][1]["content"]
    assert "Mode: final_answer" in opus_final_prompt
    assert "Internal same-provider findings" not in opus_final_prompt


def test_json_object_parser_accepts_wrapped_provider_text() -> None:
    payload = _parse_json_object('Here is the JSON:\n{"verdict":"pass","score":1}\nDone.')
    assert payload == {"verdict": "pass", "score": 1}


def test_judge_payload_normalizer_accepts_minor_provider_variations() -> None:
    payload = _normalize_judge_payload(
        {
            "score": "0.8",
            "verdict": "PASS",
            "dimension_notes": "grounded",
            "revision_notes": "tighten citations",
        },
        iteration=2,
    )
    assert payload["verdict"] == "pass"
    assert payload["dimension_notes"] == {"grounding": "grounded"}
    assert payload["revision_notes"] == ["tighten citations"]
    assert payload["iteration"] == 2
    assert payload["unknown"] is False
