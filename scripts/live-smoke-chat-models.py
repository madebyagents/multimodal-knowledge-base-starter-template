#!/usr/bin/env python3
"""Live /api/chat smoke for active DanteDash chat modes."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.chat_profiles import active_profile_ids  # noqa: E402


@dataclass(frozen=True)
class LiveSmokeResult:
    model_id: str
    ok: bool
    status: str
    elapsed_s: float
    answer_chars: int
    sources: int
    citation_validation: dict[str, Any] | None
    error: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "ok": self.ok,
            "status": self.status,
            "elapsed_s": self.elapsed_s,
            "answer_chars": self.answer_chars,
            "sources": self.sources,
            "citation_validation": self.citation_validation,
            "error": self.error,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8035")
    parser.add_argument("--question", default="In one concise sentence, what does this retrieved source show about DanteDash?")
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--models", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-provider-unavailable", action="store_true")
    args = parser.parse_args()

    model_ids = _selected_model_ids(args.models)
    results = [
        smoke_model(
            api_base=args.api_base.rstrip("/"),
            model_id=model_id,
            question=args.question,
            top_k=args.top_k,
            timeout=args.timeout,
        )
        for model_id in model_ids
    ]
    payload = {
        "api_base": args.api_base.rstrip("/"),
        "results": [result.to_payload() for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"DanteDash live chat smoke: {payload['api_base']}")
        for result in results:
            prefix = "PASS" if result.ok else "FAIL"
            print(
                f"{prefix} {result.model_id}: status={result.status} "
                f"sources={result.sources} answer_chars={result.answer_chars} "
                f"elapsed={result.elapsed_s:.2f}s"
            )
            if result.error:
                print(f"  error={result.error}")

    acceptable = all(
        result.ok or (args.allow_provider_unavailable and result.status == "provider_unavailable")
        for result in results
    )
    return 0 if acceptable else 1


def smoke_model(
    *,
    api_base: str,
    model_id: str,
    question: str,
    top_k: int,
    timeout: float,
) -> LiveSmokeResult:
    started = time.monotonic()
    answer_parts: list[str] = []
    sources_payload: dict[str, Any] | None = None
    error_payload: str | None = None
    event = "message"
    try:
        with httpx.stream(
            "POST",
            f"{api_base}/api/chat",
            json={
                "question": question,
                "top_k": top_k,
                "modality_filter": None,
                "max_images": 1,
                "chat_model": model_id,
            },
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                line = raw_line.strip()
                if not line:
                    event = "message"
                    continue
                if line.startswith("event: "):
                    event = line.removeprefix("event: ")
                    continue
                if not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ")
                if event == "message":
                    token = json.loads(data)
                    if isinstance(token, str):
                        answer_parts.append(token)
                elif event == "sources":
                    parsed = json.loads(data)
                    if isinstance(parsed, dict):
                        sources_payload = parsed
                elif event == "error":
                    error_payload = _extract_error(data)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        error_payload = str(exc)

    elapsed_s = round(time.monotonic() - started, 2)
    citation_validation = (sources_payload or {}).get("citation_validation")
    answer = "".join(answer_parts)
    status = _status_for_result(error_payload, answer, citation_validation)
    return LiveSmokeResult(
        model_id=model_id,
        ok=status == "ok",
        status=status,
        elapsed_s=elapsed_s,
        answer_chars=len(answer),
        sources=len((sources_payload or {}).get("sources") or []),
        citation_validation=citation_validation,
        error=error_payload,
    )


def _extract_error(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict):
        message = parsed.get("message")
        if isinstance(message, str):
            return message
    return raw


def _status_for_result(
    error: str | None,
    answer: str,
    citation_validation: dict[str, Any] | None,
) -> str:
    if error:
        lowered = error.lower()
        if "insufficient balance" in lowered or "402" in lowered or "rate limit" in lowered:
            return "provider_unavailable"
        if "currently unavailable" in lowered:
            return "provider_unavailable"
        return "provider_error"
    if not answer:
        return "empty_answer"
    if not citation_validation:
        return "missing_citation_validation"
    if citation_validation.get("ok") is not True:
        return "invalid_citations"
    return "ok"


def _selected_model_ids(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return active_profile_ids()
    requested = tuple(part.strip() for part in raw.split(",") if part.strip())
    active = set(active_profile_ids())
    unknown = [model_id for model_id in requested if model_id not in active]
    if unknown:
        raise SystemExit(f"Unknown active chat model(s): {', '.join(unknown)}")
    return requested


if __name__ == "__main__":
    raise SystemExit(main())
