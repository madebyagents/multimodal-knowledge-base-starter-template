"""Static contact-sheet and review-state generation."""
from __future__ import annotations

import csv
import html
import io
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from PIL import Image, UnidentifiedImageError

from .cards import REVIEW_STATUSES, read_card
from .manifest import resolve_inside, safe_relative_path, validate_run_id
from .safe_io import safe_append_text, safe_json_candidate, safe_mkdir, safe_write_bytes, safe_write_text


@dataclass(frozen=True)
class ReviewDecision:
    image_id: str
    source_sha256: str
    status: str
    reviewer: str
    reason: str
    run_id: str
    card_schema_version: str
    threshold_version: str | None = None
    created_at: str | None = None

    def normalized(self) -> dict[str, str]:
        if self.status not in REVIEW_STATUSES:
            raise ValueError(f"Unsupported review status: {self.status}")
        payload = asdict(self)
        payload["created_at"] = self.created_at or utc_now_iso()
        return {key: "" if value is None else str(value) for key, value in payload.items()}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def append_review_decision(log_path: Path, decision: ReviewDecision) -> dict[str, str]:
    payload = decision.normalized()
    safe_append_text(log_path, json.dumps(payload, sort_keys=True) + "\n", root=log_path.parent)
    return payload


def load_review_decisions(log_path: Path) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    if not log_path.exists():
        return latest
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            source_sha256 = str(payload.get("source_sha256", ""))
            if source_sha256:
                latest[source_sha256] = {key: "" if value is None else str(value) for key, value in payload.items()}
    return latest


def write_review_state(cards: list[dict], decisions_log: Path, state_path: Path) -> dict[str, int]:
    decisions = load_review_decisions(decisions_log)
    counts = {status: 0 for status in sorted(REVIEW_STATUSES)}
    fields = [
        "image_id",
        "source_sha256",
        "status",
        "reviewer",
        "reason",
        "run_id",
        "card_schema_version",
        "threshold_version",
        "created_at",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for card in sorted(cards, key=lambda item: item["image_id"]):
        source = card["source"]
        decision = decisions.get(source["sha256"])
        status = decision["status"] if decision else card["review"]["status"]
        counts[status] = counts.get(status, 0) + 1
        writer.writerow(
            {
                "image_id": card["image_id"],
                "source_sha256": source["sha256"],
                "status": status,
                "reviewer": decision.get("reviewer", "") if decision else "",
                "reason": decision.get("reason", "") if decision else "",
                "run_id": decision.get("run_id", card["run_id"]) if decision else card["run_id"],
                "card_schema_version": decision.get("card_schema_version", card["schema_version"])
                if decision
                else card["schema_version"],
                "threshold_version": decision.get("threshold_version", "") if decision else "",
                "created_at": decision.get("created_at", "") if decision else "",
            }
        )
    safe_write_text(state_path, output.getvalue(), root=state_path.parent)
    return counts


def load_cards(cards_root: Path) -> tuple[list[dict], list[dict[str, str]]]:
    cards: list[dict] = []
    residuals: list[dict[str, str]] = []
    for path in sorted(cards_root.rglob("*.json")):
        safe_path = safe_json_candidate(path, root=cards_root)
        if safe_path is None:
            residuals.append({"path": str(path), "reason": "unsafe card path or symlink"})
            continue
        try:
            cards.append(read_card(safe_path))
        except (ValueError, json.JSONDecodeError) as exc:
            residuals.append({"path": str(path), "reason": str(exc)})
    return cards, residuals


def generate_contact_sheet(
    *,
    cards_root: Path,
    asset_root: Path,
    review_dir: Path,
    decisions_log: Path,
    review_state_path: Path,
    title: str = "Dante Visual Analysis Review",
) -> dict[str, object]:
    cards, residuals = load_cards(cards_root)
    safe_mkdir(review_dir, root=review_dir)
    thumbnail_root = review_dir / "assets" / "thumbnails"
    safe_mkdir(thumbnail_root, root=review_dir)
    state_counts = write_review_state(cards, decisions_log, review_state_path)
    decisions = load_review_decisions(decisions_log)
    rows = []
    for card in cards:
        try:
            rows.append(_card_to_row(card, cards_root, asset_root, review_dir, thumbnail_root, decisions))
        except (ValueError, OSError) as exc:
            residuals.append({"path": card.get("image_id", "unknown"), "reason": str(exc)})
    html_path = review_dir / "index.html"
    safe_write_text(html_path, _render_html(title, rows, state_counts, residuals), root=review_dir)
    if residuals:
        safe_write_text(
            review_dir / "residuals.json",
            json.dumps(residuals, indent=2, sort_keys=True) + "\n",
            root=review_dir,
        )
    return {
        "html_path": str(html_path),
        "card_count": len(cards),
        "residual_count": len(residuals),
        "state_counts": state_counts,
    }


def _card_to_row(
    card: dict,
    cards_root: Path,
    asset_root: Path,
    review_dir: Path,
    thumbnail_root: Path,
    decisions: dict[str, dict[str, str]],
) -> dict[str, str]:
    source = card["source"]
    relative_image_path = safe_relative_path(source["new_relative_path"], field_name="card source path")
    image_path = resolve_inside(asset_root, relative_image_path)
    thumb_path = _thumbnail_for(image_path, thumbnail_root, source["category"], source["group"])
    card_json_path = cards_root / source["category"] / source["group"] / f"{Path(source['new_relative_path']).stem}.json"
    card_md_path = card_json_path.with_suffix(".md")
    decision = decisions.get(source["sha256"], {})
    status = decision.get("status") or card["review"]["status"]
    judgment = card.get("editorial_judgment", {})
    flags = ", ".join(judgment.get("flags", []))
    return {
        "image_id": card["image_id"],
        "status": status,
        "group": source["group"],
        "category": source["category"],
        "score": str(judgment.get("score", 0)),
        "tier": str(judgment.get("tier", "unrated")),
        "flags": flags,
        "thumbnail_href": safe_href(review_dir, thumb_path, [review_dir]),
        "image_href": safe_href(review_dir, image_path, [asset_root]),
        "json_href": safe_href(review_dir, card_json_path, [cards_root]),
        "markdown_href": safe_href(review_dir, card_md_path, [cards_root]),
        "source_sha256": source["sha256"],
    }


def _thumbnail_for(image_path: Path, thumbnail_root: Path, category: str, group: str) -> Path:
    target_dir = thumbnail_root / category / group
    safe_mkdir(target_dir, root=thumbnail_root)
    target = target_dir / image_path.name
    if target.is_symlink():
        raise ValueError(f"Refusing thumbnail symlink target: {target}")
    if target.exists():
        return target
    try:
        with Image.open(image_path) as image:
            image.thumbnail((320, 180))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "JPEG", quality=82)
            safe_write_bytes(target, buffer.getvalue(), root=thumbnail_root)
    except (UnidentifiedImageError, OSError):
        return image_path
    return target


def safe_href(from_dir: Path, target: Path, allowed_roots: Iterable[Path]) -> str:
    target_resolved = target.resolve()
    allowed = False
    for root in allowed_roots:
        try:
            target_resolved.relative_to(root.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ValueError(f"Target is outside allowed roots: {target}")
    rel_text = os.path.relpath(target_resolved, from_dir.resolve())
    if rel_text.startswith(("javascript:", "data:", "http:", "https:")):
        raise ValueError(f"Unsafe link scheme: {rel_text}")
    return quote(rel_text)


def _render_html(title: str, rows: list[dict[str, str]], state_counts: dict[str, int], residuals: list[dict[str, str]]) -> str:
    cards = "\n".join(_render_card(row) for row in rows)
    state = " ".join(f"{html.escape(key)}: {count}" for key, count in sorted(state_counts.items()))
    residual_notice = (
        f"<p class=\"warning\">Residual cards excluded: {len(residuals)}</p>" if residuals else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file: data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; color: #171717; background: #f7f7f5; }}
    header {{ padding: 20px 24px; border-bottom: 1px solid #d8d8d0; background: #ffffff; position: sticky; top: 0; z-index: 1; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    .summary {{ color: #4b5563; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; padding: 18px; }}
    article {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }}
    img {{ width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #ececec; display: block; }}
    .body {{ padding: 12px; }}
    .meta {{ color: #4b5563; font-size: 12px; line-height: 1.45; }}
    .links a {{ margin-right: 10px; font-size: 12px; color: #1358a2; }}
    .status {{ display: inline-block; padding: 2px 8px; border: 1px solid #ccc; border-radius: 999px; font-size: 12px; }}
    .warning {{ color: #8a3b12; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <div class="summary">Cards: {len(rows)}. Review states: {state}</div>
    {residual_notice}
  </header>
  <main class="grid">
    {cards or '<p>No cards generated yet.</p>'}
  </main>
</body>
</html>
"""


def _render_card(row: dict[str, str]) -> str:
    return f"""<article>
  <a href="{html.escape(row['image_href'], quote=True)}"><img src="{html.escape(row['thumbnail_href'], quote=True)}" alt="{html.escape(row['image_id'])} thumbnail"></a>
  <div class="body">
    <strong>{html.escape(row['image_id'])}</strong>
    <div><span class="status">{html.escape(row['status'])}</span></div>
    <div class="meta">
      Group: {html.escape(row['group'])}<br>
      Category: {html.escape(row['category'])}<br>
      Score: {html.escape(row['score'])} / Tier: {html.escape(row['tier'])}<br>
      Flags: {html.escape(row['flags'] or 'none')}<br>
      SHA: <code>{html.escape(row['source_sha256'][:12])}</code>
    </div>
    <div class="links">
      <a href="{html.escape(row['json_href'], quote=True)}">JSON</a>
      <a href="{html.escape(row['markdown_href'], quote=True)}">Markdown</a>
      <a href="{html.escape(row['image_href'], quote=True)}">Image</a>
    </div>
  </div>
</article>"""


def validate_review_run_id(run_id: str) -> str:
    return validate_run_id(run_id)
