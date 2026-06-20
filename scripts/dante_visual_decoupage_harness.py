#!/usr/bin/env python3
"""CLI harness for premium Dante decoupage sidecars."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env", override=True)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.dante_visual.decoupage import DECOUPAGE_PROFILE_ID  # noqa: E402
from app.dante_visual.manifest import VisualAsset, load_visual_manifest, validate_run_id  # noqa: E402
from app.dante_visual.openai_decoupage_provider import (  # noqa: E402
    DEFAULT_OPENAI_DECOUPAGE_MODEL,
    DEFAULT_OPENAI_RESPONSES_BASE_URL,
    MockDecoupageProvider,
    OpenAIDecoupageProvider,
)
from app.dante_visual.safe_io import safe_write_text  # noqa: E402
from dante_visual_analysis_harness import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    DEFAULT_VAULT_ROOT,
    resolve_paths as resolve_base_paths,
    select_assets,
)

DEFAULT_RUN_ID = "visual-decoupage-smoke"
LENSES = ("solo", "dp", "art_cast", "critic", "judge", "confrontador")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--run-id", default=None)
    subcommands = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subcommands.add_parser("preflight", help="Validate manifest and selected provider readiness")
    add_provider_args(preflight_parser)

    generate_parser = subcommands.add_parser("generate", help="Generate bounded decoupage sidecars")
    generate_parser.add_argument("--sample", type=int, default=1)
    generate_parser.add_argument("--sample-mode", choices=["first", "stratified"], default="first")
    generate_parser.add_argument("--lens", choices=LENSES, default="solo")
    generate_parser.add_argument("--force", action="store_true", help="Overwrite existing decoupage sidecars")
    generate_parser.add_argument("--continue-on-error", action="store_true")
    add_provider_args(generate_parser)

    args = parser.parse_args()
    run_id = validate_run_id(args.run_id or default_run_id())
    paths = resolve_paths(args.vault_root, args.dataset_root, run_id)

    if args.command == "preflight":
        return cmd_preflight(paths, args)
    if args.command == "generate":
        return cmd_generate(paths, args)
    raise AssertionError(f"Unhandled command: {args.command}")


def add_provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["mock", "openai"], default="mock")
    parser.add_argument("--openai-model", default=os.getenv("OPENAI_DECOUPAGE_MODEL", DEFAULT_OPENAI_DECOUPAGE_MODEL))
    parser.add_argument("--openai-base-url", default=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_RESPONSES_BASE_URL))
    parser.add_argument("--openai-timeout", type=float, default=float(os.getenv("OPENAI_DECOUPAGE_TIMEOUT", "180")))
    parser.add_argument("--openai-max-retries", type=int, default=int(os.getenv("OPENAI_DECOUPAGE_MAX_RETRIES", "2")))
    parser.add_argument("--openai-max-output-tokens", type=int, default=int(os.getenv("OPENAI_DECOUPAGE_MAX_OUTPUT_TOKENS", "8192")))
    parser.add_argument("--openai-max-image-edge", type=int, default=int(os.getenv("OPENAI_DECOUPAGE_MAX_IMAGE_EDGE", "1280")))
    parser.add_argument("--openai-jpeg-quality", type=int, default=int(os.getenv("OPENAI_DECOUPAGE_JPEG_QUALITY", "82")))
    parser.add_argument("--reasoning-effort", default=os.getenv("OPENAI_DECOUPAGE_REASONING_EFFORT", "high"))
    parser.add_argument("--text-verbosity", default=os.getenv("OPENAI_DECOUPAGE_TEXT_VERBOSITY", "high"))


def default_run_id() -> str:
    return datetime.now(UTC).strftime("visual-decoupage-%Y%m%dT%H%M%SZ")


def resolve_paths(vault_root: Path, dataset_root: Path, run_id: str) -> dict[str, Path]:
    base = resolve_base_paths(vault_root, dataset_root, run_id)
    decoupage_root = base["analysis_root"] / "decoupage"
    return {
        **base,
        "decoupage_root": decoupage_root,
        "decoupage_sidecars_root": decoupage_root / "sidecars",
        "decoupage_markdown_root": decoupage_root / "markdown",
        "decoupage_manifest_run_dir": decoupage_root / "manifests" / run_id,
        "decoupage_preflight_path": decoupage_root / "manifests" / run_id / "preflight.json",
        "decoupage_manifest_path": decoupage_root / "manifests" / run_id / "decoupage-manifest.tsv",
        "decoupage_summary_path": decoupage_root / "manifests" / run_id / "summary.json",
    }


def cmd_preflight(paths: dict[str, Path], args: argparse.Namespace) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    provider = build_provider(paths, args)
    preflight = provider.preflight()
    payload = {
        "profile_id": DECOUPAGE_PROFILE_ID,
        "run_id": paths["decoupage_manifest_run_dir"].name,
        "manifest_summary": manifest.summary(),
        "manifest_issues": [issue.__dict__ for issue in manifest.issues],
        "provider_preflight": preflight.__dict__,
        "output_root": str(paths["decoupage_root"]),
    }
    safe_write_text(
        paths["decoupage_preflight_path"],
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        root=paths["decoupage_manifest_run_dir"],
    )
    print(json.dumps({"manifest": manifest.summary(), "provider_preflight": preflight.__dict__}, indent=2, sort_keys=True))
    return 0 if manifest.is_valid and preflight.execute_ready else 2


def cmd_generate(paths: dict[str, Path], args: argparse.Namespace) -> int:
    manifest = load_visual_manifest(paths["manifest_path"], paths["asset_root"])
    if not manifest.is_valid:
        print(f"Preflight failed with {manifest.error_count} manifest errors; sidecars were not generated.", file=sys.stderr)
        return 2
    provider = build_provider(paths, args)
    preflight = provider.preflight()
    if not preflight.execute_ready:
        print(json.dumps(preflight.__dict__, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    assets = select_assets(manifest.assets, sample=max(0, args.sample), sample_mode=args.sample_mode)
    rows: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    written = 0
    skipped = 0
    for asset in assets:
        sidecar_path = decoupage_json_path(asset, paths["decoupage_sidecars_root"])
        markdown_path = decoupage_markdown_path(asset, paths["decoupage_markdown_root"])
        if sidecar_path.exists() and markdown_path.exists() and not args.force:
            skipped += 1
            rows.append(row_for_asset(asset, sidecar_path, markdown_path, skipped=True))
            continue
        try:
            payload = provider.analyze(asset, lens=args.lens)
            safe_write_text(
                sidecar_path,
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                root=paths["decoupage_root"],
            )
            safe_write_text(
                markdown_path,
                payload["markdown_handoff"].rstrip() + "\n",
                root=paths["decoupage_root"],
            )
            written += 1
            rows.append(row_for_asset(asset, sidecar_path, markdown_path, skipped=False))
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            errors.append({"image_id": asset.image_id, "error": error})
            rows.append(
                {
                    "image_id": asset.image_id,
                    "sidecar_json": "",
                    "sidecar_markdown": "",
                    "source_sha256": asset.sha256,
                    "skipped": False,
                    "error": error,
                }
            )
            if not args.continue_on_error:
                break

    write_manifest(paths["decoupage_manifest_path"], rows)
    summary = {
        "profile_id": DECOUPAGE_PROFILE_ID,
        "run_id": paths["decoupage_manifest_run_dir"].name,
        "provider": preflight.provider,
        "model": preflight.model,
        "lens": args.lens,
        "targeted": len(assets),
        "written": written,
        "skipped": skipped,
        "error_count": len(errors),
        "errors": errors,
        "manifest_path": str(paths["decoupage_manifest_path"]),
    }
    safe_write_text(
        paths["decoupage_summary_path"],
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        root=paths["decoupage_manifest_run_dir"],
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


def build_provider(paths: dict[str, Path], args: argparse.Namespace) -> Any:
    if args.provider == "mock":
        return MockDecoupageProvider()
    if args.provider == "openai":
        return OpenAIDecoupageProvider(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            asset_root=paths["asset_root"],
            model_name=args.openai_model,
            base_url=args.openai_base_url,
            timeout_s=args.openai_timeout,
            max_retries=args.openai_max_retries,
            max_image_edge=args.openai_max_image_edge,
            jpeg_quality=args.openai_jpeg_quality,
            max_output_tokens=args.openai_max_output_tokens,
            reasoning_effort=args.reasoning_effort,
            text_verbosity=args.text_verbosity,
        )
    raise ValueError(f"Unsupported provider: {args.provider}")


def decoupage_json_path(asset: VisualAsset, root: Path) -> Path:
    return root / asset.category / asset.group / f"{asset.file_stem}.json"


def decoupage_markdown_path(asset: VisualAsset, root: Path) -> Path:
    return root / asset.category / asset.group / f"{asset.file_stem}.md"


def row_for_asset(asset: VisualAsset, sidecar_path: Path, markdown_path: Path, *, skipped: bool) -> dict[str, object]:
    return {
        "image_id": asset.image_id,
        "sidecar_json": str(sidecar_path),
        "sidecar_markdown": str(markdown_path),
        "source_sha256": asset.sha256,
        "skipped": skipped,
        "error": "",
    }


def write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    import io

    output = io.StringIO()
    fields = ["image_id", "sidecar_json", "sidecar_markdown", "source_sha256", "skipped", "error"]
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    safe_write_text(path, output.getvalue(), root=path.parent)


if __name__ == "__main__":
    raise SystemExit(main())
