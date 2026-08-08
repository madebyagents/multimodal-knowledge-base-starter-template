#!/usr/bin/env python3
"""CLI harness for Dante visual-analysis cards and review artifacts."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))

from app.dante_visual.cards import read_card  # noqa: E402
from app.dante_visual.contact_sheet import (  # noqa: E402
    ReviewDecision,
    append_review_decision,
    generate_contact_sheet,
    load_review_decisions,
)
from app.dante_visual.gemini_provider import DEFAULT_GEMINI_MODEL, GeminiVisionAnalysisProvider  # noqa: E402
from app.dante_visual.manifest import load_visual_manifest, resolve_inside, safe_relative_path, validate_run_id, validate_slug  # noqa: E402
from app.dante_visual.orchestrator import MockVisionAnalysisProvider, VisionAnalysisProvider, generate_cards  # noqa: E402
from app.dante_visual.safe_io import safe_json_candidate, safe_write_text  # noqa: E402

DEFAULT_VAULT_ROOT = Path("/Users/vidigal/Dante")
DEFAULT_DATASET_ROOT = Path("commercial-film-production-kb/13-visual-reference-assets")
DEFAULT_EXTERNAL_ASSET_ROOT = Path("/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/visual-reference-assets/source-assets")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--run-id", default=None)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("preflight", help="Validate the canonical source-assets manifest")

    generate_parser = subcommands.add_parser("generate", help="Generate sample cards with the selected vision provider")
    generate_parser.add_argument("--sample", type=int, default=10)
    generate_parser.add_argument("--sample-mode", choices=["first", "stratified"], default="first")
    generate_parser.add_argument("--max-premium", type=int, default=2)
    generate_parser.add_argument("--provider", choices=["mock", "gemini"], default="mock")
    generate_parser.add_argument("--gemini-model", default=os.getenv("GEMINI_VISION_MODEL", DEFAULT_GEMINI_MODEL))
    generate_parser.add_argument("--gemini-timeout", type=float, default=90.0)
    generate_parser.add_argument("--gemini-max-retries", type=int, default=3)
    generate_parser.add_argument("--gemini-max-output-tokens", type=int, default=4096)
    generate_parser.add_argument("--continue-on-error", action="store_true")
    generate_parser.add_argument("--skip-contact-sheet", action="store_true")

    subcommands.add_parser("contact-sheet", help="Regenerate review/index.html from existing cards")

    decide_parser = subcommands.add_parser("decide", help="Append one review decision")
    decide_parser.add_argument("image_id")
    decide_parser.add_argument("status", choices=["pending", "approved", "rejected", "needs_premium", "needs_rerun"])
    decide_parser.add_argument("--reviewer", default="operator")
    decide_parser.add_argument("--reason", default="")

    bulk_parser = subcommands.add_parser("bulk-approve", help="Approve up to N currently pending cards")
    bulk_parser.add_argument("--limit", type=int, default=25)
    bulk_parser.add_argument("--reviewer", default="operator")
    bulk_parser.add_argument("--reason", default="bulk approve from visual-analysis harness")

    args = parser.parse_args()
    run_id = validate_run_id(args.run_id or default_run_id())
    paths = resolve_paths(args.vault_root, args.dataset_root, run_id)

    if args.command == "preflight":
        return cmd_preflight(paths)
    if args.command == "generate":
        return cmd_generate(
            paths,
            sample=args.sample,
            sample_mode=args.sample_mode,
            max_premium=args.max_premium,
            contact_sheet=not args.skip_contact_sheet,
            provider_name=args.provider,
            gemini_model=args.gemini_model,
            gemini_timeout=args.gemini_timeout,
            gemini_max_retries=args.gemini_max_retries,
            gemini_max_output_tokens=args.gemini_max_output_tokens,
            continue_on_error=args.continue_on_error,
        )
    if args.command == "contact-sheet":
        return cmd_contact_sheet(paths)
    if args.command == "decide":
        return cmd_decide(paths, args.image_id, args.status, reviewer=args.reviewer, reason=args.reason)
    if args.command == "bulk-approve":
        return cmd_bulk_approve(paths, limit=args.limit, reviewer=args.reviewer, reason=args.reason)
    raise AssertionError(f"Unhandled command: {args.command}")


def default_run_id() -> str:
    return datetime.now(UTC).strftime("visual-%Y%m%dT%H%M%SZ")


def resolve_paths(vault_root: Path, dataset_root: Path, run_id: str) -> dict[str, Path]:
    vault_abs = vault_root.resolve()
    dataset_rel = safe_relative_path(str(dataset_root), field_name="dataset_root")
    dataset_abs = resolve_inside(vault_abs, dataset_rel)
    analysis_root = dataset_abs / "analysis-cards"
    manifest_run_dir = analysis_root / "manifests" / run_id
    asset_root = DEFAULT_EXTERNAL_ASSET_ROOT if DEFAULT_EXTERNAL_ASSET_ROOT.exists() else dataset_abs / "source-assets"
    return {
        "vault_root": vault_abs,
        "dataset_root": dataset_abs,
        "asset_root": asset_root,
        "manifest_path": asset_root / "asset-manifest.tsv",
        "analysis_root": analysis_root,
        "cards_root": analysis_root / "cards",
        "raw_runs_root": analysis_root / "raw-runs",
        "manifest_run_dir": manifest_run_dir,
        "preflight_path": manifest_run_dir / "preflight.json",
        "analysis_manifest_path": manifest_run_dir / "analysis-manifest.tsv",
        "decisions_log": analysis_root / "review-decisions.jsonl",
        "review_state_path": analysis_root / "review-state.tsv",
        "review_dir": dataset_abs / "review",
    }


def cmd_preflight(paths: dict[str, Path]) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    payload = {
        "summary": manifest.summary(),
        "issues": [issue.__dict__ for issue in manifest.issues],
    }
    safe_write_text(
        paths["preflight_path"],
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        root=paths["manifest_run_dir"],
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0 if manifest.is_valid else 2


def cmd_generate(
    paths: dict[str, Path],
    *,
    sample: int,
    sample_mode: str,
    max_premium: int,
    contact_sheet: bool,
    provider_name: str,
    gemini_model: str,
    gemini_timeout: float,
    gemini_max_retries: int,
    gemini_max_output_tokens: int,
    continue_on_error: bool,
) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    cmd_preflight(paths)
    if not manifest.is_valid:
        print(f"Preflight failed with {manifest.error_count} errors; cards were not generated.", file=sys.stderr)
        return 2
    assets = select_assets(manifest.assets, sample=max(0, sample), sample_mode=sample_mode)
    result = generate_cards(
        assets,
        cards_root=paths["cards_root"],
        raw_runs_root=paths["raw_runs_root"],
        run_id=paths["manifest_run_dir"].name,
        provider=build_provider(
            provider_name,
            paths=paths,
            gemini_model=gemini_model,
            gemini_timeout=gemini_timeout,
            gemini_max_retries=gemini_max_retries,
            gemini_max_output_tokens=gemini_max_output_tokens,
        ),
        max_premium=max(0, max_premium),
        continue_on_error=continue_on_error,
    )
    write_analysis_manifest(paths["analysis_manifest_path"], result["results"])
    if contact_sheet:
        cmd_contact_sheet(paths)
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2, sort_keys=True))
    return 0


def build_provider(
    provider_name: str,
    *,
    paths: dict[str, Path],
    gemini_model: str,
    gemini_timeout: float,
    gemini_max_retries: int,
    gemini_max_output_tokens: int,
) -> VisionAnalysisProvider:
    if provider_name == "mock":
        return MockVisionAnalysisProvider()
    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        return GeminiVisionAnalysisProvider(
            api_key=api_key,
            asset_root=paths["asset_root"],
            model_name=gemini_model,
            timeout_s=gemini_timeout,
            max_retries=gemini_max_retries,
            max_output_tokens=gemini_max_output_tokens,
        )
    raise ValueError(f"Unsupported provider: {provider_name}")


def select_assets(assets: list[object], *, sample: int, sample_mode: str) -> list[object]:
    if sample <= 0:
        return []
    if sample_mode == "first":
        return assets[:sample]
    if sample_mode != "stratified":
        raise ValueError(f"Unsupported sample mode: {sample_mode}")
    groups: dict[tuple[str, str], list[object]] = {}
    for asset in assets:
        key = (getattr(asset, "category"), getattr(asset, "group"))
        groups.setdefault(key, []).append(asset)
    selected: list[object] = []
    group_values = list(groups.values())
    index = 0
    while len(selected) < sample:
        added = False
        for group_assets in group_values:
            if index < len(group_assets):
                selected.append(group_assets[index])
                added = True
                if len(selected) >= sample:
                    break
        if not added:
            break
        index += 1
    return selected


def write_analysis_manifest(path: Path, rows: object) -> None:
    import io

    output = io.StringIO()
    fields = ["image_id", "card_json", "card_markdown", "premium", "error"]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    safe_write_text(path, output.getvalue(), root=path.parent)


def cmd_contact_sheet(paths: dict[str, Path]) -> int:
    result = generate_contact_sheet(
        cards_root=paths["cards_root"],
        asset_root=paths["asset_root"],
        review_dir=paths["review_dir"],
        decisions_log=paths["decisions_log"],
        review_state_path=paths["review_state_path"],
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_decide(paths: dict[str, Path], image_id: str, status: str, *, reviewer: str, reason: str) -> int:
    card_path = find_card(paths["cards_root"], image_id)
    card = read_card(card_path)
    payload = append_review_decision(
        paths["decisions_log"],
        ReviewDecision(
            image_id=image_id,
            source_sha256=card["source"]["sha256"],
            status=status,
            reviewer=reviewer,
            reason=reason,
            run_id=paths["manifest_run_dir"].name,
            card_schema_version=card["schema_version"],
        ),
    )
    cmd_contact_sheet(paths)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_bulk_approve(paths: dict[str, Path], *, limit: int, reviewer: str, reason: str) -> int:
    cards = [read_card(path) for path in sorted(paths["cards_root"].rglob("*.json"))]
    decisions = load_review_decisions(paths["decisions_log"])
    approved = 0
    for card in cards:
        if approved >= limit:
            break
        current_status = decisions.get(card["source"]["sha256"], {}).get("status") or card["review"]["status"]
        if current_status != "pending":
            continue
        append_review_decision(
            paths["decisions_log"],
            ReviewDecision(
                image_id=card["image_id"],
                source_sha256=card["source"]["sha256"],
                status="approved",
                reviewer=reviewer,
                reason=reason,
                run_id=paths["manifest_run_dir"].name,
                card_schema_version=card["schema_version"],
            ),
        )
        approved += 1
    cmd_contact_sheet(paths)
    print(json.dumps({"approved": approved}, indent=2, sort_keys=True))
    return 0


def find_card(cards_root: Path, image_id: str) -> Path:
    validate_slug(image_id, field_name="image_id")
    matches = [
        safe_path
        for path in cards_root.rglob(f"{image_id}.json")
        if (safe_path := safe_json_candidate(path, root=cards_root)) is not None
    ]
    if not matches:
        raise FileNotFoundError(f"No card found for image_id {image_id!r}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple cards found for image_id {image_id!r}")
    return matches[0]


if __name__ == "__main__":
    raise SystemExit(main())
