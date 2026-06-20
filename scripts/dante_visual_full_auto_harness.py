#!/usr/bin/env python3
"""Full-corpus concurrent Gemini runner for Dante visual-analysis cards."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.dante_visual.cards import read_card, render_markdown  # noqa: E402
from app.dante_visual.gemini_provider import DEFAULT_GEMINI_MODEL, GeminiVisionAnalysisProvider  # noqa: E402
from app.dante_visual.manifest import VisualAsset, load_visual_manifest, validate_run_id  # noqa: E402
from app.dante_visual.orchestrator import (  # noqa: E402
    BASELINE_ROLES,
    PREMIUM_ROLES,
    VisionAnalysisProvider,
    generate_cards,
    select_premium_assets,
)
from app.dante_visual.safe_io import safe_append_text, safe_write_text  # noqa: E402
from dante_visual_analysis_harness import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    DEFAULT_VAULT_ROOT,
    cmd_contact_sheet,
    cmd_preflight,
    resolve_paths,
    write_analysis_manifest,
)


DEFAULT_RUN_ID = "visual-gemini-full-auto-20260613-codex"
PROGRESS_EVERY = 10


@dataclass(frozen=True)
class Target:
    index: int
    asset: VisualAsset
    premium: bool
    required_roles: set[str]


@dataclass(frozen=True)
class ExistingCardStatus:
    valid: bool
    reason: str
    row: dict[str, object] | None = None


@dataclass(frozen=True)
class ProviderConfig:
    asset_root: Path
    model_name: str
    timeout_s: float
    max_retries: int
    max_output_tokens: int
    max_image_edge: int
    jpeg_quality: int


_thread_state = threading.local()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--retry-passes", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="Optional cap for dry/progressive runs. 0 means all assets.")
    parser.add_argument("--all-premium", action="store_true", help="Run judge and confrontation roles for every asset.")
    parser.add_argument("--max-premium", type=int, default=315, help="Premium budget when --all-premium is not set.")
    parser.add_argument("--force", action="store_true", help="Re-run assets even when a valid Gemini card already exists.")
    parser.add_argument("--skip-contact-sheet", action="store_true")
    parser.add_argument("--gemini-model", default=os.getenv("GEMINI_VISION_MODEL", DEFAULT_GEMINI_MODEL))
    parser.add_argument("--gemini-timeout", type=float, default=75.0)
    parser.add_argument("--gemini-max-retries", type=int, default=3)
    parser.add_argument("--gemini-max-output-tokens", type=int, default=6144)
    parser.add_argument("--gemini-max-image-edge", type=int, default=1280)
    parser.add_argument("--gemini-jpeg-quality", type=int, default=82)
    args = parser.parse_args()

    run_id = validate_run_id(args.run_id)
    paths = resolve_paths(args.vault_root, args.dataset_root, run_id)
    provider_config = ProviderConfig(
        asset_root=paths["asset_root"],
        model_name=args.gemini_model,
        timeout_s=args.gemini_timeout,
        max_retries=args.gemini_max_retries,
        max_output_tokens=args.gemini_max_output_tokens,
        max_image_edge=args.gemini_max_image_edge,
        jpeg_quality=args.gemini_jpeg_quality,
    )

    cmd_preflight(paths)
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    if not manifest.is_valid:
        print(f"Preflight failed with {manifest.error_count} errors; full-auto run was not started.", file=sys.stderr)
        return 2
    provider_preflight = GeminiVisionAnalysisProvider(
        api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        asset_root=paths["asset_root"],
        model_name=provider_config.model_name,
        timeout_s=provider_config.timeout_s,
        max_retries=provider_config.max_retries,
        max_output_tokens=provider_config.max_output_tokens,
        max_image_edge=provider_config.max_image_edge,
        jpeg_quality=provider_config.jpeg_quality,
    ).preflight()
    if not provider_preflight.execute_ready:
        print(json.dumps(provider_preflight.__dict__, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    assets = manifest.assets[: args.limit] if args.limit > 0 else manifest.assets
    premium_ids = {asset.image_id for asset in assets} if args.all_premium else select_premium_assets(
        assets,
        max_premium=max(0, args.max_premium),
    )
    targets = [
        Target(
            index=index,
            asset=asset,
            premium=asset.image_id in premium_ids,
            required_roles=required_role_names(asset.image_id in premium_ids),
        )
        for index, asset in enumerate(assets)
    ]

    results: list[dict[str, object] | None] = [None] * len(targets)
    pending: list[Target] = []
    expected_model = provider_config.model_name.removeprefix("models/")
    for target in targets:
        status = ExistingCardStatus(valid=False, reason="forced") if args.force else existing_card_status(
            target,
            paths["cards_root"],
            expected_model=expected_model,
        )
        if status.valid and status.row is not None:
            results[target.index] = status.row
        else:
            pending.append(target)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "total_assets": len(targets),
                "already_valid_gemini_cards": len(targets) - len(pending),
                "pending_api_calls": len(pending),
                "premium_targets": sum(1 for target in targets if target.premium),
                "all_premium": args.all_premium,
                "concurrency": max(1, args.concurrency),
                "provider": provider_preflight.provider,
                "model": provider_preflight.model,
            },
            indent=2,
            sort_keys=True,
        )
    )

    failures: list[dict[str, object]] = []
    for pass_index in range(args.retry_passes + 1):
        if not pending:
            break
        failures = []
        print(json.dumps({"pass": pass_index + 1, "pending": len(pending)}, sort_keys=True))
        pass_rows, failures = process_targets(
            pending,
            paths=paths,
            run_id=run_id,
            provider_config=provider_config,
            concurrency=max(1, args.concurrency),
            pass_index=pass_index,
        )
        for target, row in pass_rows:
            results[target.index] = row

        pending = []
        for failure in failures:
            target = failure["target"]
            if not isinstance(target, Target):
                continue
            pending.append(target)

        write_partial_manifest(paths["analysis_manifest_path"], targets, results, failures)
        print(
            json.dumps(
                {
                    "pass": pass_index + 1,
                    "completed_total": sum(1 for row in results if row and not row.get("error")),
                    "failed_this_pass": len(failures),
                    "remaining": len(pending),
                },
                sort_keys=True,
            )
        )

    final_failures = [
        {
            "image_id": failure["target"].asset.image_id,
            "category": failure["target"].asset.category,
            "group": failure["target"].asset.group,
            "error": failure["error"],
        }
        for failure in failures
        if isinstance(failure.get("target"), Target)
    ]
    write_partial_manifest(paths["analysis_manifest_path"], targets, results, failures)
    rerendered = rerender_markdowns(paths["cards_root"])
    contact_result = None if args.skip_contact_sheet else run_contact_sheet(paths)
    summary = {
        "run_id": run_id,
        "total_assets": len(targets),
        "cards_ready": sum(1 for row in results if row and not row.get("error")),
        "remaining_errors": len(final_failures),
        "final_failures": final_failures,
        "markdowns_rerendered": rerendered,
        "contact_sheet": contact_result,
        "manifest_path": str(paths["analysis_manifest_path"]),
    }
    safe_write_text(
        paths["manifest_run_dir"] / "full-auto-summary.json",
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        root=paths["manifest_run_dir"],
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not final_failures else 1


def required_role_names(premium: bool) -> set[str]:
    roles = {role.value for role in BASELINE_ROLES}
    if premium:
        roles.update(role.value for role in PREMIUM_ROLES)
    return roles


def existing_card_status(target: Target, cards_root: Path, *, expected_model: str) -> ExistingCardStatus:
    path = card_json_path(target.asset, cards_root)
    if not path.exists():
        return ExistingCardStatus(valid=False, reason="missing_card")
    try:
        card = read_card(path)
    except Exception as exc:
        return ExistingCardStatus(valid=False, reason=f"invalid_card: {type(exc).__name__}: {exc}")
    source = card.get("source") if isinstance(card, dict) else None
    if not isinstance(source, dict) or source.get("sha256") != target.asset.sha256:
        return ExistingCardStatus(valid=False, reason="source_sha_mismatch")
    if source.get("new_relative_path") != target.asset.new_relative_path:
        return ExistingCardStatus(valid=False, reason="source_path_mismatch")
    runs = card.get("model_runs")
    if not isinstance(runs, list):
        return ExistingCardStatus(valid=False, reason="missing_model_runs")
    gemini_roles = {
        str(run.get("role"))
        for run in runs
        if (
            isinstance(run, dict)
            and run.get("provider") == "gemini"
            and str(run.get("model", "")).removeprefix("models/") == expected_model
            and run.get("role")
        )
    }
    missing_roles = target.required_roles - gemini_roles
    if missing_roles:
        return ExistingCardStatus(valid=False, reason=f"missing_gemini_roles: {sorted(missing_roles)}")
    return ExistingCardStatus(valid=True, reason="valid", row=result_row_for_card(target.asset, cards_root))


def result_row_for_card(asset: VisualAsset, cards_root: Path) -> dict[str, object]:
    json_path = card_json_path(asset, cards_root)
    md_path = json_path.with_suffix(".md")
    return {
        "image_id": asset.image_id,
        "card_json": str(json_path.relative_to(cards_root.parent)),
        "card_markdown": str(md_path.relative_to(cards_root.parent)),
        "premium": False,
        "error": "",
    }


def card_json_path(asset: VisualAsset, cards_root: Path) -> Path:
    return cards_root / asset.category / asset.group / f"{asset.file_stem}.json"


def process_targets(
    targets: list[Target],
    *,
    paths: dict[str, Path],
    run_id: str,
    provider_config: ProviderConfig,
    concurrency: int,
    pass_index: int,
) -> tuple[list[tuple[Target, dict[str, object]]], list[dict[str, object]]]:
    rows: list[tuple[Target, dict[str, object]]] = []
    failures: list[dict[str, object]] = []
    progress_lock = threading.Lock()
    completed = 0
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(process_one, target, paths, run_id, provider_config, pass_index): target for target in targets
        }
        for future in as_completed(future_map):
            target = future_map[future]
            completed += 1
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "image_id": target.asset.image_id,
                    "card_json": "",
                    "card_markdown": "",
                    "premium": target.premium,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            record = {
                "at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "pass": pass_index + 1,
                "index": target.index,
                "image_id": target.asset.image_id,
                "category": target.asset.category,
                "group": target.asset.group,
                "premium": target.premium,
                "error": row.get("error", ""),
            }
            with progress_lock:
                safe_append_text(
                    paths["manifest_run_dir"] / "full-auto-progress.jsonl",
                    json.dumps(record, sort_keys=True) + "\n",
                    root=paths["manifest_run_dir"],
                )
            if row.get("error"):
                failures.append({"target": target, "error": row["error"]})
            else:
                rows.append((target, row))
            if completed % PROGRESS_EVERY == 0 or completed == len(targets):
                print(
                    json.dumps(
                        {
                            "pass": pass_index + 1,
                            "completed_in_pass": completed,
                            "total_in_pass": len(targets),
                            "success_in_pass": len(rows),
                            "failed_in_pass": len(failures),
                            "started_at": started_at,
                        },
                        sort_keys=True,
                    )
                )
    return rows, failures


def process_one(
    target: Target,
    paths: dict[str, Path],
    run_id: str,
    provider_config: ProviderConfig,
    pass_index: int,
) -> dict[str, object]:
    provider = provider_for_thread(provider_config)
    result = generate_cards(
        [target.asset],
        cards_root=paths["cards_root"],
        raw_runs_root=paths["raw_runs_root"],
        run_id=run_id,
        provider=provider,
        max_premium=1 if target.premium else 0,
        continue_on_error=True,
    )
    row = result["results"][0]
    if row.get("error"):
        return row
    status = existing_card_status(
        target,
        paths["cards_root"],
        expected_model=provider_config.model_name.removeprefix("models/"),
    )
    if not status.valid:
        row["error"] = f"post_write_validation_failed: {status.reason}"
        return row
    row["premium"] = target.premium
    return row


def provider_for_thread(config: ProviderConfig) -> VisionAnalysisProvider:
    provider = getattr(_thread_state, "provider", None)
    if provider is None:
        provider = GeminiVisionAnalysisProvider(
            api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            asset_root=config.asset_root,
            model_name=config.model_name,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            max_output_tokens=config.max_output_tokens,
            max_image_edge=config.max_image_edge,
            jpeg_quality=config.jpeg_quality,
        )
        _thread_state.provider = provider
    return provider


def write_partial_manifest(
    manifest_path: Path,
    targets: list[Target],
    results: list[dict[str, object] | None],
    failures: list[dict[str, object]],
) -> None:
    failure_by_index = {
        failure["target"].index: failure["error"] for failure in failures if isinstance(failure.get("target"), Target)
    }
    rows: list[dict[str, object]] = []
    for target, row in zip(targets, results, strict=True):
        if row is not None:
            next_row = dict(row)
            next_row["premium"] = target.premium
            rows.append(next_row)
            continue
        rows.append(
            {
                "image_id": target.asset.image_id,
                "card_json": "",
                "card_markdown": "",
                "premium": target.premium,
                "error": failure_by_index.get(target.index, "pending"),
            }
        )
    write_analysis_manifest(manifest_path, rows)


def rerender_markdowns(cards_root: Path) -> int:
    count = 0
    for json_path in sorted(cards_root.rglob("*.json")):
        card = read_card(json_path)
        safe_write_text(json_path.with_suffix(".md"), render_markdown(card), root=cards_root)
        count += 1
    return count


def run_contact_sheet(paths: dict[str, Path]) -> dict[str, Any]:
    before = sys.stdout
    try:
        from io import StringIO

        buffer = StringIO()
        sys.stdout = buffer
        cmd_contact_sheet(paths)
        printed = buffer.getvalue().strip()
    finally:
        sys.stdout = before
    if printed:
        try:
            return json.loads(printed)
        except json.JSONDecodeError:
            return {"raw": printed}
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
