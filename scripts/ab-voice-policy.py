#!/usr/bin/env python3
"""Live A/B harness for DanteDash principal voice policy."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.chat_eval import score_answer, score_voice  # noqa: E402
from app.chat_models import CHAT_MODEL_CLAUDE_OPUS, ChatModelId  # noqa: E402
from app.chat_profiles import active_profile_ids, get_chat_profile  # noqa: E402
from app.chat_prompts import registry  # noqa: E402
from app.deps import get_kb  # noqa: E402
from app.providers import ProviderError  # noqa: E402

VOICE_POLICY = "policies/voice.md"


@dataclass(frozen=True)
class VoiceAbCase:
    case_id: str
    question: str
    sources: tuple[str, ...]
    expected_insufficient: bool = False


CASES: tuple[VoiceAbCase, ...] = (
    VoiceAbCase(
        case_id="multi_card_synthesis",
        question=(
            "Synthesize what these cards say about how DanteDash answers chat questions. "
            "Lead with the answer and cite every factual claim."
        ),
        sources=(
            "DanteDash retrieves source cards from the local multimodal knowledge base before answering chat questions.",
            "The chat endpoint sends retrieved sources to the selected principal model and returns a final source panel.",
            "Citation validation checks that bracketed source numbers in the answer refer to retrieved cards.",
        ),
    ),
    VoiceAbCase(
        case_id="partial_evidence_explanation",
        question=(
            "Do these cards prove that DanteDash has cloud sync and live collaborative editing? "
            "If the cards do not support that, use the phrase 'not enough evidence' and cite the cards."
        ),
        sources=(
            "DanteDash stores runtime uploads and the Chroma vector database on the local machine.",
            "The chat UI can stream an answer and then attach retrieved source cards in the source panel.",
        ),
        expected_insufficient=True,
    ),
    VoiceAbCase(
        case_id="conflicting_cards",
        question=(
            "Explain the conflict in these cards and say what a careful answer should do. "
            "Cite both sides of the conflict."
        ),
        sources=(
            "One implementation note says the right context panel should replace the previous output image.",
            "A later product note says the right context panel should keep adding output images instead of replacing them.",
        ),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="")
    parser.add_argument("--cases", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-samples", type=int, default=2)
    args = parser.parse_args()

    model_ids = _selected_model_ids(args.models)
    cases = _selected_cases(args.cases)
    kb = get_kb()

    results: list[dict[str, Any]] = []
    for model_id in model_ids:
        for case in cases:
            for arm in ("A_without_voice", "B_with_voice"):
                started = time.monotonic()
                answer = ""
                error = None
                try:
                    answer = _run_principal(
                        kb=kb,
                        model_id=model_id,
                        case=case,
                        with_voice=(arm == "B_with_voice"),
                    )
                except Exception as exc:  # noqa: BLE001
                    error = _safe_error(exc)
                elapsed_s = round(time.monotonic() - started, 2)
                result = _score_result(
                    model_id=model_id,
                    case=case,
                    arm=arm,
                    answer=answer,
                    error=error,
                    elapsed_s=elapsed_s,
                )
                results.append(result)

    summary = _summarize(results, max_samples=args.max_samples)
    payload = {
        "models": list(model_ids),
        "cases": [case.case_id for case in cases],
        "voice_policy": VOICE_POLICY,
        "summary": summary,
        "results": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0 if all(row["ok"] for row in results) else 1


def _run_principal(*, kb, model_id: ChatModelId, case: VoiceAbCase, with_voice: bool) -> str:
    bundle = _principal_bundle(model_id=model_id, with_voice=with_voice)
    user_prompt = _user_prompt_for_case(model_id=model_id, case=case)
    client = kb.chat_client_for_model(model_id)
    if hasattr(client, "complete_chat"):
        answer = client.complete_chat(
            [
                {"role": "system", "content": bundle.system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
    else:
        answer = "".join(
            client.stream_chat(
                [
                    {"role": "system", "content": bundle.system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
        )
    if not answer.strip():
        raise ProviderError("Provider returned an empty answer.")
    return answer.strip()


def _principal_bundle(*, model_id: ChatModelId, with_voice: bool):
    profile = get_chat_profile(model_id)
    policies = registry.PRINCIPAL_POLICIES
    if not with_voice:
        policies = tuple(policy for policy in policies if policy != VOICE_POLICY)
    return registry._compose_bundle(  # noqa: SLF001
        prompt_id=profile.principal_prompt_id,
        provider_family=profile.provider_family,
        visibility="principal",
        policies=policies,
    )


def _user_prompt_for_case(*, model_id: str, case: VoiceAbCase) -> str:
    source_lines = [f"[{index}] Synthetic voice A/B card {index}" for index in range(1, len(case.sources) + 1)]
    context_lines: list[str] = []
    for index, source in enumerate(case.sources, 1):
        context_lines.extend(
            [
                f"Source [{index}]",
                f"Name: Synthetic voice A/B card {index}",
                "Modality: text",
                f"Snippet: {source}",
                "",
            ]
        )
    mode_line = "Mode: final_answer\n" if model_id == CHAT_MODEL_CLAUDE_OPUS else ""
    return (
        f"{mode_line}"
        f"Question: {case.question}\n\n"
        f"Retrieved sources:\n{chr(10).join(source_lines)}\n\n"
        f"Source context:\n{chr(10).join(context_lines).strip()}\n\n"
        "Answer now."
    )


def _score_result(
    *,
    model_id: str,
    case: VoiceAbCase,
    arm: str,
    answer: str,
    error: str | None,
    elapsed_s: float,
) -> dict[str, Any]:
    if error:
        return {
            "model_id": model_id,
            "case_id": case.case_id,
            "arm": arm,
            "ok": False,
            "error": error,
            "elapsed_s": elapsed_s,
            "answer": answer,
        }
    gate = score_answer(
        answer=answer,
        source_count=len(case.sources),
        source_panel_count=len(case.sources),
        expected_insufficient=case.expected_insufficient,
    )
    voice = score_voice(answer)
    return {
        "model_id": model_id,
        "case_id": case.case_id,
        "arm": arm,
        "ok": gate.passes_gate,
        "error": None,
        "elapsed_s": elapsed_s,
        "gate": gate.to_payload(),
        "voice": voice.to_payload(),
        "answer": answer,
    }


def _summarize(results: list[dict[str, Any]], *, max_samples: int) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for model_id in sorted({str(row["model_id"]) for row in results}):
        model_rows = [row for row in results if row["model_id"] == model_id]
        arms: dict[str, dict[str, Any]] = {}
        for arm in ("A_without_voice", "B_with_voice"):
            rows = [row for row in model_rows if row["arm"] == arm]
            scored = [row for row in rows if row.get("gate")]
            arms[arm] = {
                "ok": all(row.get("ok") for row in rows),
                "errors": [row["error"] for row in rows if row.get("error")],
                "mean_gate_score": _mean(row["gate"]["score"] for row in scored),
                "min_gate_score": min((row["gate"]["score"] for row in scored), default=None),
                "em_dash_count": sum(row["voice"]["em_dash_count"] for row in scored),
                "en_dash_separator_count": sum(row["voice"]["en_dash_separator_count"] for row in scored),
                "ai_tell_count": sum(row["voice"]["ai_tell_count"] for row in scored),
                "bullet_dump_count": sum(row["voice"]["bullet_dump_count"] for row in scored),
                "throat_clearing_count": sum(row["voice"]["throat_clearing_count"] for row in scored),
                "soft_warning_cases": sum(1 for row in scored if row["voice"]["has_soft_warnings"]),
                "voice_clean_cases": sum(1 for row in scored if row["voice"]["voice_clean"]),
                "case_count": len(rows),
                "scored_case_count": len(scored),
                "samples": [
                    {
                        "case_id": row["case_id"],
                        "answer": row["answer"],
                    }
                    for row in scored[:max_samples]
                ],
            }
        delta = None
        if arms["A_without_voice"]["mean_gate_score"] is not None and arms["B_with_voice"]["mean_gate_score"] is not None:
            delta = round(arms["B_with_voice"]["mean_gate_score"] - arms["A_without_voice"]["mean_gate_score"], 4)
        summary[model_id] = {
            "gate_delta_b_minus_a": delta,
            "arms": arms,
        }
    return summary


def _mean(values) -> float | None:
    rows = list(values)
    if not rows:
        return None
    return round(sum(rows) / len(rows), 4)


def _selected_model_ids(raw: str) -> tuple[ChatModelId, ...]:
    if not raw.strip():
        return active_profile_ids()
    requested = tuple(part.strip() for part in raw.split(",") if part.strip())
    active = set(active_profile_ids())
    unknown = [model_id for model_id in requested if model_id not in active]
    if unknown:
        raise SystemExit(f"Unknown active chat model(s): {', '.join(unknown)}")
    return requested  # type: ignore[return-value]


def _selected_cases(raw: str) -> tuple[VoiceAbCase, ...]:
    if not raw.strip():
        return CASES
    requested = {part.strip() for part in raw.split(",") if part.strip()}
    selected = tuple(case for case in CASES if case.case_id in requested)
    missing = requested - {case.case_id for case in selected}
    if missing:
        raise SystemExit(f"Unknown case(s): {', '.join(sorted(missing))}")
    return selected


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if "rate limit" in text.lower():
        return "provider_unavailable: rate limit"
    if "insufficient balance" in text.lower() or "402" in text:
        return "provider_unavailable: billing"
    return f"{type(exc).__name__}: {text[:240]}"


def _print_text(payload: dict[str, Any]) -> None:
    print("DanteDash voice policy A/B")
    for model_id, row in payload["summary"].items():
        print(f"\n{model_id}: gate_delta_b_minus_a={row['gate_delta_b_minus_a']}")
        for arm, arm_row in row["arms"].items():
            print(
                f"  {arm}: ok={arm_row['ok']} mean_gate={arm_row['mean_gate_score']} "
                f"em_dash={arm_row['em_dash_count']} en_dash_sep={arm_row['en_dash_separator_count']} "
                f"ai_tell={arm_row['ai_tell_count']} soft={arm_row['soft_warning_cases']}/{arm_row['scored_case_count']} "
                f"clean={arm_row['voice_clean_cases']}/{arm_row['scored_case_count']}"
            )
            for error in arm_row["errors"]:
                print(f"    error={error}")


if __name__ == "__main__":
    raise SystemExit(main())
