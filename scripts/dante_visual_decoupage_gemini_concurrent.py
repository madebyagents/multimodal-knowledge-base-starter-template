#!/usr/bin/env python3
"""Concurrent Gemini runner for Dante art-grade decoupage validation."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.dante_visual.decoupage import (  # noqa: E402
    build_decoupage_instructions,
    decoupage_required_fields,
    load_decoupage_schema,
)
from app.dante_visual.gemini_provider import GEMINI_ENDPOINT, _prepare_image_bytes  # noqa: E402
from app.dante_visual.manifest import VisualAsset, load_visual_manifest, resolve_inside, safe_relative_path, validate_run_id  # noqa: E402
from app.dante_visual.safe_io import safe_append_text, safe_write_text  # noqa: E402
from dante_visual_analysis_harness import DEFAULT_DATASET_ROOT, DEFAULT_VAULT_ROOT, resolve_paths, select_assets  # noqa: E402

DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_THRESHOLD = 0.87


@dataclass(frozen=True)
class Target:
    index: int
    asset: VisualAsset


@dataclass(frozen=True)
class RunConfig:
    run_dir: Path
    asset_root: Path
    api_key: str
    model_name: str
    lens: str
    timeout_s: float
    request_retries: int
    max_output_tokens: int
    max_image_edge: int
    jpeg_quality: int
    schema: dict[str, Any]
    required_fields: tuple[str, ...]
    force: bool


_thread_state = threading.local()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--sample-mode", choices=["first", "stratified"], default="stratified")
    parser.add_argument("--include-image-id", action="append", default=[])
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--retry-passes", type=int, default=2)
    parser.add_argument("--request-retries", type=int, default=2)
    parser.add_argument("--model", default=os.getenv("GEMINI_DECOUPAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=12288)
    parser.add_argument("--max-image-edge", type=int, default=1280)
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--lens", default="solo")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--force", action="store_true", help="Re-run targets even when this run already has valid outputs")
    args = parser.parse_args()

    run_id = validate_run_id(args.run_id or default_run_id())
    paths = resolve_paths(args.vault_root, args.dataset_root, run_id)
    run_dir = paths["analysis_root"] / "decoupage" / "manifests" / run_id
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    if not manifest.is_valid:
        print(f"Manifest invalid with {manifest.error_count} errors; run aborted.", file=sys.stderr)
        return 2

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY is missing; run aborted.", file=sys.stderr)
        return 2

    targets = build_targets(manifest.assets, sample=args.sample, sample_mode=args.sample_mode, include_ids=args.include_image_id)
    if not targets:
        print("No targets selected; run aborted.", file=sys.stderr)
        return 2

    config = RunConfig(
        run_dir=run_dir,
        asset_root=paths["asset_root"],
        api_key=api_key,
        model_name=args.model.removeprefix("models/"),
        lens=args.lens,
        timeout_s=args.timeout,
        request_retries=max(0, args.request_retries),
        max_output_tokens=args.max_output_tokens,
        max_image_edge=args.max_image_edge,
        jpeg_quality=args.jpeg_quality,
        schema=to_gemini_schema(load_decoupage_schema()),
        required_fields=decoupage_required_fields(),
        force=args.force,
    )
    write_run_header(config, targets, threshold=args.threshold, concurrency=max(1, args.concurrency))

    rows: list[dict[str, Any] | None] = [None] * len(targets)
    pending = targets
    failures: list[dict[str, Any]] = []
    for pass_index in range(max(0, args.retry_passes) + 1):
        if not pending:
            break
        print(json.dumps({"pass": pass_index + 1, "pending": len(pending), "concurrency": max(1, args.concurrency)}, sort_keys=True))
        pass_rows, failures = process_pass(pending, config=config, concurrency=max(1, args.concurrency), pass_index=pass_index)
        for target, row in pass_rows:
            rows[target.index] = row
        pending = [failure["target"] for failure in failures if isinstance(failure.get("target"), Target)]
        write_summary(config, rows, targets, failures, threshold=args.threshold, final=False)

    summary = write_summary(config, rows, targets, failures, threshold=args.threshold, final=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["pass"] else 1


def default_run_id() -> str:
    return datetime.now(UTC).strftime("visual-decoupage-gemini31-concurrent-%Y%m%dT%H%M%SZ")


def build_targets(
    assets: list[VisualAsset],
    *,
    sample: int,
    sample_mode: str,
    include_ids: list[str],
) -> list[Target]:
    by_id = {asset.image_id: asset for asset in assets}
    selected: list[VisualAsset] = []
    seen: set[str] = set()
    for image_id in include_ids:
        asset = by_id.get(image_id)
        if asset is None:
            raise ValueError(f"Unknown image_id requested with --include-image-id: {image_id}")
        selected.append(asset)
        seen.add(asset.image_id)
    for asset in select_assets(assets, sample=max(0, sample), sample_mode=sample_mode):
        if asset.image_id in seen:
            continue
        selected.append(asset)
        seen.add(asset.image_id)
        if len(selected) >= sample + len(include_ids):
            break
    return [Target(index=index, asset=asset) for index, asset in enumerate(selected)]


def write_run_header(config: RunConfig, targets: list[Target], *, threshold: float, concurrency: int) -> None:
    request_summary = {
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "provider": "gemini",
        "api_surface": "Gemini Developer API",
        "uses_vertex": False,
        "endpoint": f"{GEMINI_ENDPOINT}/models/{config.model_name}:generateContent",
        "model": config.model_name,
        "lens": config.lens,
        "target_count": len(targets),
        "threshold": threshold,
        "concurrency": concurrency,
        "timeout_s": config.timeout_s,
        "request_retries": config.request_retries,
        "targets": [target.asset.image_id for target in targets],
    }
    safe_write_text(config.run_dir / "request-summary.json", json.dumps(request_summary, indent=2, sort_keys=True) + "\n", root=config.run_dir)
    safe_write_text(config.run_dir / "gemini-response-schema.json", json.dumps(config.schema, indent=2, sort_keys=True) + "\n", root=config.run_dir)


def process_pass(
    targets: list[Target],
    *,
    config: RunConfig,
    concurrency: int,
    pass_index: int,
) -> tuple[list[tuple[Target, dict[str, Any]]], list[dict[str, Any]]]:
    rows: list[tuple[Target, dict[str, Any]]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="gemini-decoupage") as executor:
        future_map = {executor.submit(process_one, target, config, pass_index): target for target in targets}
        for completed, future in enumerate(as_completed(future_map), start=1):
            target = future_map[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "image_id": target.asset.image_id,
                    "status": "exception",
                    "confidence": None,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            row["pass_index"] = pass_index + 1
            row["completed_in_pass"] = completed
            safe_append_text(config.run_dir / "progress.jsonl", json.dumps(row, sort_keys=True) + "\n", root=config.run_dir)
            print(json.dumps({"progress": f"{completed}/{len(targets)}", **compact_progress(row)}, sort_keys=True), flush=True)
            if row.get("status") == "ok":
                rows.append((target, row))
            else:
                failures.append({"target": target, "error": row.get("error", "unknown_error"), "row": row})
    return rows, failures


def compact_progress(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_id": row.get("image_id"),
        "status": row.get("status"),
        "confidence": row.get("confidence"),
        "elapsed_s": row.get("elapsed_s"),
        "error": row.get("error"),
    }


def process_one(target: Target, config: RunConfig, pass_index: int) -> dict[str, Any]:
    started = time.monotonic()
    asset = target.asset
    if not config.force:
        existing = existing_output_row(config, asset)
        if existing is not None:
            return existing

    url = f"{GEMINI_ENDPOINT}/models/{config.model_name}:generateContent"
    image_path = resolve_inside(config.asset_root, safe_relative_path(asset.new_relative_path, field_name="new_relative_path"))
    image_bytes = _prepare_image_bytes(
        image_path,
        max_image_edge=config.max_image_edge,
        jpeg_quality=config.jpeg_quality,
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_for_asset(asset, config.lens)},
                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode("ascii")}},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.18,
            "topP": 0.85,
            "maxOutputTokens": config.max_output_tokens,
            "responseMimeType": "application/json",
            "responseSchema": config.schema,
        },
    }

    last_error: Exception | None = None
    raw_payload: dict[str, Any] | None = None
    for attempt in range(config.request_retries + 1):
        try:
            response = client_for_thread(config).post(url, params={"key": config.api_key}, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:500]}")
            raw_payload = response.json()
            parsed = parse_json_text(extract_text(raw_payload))
            if not isinstance(parsed, dict):
                raise ValueError("Gemini response JSON must be an object")
            validate_decoupage(parsed, asset=asset, config=config)
            write_outputs(config, asset, parsed, raw_payload=raw_payload, pass_index=pass_index)
            return {
                "image_id": asset.image_id,
                "status": "ok",
                "confidence": float(parsed["provenance"]["confidence_overall"]),
                "elapsed_s": round(time.monotonic() - started, 2),
                "sidecar_json": str((config.run_dir / "sidecars" / f"{asset.image_id}.json")),
                "sidecar_markdown": str((config.run_dir / "markdown" / f"{asset.image_id}.md")),
                "error": "",
            }
        except Exception as exc:
            last_error = exc
            if attempt >= config.request_retries:
                break
            time.sleep(min(2**attempt, 10))
    return {
        "image_id": asset.image_id,
        "status": "exception",
        "confidence": None,
        "elapsed_s": round(time.monotonic() - started, 2),
        "error": f"{type(last_error).__name__}: {str(last_error)[:500]}",
    }


def existing_output_row(config: RunConfig, asset: VisualAsset) -> dict[str, Any] | None:
    sidecar_path = config.run_dir / "sidecars" / f"{asset.image_id}.json"
    markdown_path = config.run_dir / "markdown" / f"{asset.image_id}.md"
    if not sidecar_path.exists() or not markdown_path.exists():
        return None
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        validate_decoupage(payload, asset=asset, config=config)
        binding = payload.get("_dante_binding") if isinstance(payload, dict) else None
        if not isinstance(binding, dict) or binding.get("source_sha256") != asset.sha256:
            return None
        confidence = float(payload["provenance"]["confidence_overall"])
    except Exception:
        return None
    return {
        "image_id": asset.image_id,
        "status": "ok",
        "confidence": confidence,
        "elapsed_s": 0.0,
        "sidecar_json": str(sidecar_path),
        "sidecar_markdown": str(markdown_path),
        "skipped_existing": True,
        "error": "",
    }


def client_for_thread(config: RunConfig) -> httpx.Client:
    client = getattr(_thread_state, "client", None)
    if client is None:
        client = httpx.Client(timeout=config.timeout_s)
        _thread_state.client = client
    return client


def prompt_for_asset(asset: VisualAsset, lens: str) -> str:
    return (
        f"{build_decoupage_instructions(asset_id=asset.image_id, lens=lens)}\n\n"
        "Gemini Developer API validation mode:\n"
        "- You are one of multiple concurrent workers; analyze only this one image.\n"
        "- Never reuse a prior answer template; vary the interpretive language based on visible evidence.\n"
        "- Calibrate provenance.confidence_overall honestly. Do not inflate confidence to pass a benchmark.\n"
        "- Lens, focal length, stock, and Kelvin values are inferences unless directly evidenced.\n\n"
        "Asset metadata:\n"
        f"- image_id: {asset.image_id}\n"
        f"- category: {asset.category}\n"
        f"- group: {asset.group}\n"
        f"- dimensions: {asset.width}x{asset.height}\n"
        f"- source_sha256: {asset.sha256}\n"
    )


def validate_decoupage(payload: dict[str, Any], *, asset: VisualAsset, config: RunConfig) -> None:
    missing = [field for field in config.required_fields if field not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    if payload.get("asset_id") != asset.image_id:
        raise ValueError(f"asset_id mismatch: {payload.get('asset_id')!r} != {asset.image_id!r}")
    if payload.get("lens") != config.lens:
        raise ValueError(f"lens mismatch: {payload.get('lens')!r} != {config.lens!r}")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Missing provenance object")
    confidence = provenance.get("confidence_overall")
    try:
        confidence_number = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("provenance.confidence_overall must be numeric") from exc
    if not 0 <= confidence_number <= 1:
        raise ValueError("provenance.confidence_overall must be between 0 and 1")
    if not str(payload.get("markdown_handoff", "")).strip():
        raise ValueError("markdown_handoff must be non-empty")


def write_outputs(
    config: RunConfig,
    asset: VisualAsset,
    payload: dict[str, Any],
    *,
    raw_payload: dict[str, Any],
    pass_index: int,
) -> None:
    payload = {
        **payload,
        "_dante_binding": {
            "image_id": asset.image_id,
            "source_sha256": asset.sha256,
            "new_relative_path": asset.new_relative_path,
            "provider": "gemini",
            "model": config.model_name,
            "api_surface": "Gemini Developer API",
            "uses_vertex": False,
            "pass_index": pass_index + 1,
        },
    }
    raw_name = f"{asset.image_id}-pass-{pass_index + 1}-raw-response.json"
    safe_write_text(config.run_dir / "raw-responses" / raw_name, json.dumps(raw_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", root=config.run_dir)
    safe_write_text(config.run_dir / "sidecars" / f"{asset.image_id}.json", json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", root=config.run_dir)
    safe_write_text(config.run_dir / "markdown" / f"{asset.image_id}.md", str(payload["markdown_handoff"]).rstrip() + "\n", root=config.run_dir)


def write_summary(
    config: RunConfig,
    rows: list[dict[str, Any] | None],
    targets: list[Target],
    failures: list[dict[str, Any]],
    *,
    threshold: float,
    final: bool,
) -> dict[str, Any]:
    ok_rows = [row for row in rows if row and row.get("status") == "ok"]
    confidences = [float(row["confidence"]) for row in ok_rows if row.get("confidence") is not None]
    average = round(sum(confidences) / len(confidences), 4) if confidences else None
    pass_flag = len(ok_rows) == len(targets) and average is not None and average >= threshold
    summary = {
        "final": final,
        "provider": "gemini",
        "api_surface": "Gemini Developer API",
        "uses_vertex": False,
        "model": config.model_name,
        "target_count": len(targets),
        "ok_count": len(ok_rows),
        "error_count": len(targets) - len(ok_rows),
        "average_confidence_overall": average,
        "threshold": threshold,
        "pass": pass_flag,
        "run_dir": str(config.run_dir),
        "results": rows,
        "remaining_failures": [
            {
                "image_id": failure["target"].asset.image_id if isinstance(failure.get("target"), Target) else None,
                "error": failure.get("error"),
            }
            for failure in failures
        ],
    }
    path = config.run_dir / ("summary.json" if final else "partial-summary.json")
    safe_write_text(path, json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", root=config.run_dir)
    return summary


def extract_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not include candidates[0].content.parts") from exc
    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise ValueError("Gemini response text was empty")
    return text


def parse_json_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def to_gemini_schema(value: Any) -> Any:
    """Convert strict OpenAI JSON schema into Gemini responseSchema subset."""
    if isinstance(value, list):
        return [to_gemini_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted: dict[str, Any] = {}
    for key, child in value.items():
        if key in {"$schema", "$id", "additionalProperties"}:
            continue
        if key == "type" and isinstance(child, list):
            non_null = [item for item in child if item != "null"]
            if len(non_null) == 1:
                converted["type"] = non_null[0]
                converted["nullable"] = True
            else:
                converted[key] = non_null
            continue
        converted[key] = to_gemini_schema(child)
    return converted


if __name__ == "__main__":
    raise SystemExit(main())
