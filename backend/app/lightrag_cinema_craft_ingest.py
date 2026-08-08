"""Guarded ingest helpers for the LightRAG cinema craft canon suites."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import httpx

DEFAULT_LIGHTRAG_BASE_URL = "http://127.0.0.1:9621"
DEFAULT_MAX_BATCH_CHARS = 150_000
DEFAULT_MAX_BATCH_ITEMS = 20
DEFAULT_MAX_FILE_CHARS = 300_000
DEFAULT_EVAL_THRESHOLD = 0.72
DEFAULT_MAX_CONTROL_FILE_CHARS = 8_000

MARKDOWN_SUFFIX = ".md"
REPORTS_ROOT = Path("docs/reports")
RUN_PREFIX = "lightrag-cinema-craft-ingest"

SKIP_DIR_NAMES = {"quarantine", "__MACOSX"}
SKIP_FILE_NAMES = {".DS_Store"}
DEFAULT_SKIP_ROLES = {"agent_prompt", "package_stats", "unknown"}
CONTROL_PLANE_ROLES = {
    "eval_card",
    "graph_hint",
    "ingestion_metadata",
    "root_or_package_metadata",
    "strategy_or_map",
}
MEDIA_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
    ".aiff",
    ".pdf",
    ".srt",
    ".vtt",
}
RIGHTS_WARNING_PATTERNS = (
    "full screenplay",
    "full script",
    "subtitle dump",
    "lyrics",
    "long quote",
    "copied transcript",
    "full chapter",
    "full essay",
)
RIGHTS_SAFE_CONTEXT_PATTERNS = (
    "rights-safe",
    "rights safe",
    "no protected full text",
    "no full protected source text",
    "no protected source text",
    "no screenplays",
    "no stills",
    "no frames",
    "no photographs",
    "no lyrics",
    "no videos",
    "no long quotes",
    "does not include",
    "do not include",
    "metadata_summary_concept_cards_only",
)
NOISY_RESPONSE_PATTERNS = (
    "base64,",
    "excalidraw",
    "<svg",
    "data:image",
)
NON_RETRYABLE_FAILED_PATTERNS = (
    "insufficient balance",
    "error code: 402",
    "insufficient_quota",
    "payment required",
    "billing",
)
FAILED_DOCUMENT_SNAPSHOT_LIMIT = 12


@dataclass(frozen=True)
class InventoryRow:
    suite_id: str
    source_relative_path: str
    suite_relative_path: str
    package_id: str | None
    domain: str | None
    priority: str | None
    role: str
    suffix: str
    bytes: int
    chars: int
    sha256: str | None
    selected: bool
    skip_reason: str | None = None
    rights_warnings: list[str] = field(default_factory=list)
    rights_status: str = "clear"


@dataclass(frozen=True)
class BatchItem:
    document_id: str
    source_sha256: str
    suite_id: str
    source_relative_path: str
    package_id: str | None
    role: str
    text: str
    rights_status: str
    rights_warnings: list[str]


@dataclass(frozen=True)
class Batch:
    batch_id: str
    item_count: int
    char_count: int
    document_ids: list[str]


@dataclass(frozen=True)
class ExistingDocumentIndex:
    source_hashes: set[str] = field(default_factory=set)
    file_sources: set[str] = field(default_factory=set)
    document_ids: set[str] = field(default_factory=set)


@dataclass
class IngestSummary:
    run_id: str
    dry_run: bool
    base_url: str
    batches_total: int
    batches_sent: int = 0
    items_total: int = 0
    chars_total: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    preflight: dict[str, Any] = field(default_factory=dict)
    final_pipeline_status: dict[str, Any] = field(default_factory=dict)
    final_status_counts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        if self.errors:
            return False
        if self.dry_run:
            return True
        if self.batches_sent != self.batches_total:
            return False
        if self.final_pipeline_status.get("timed_out") or self.final_pipeline_status.get("settled") is False:
            return False
        if self.final_pipeline_status.get("busy") or self.final_pipeline_status.get("request_pending"):
            return False
        return _active_count(self.final_status_counts) == 0


@dataclass(frozen=True)
class EvalQuery:
    query: str
    expected_terms: list[str]
    source: str
    mode: str = "mix"
    expected_qualities: list[str] = field(default_factory=list)
    expected_path_fragment: str | None = None
    domain: str | None = None
    rights_mode: str | None = None


@dataclass(frozen=True)
class JudgeVerdict:
    score: float
    rights_safe: bool
    reason: str


# A judge takes the eval query and the candidate answer and returns a verdict.
Judge = Callable[["EvalQuery", str], JudgeVerdict]


@dataclass(frozen=True)
class EvalResult:
    query: str
    score: float
    usable: bool
    matched_terms: list[str]
    expected_terms: list[str]
    reference_count: int
    latency_s: float
    judge_score: float = 0.0
    retrieval_precision: float = 0.0
    sanity_score: float = 0.0
    rights_safe: bool = True
    judge_reason: str = ""
    source: str = ""
    error: str | None = None


def build_run_id() -> str:
    return f"{RUN_PREFIX}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"


def default_report_dir(run_id: str) -> Path:
    return REPORTS_ROOT / run_id


def inventory_source(
    source_root: Path,
    *,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
    include_agent_prompts: bool = False,
) -> list[InventoryRow]:
    root = source_root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"source_root_not_found: {source_root}")
    suite_roots = _find_suite_roots(root)
    if not suite_roots:
        raise ValueError("no_lightrag_suite_manifests_found")

    package_meta = _load_package_metadata(suite_roots)
    rows: list[InventoryRow] = []
    for suite_root in suite_roots:
        for path in sorted(suite_root.rglob("*")):
            if not path.is_file():
                continue
            row = _inventory_file(
                root,
                path,
                package_meta=package_meta,
                max_file_chars=max_file_chars,
                include_agent_prompts=include_agent_prompts,
            )
            rows.append(row)
    return rows


def write_inventory_reports(rows: Sequence[InventoryRow], report_dir: Path) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_inventory(rows)
    (report_dir / "inventory-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (report_dir / "inventory-summary.md").write_text(_inventory_markdown(summary), encoding="utf-8")
    _write_jsonl(report_dir / "inventory-manifest.jsonl", (asdict(row) for row in rows))
    return summary


def summarize_inventory(rows: Sequence[InventoryRow]) -> dict[str, Any]:
    selected = [row for row in rows if row.selected]
    skipped = [row for row in rows if not row.selected]
    by_suite: dict[str, dict[str, int]] = {}
    by_role: dict[str, int] = {}
    by_skip_reason: dict[str, int] = {}
    for row in rows:
        suite = by_suite.setdefault(row.suite_id, {"total": 0, "selected": 0, "skipped": 0, "chars": 0})
        suite["total"] += 1
        suite["chars"] += row.chars
        if row.selected:
            suite["selected"] += 1
        else:
            suite["skipped"] += 1
            by_skip_reason[row.skip_reason or "unknown"] = by_skip_reason.get(row.skip_reason or "unknown", 0) + 1
        by_role[row.role] = by_role.get(row.role, 0) + 1
    return {
        "total_files": len(rows),
        "selected_files": len(selected),
        "skipped_files": len(skipped),
        "selected_chars": sum(row.chars for row in selected),
        "selected_bytes": sum(row.bytes for row in selected),
        "rights_warning_files": sum(1 for row in rows if row.rights_warnings),
        "by_suite": by_suite,
        "by_role": dict(sorted(by_role.items())),
        "by_skip_reason": dict(sorted(by_skip_reason.items())),
    }


def filter_rows_by_suite(rows: Sequence[InventoryRow], only_suite: str | None) -> list[InventoryRow]:
    """Restrict inventory rows to suites matching any comma-separated token.

    Tokens match by substring against ``suite_id`` (so ``enrichment`` selects
    both ``canon_enrichment_suite`` and ``canon_enrichment_round_02``). Used to
    prioritise a gate-critical layer when provider budget is scarce.
    """
    if not only_suite:
        return list(rows)
    allowed = [token.strip() for token in only_suite.split(",") if token.strip()]
    if not allowed:
        return list(rows)
    return [row for row in rows if any(token in row.suite_id for token in allowed)]


def prepare_batches(
    source_root: Path,
    rows: Sequence[InventoryRow],
    report_dir: Path,
    *,
    max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
    limit_items: int | None = None,
    existing_index: ExistingDocumentIndex | None = None,
) -> tuple[list[BatchItem], list[Batch]]:
    report_dir.mkdir(parents=True, exist_ok=True)
    root = source_root.expanduser().resolve()
    items: list[BatchItem] = []
    skipped: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for row in rows:
        if not row.selected:
            skipped.append({**asdict(row), "reason": row.skip_reason})
            continue
        if not row.sha256:
            skipped.append({**asdict(row), "reason": "missing_hash"})
            continue
        if existing_index and row.sha256 in existing_index.source_hashes:
            skipped.append({**asdict(row), "reason": "already_indexed_sha256"})
            continue
        if existing_index and row.source_relative_path in existing_index.file_sources:
            skipped.append({**asdict(row), "reason": "already_indexed_file_source"})
            continue
        if row.sha256 in seen_hashes:
            skipped.append({**asdict(row), "reason": "duplicate_sha256"})
            continue
        seen_hashes.add(row.sha256)
        path = root / row.source_relative_path
        body = path.read_text(encoding="utf-8", errors="replace")
        document_id = stable_document_id(row)
        text = _payload_text(row, document_id, body)
        items.append(
            BatchItem(
                document_id=document_id,
                source_sha256=row.sha256,
                suite_id=row.suite_id,
                source_relative_path=row.source_relative_path,
                package_id=row.package_id,
                role=row.role,
                text=text,
                rights_status=row.rights_status,
                rights_warnings=row.rights_warnings,
            )
        )
        if limit_items is not None and len(items) >= limit_items:
            break

    batches = build_batches(items, max_batch_chars=max_batch_chars, max_batch_items=max_batch_items)
    _write_jsonl(report_dir / "selected-manifest.jsonl", (_batch_item_manifest(item) for item in items))
    _write_jsonl(report_dir / "skipped-manifest.jsonl", skipped)
    _write_jsonl(report_dir / "batch-manifest.jsonl", (asdict(batch) for batch in batches))
    return items, batches


def build_batches(
    items: Sequence[BatchItem],
    *,
    max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
) -> list[Batch]:
    batches: list[Batch] = []
    current: list[BatchItem] = []
    current_chars = 0
    for item in items:
        item_chars = len(item.text)
        if current and (len(current) >= max_batch_items or current_chars + item_chars > max_batch_chars):
            batches.append(_make_batch(len(batches) + 1, current, current_chars))
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(_make_batch(len(batches) + 1, current, current_chars))
    return batches


def run_ingest(
    items: Sequence[BatchItem],
    batches: Sequence[Batch],
    report_dir: Path,
    *,
    run_id: str,
    base_url: str = DEFAULT_LIGHTRAG_BASE_URL,
    apply: bool = False,
    timeout_s: float = 60.0,
    poll_interval_s: float = 5.0,
    poll_timeout_s: float = 1800.0,
    auto_reprocess_failed_attempts: int = 0,
) -> IngestSummary:
    report_dir.mkdir(parents=True, exist_ok=True)
    client = LightRAGClient(base_url=base_url, timeout_s=timeout_s)
    summary = IngestSummary(
        run_id=run_id,
        dry_run=not apply,
        base_url=base_url,
        batches_total=len(batches),
        items_total=len(items),
        chars_total=sum(len(item.text) for item in items),
    )
    if not apply:
        _write_ingest_summary(report_dir, summary)
        return summary

    try:
        summary.preflight = {
            "health": client.health(),
            "status_counts": client.status_counts(),
            "pipeline_status": client.pipeline_status(),
        }
    except httpx.HTTPError as exc:
        summary.errors.append({"stage": "preflight", "error": public_error(exc)})
        _write_ingest_summary(report_dir, summary)
        return summary

    if summary.preflight.get("pipeline_status", {}).get("busy"):
        summary.errors.append({"stage": "preflight", "error": "pipeline_busy"})
        _write_ingest_summary(report_dir, summary)
        return summary
    if summary.preflight.get("pipeline_status", {}).get("request_pending"):
        summary.errors.append({"stage": "preflight", "error": "pipeline_request_pending"})
        _write_ingest_summary(report_dir, summary)
        return summary
    preflight_all = _all_count(summary.preflight.get("status_counts", {}))
    preflight_failed = _failed_count(summary.preflight.get("status_counts", {}))
    if _active_count(summary.preflight.get("status_counts", {})) > 0:
        summary.errors.append(
            {
                "stage": "preflight",
                "error": "active_documents_present",
                "active_count": _active_count(summary.preflight.get("status_counts", {})),
            }
        )
        _write_ingest_summary(report_dir, summary)
        return summary
    if preflight_failed > 0:
        summary.final_pipeline_status = summary.preflight.get("pipeline_status", {})
        summary.final_status_counts = summary.preflight.get("status_counts", {})
        summary.errors.append(
            {
                "stage": "preflight",
                "error": "failed_documents_present",
                "failed": preflight_failed,
                **_failed_document_diagnostics(client, summary),
            }
        )
        _write_ingest_summary(report_dir, summary)
        return summary

    item_by_id = {item.document_id: item for item in items}
    sent_items = 0
    reprocess_attempts_used = 0
    for batch in batches:
        batch_items = [item_by_id[document_id] for document_id in batch.document_ids]
        try:
            response = client.insert_texts([item.text for item in batch_items], [item.source_relative_path for item in batch_items])
        except httpx.HTTPError as exc:
            summary.errors.append({"stage": "insert", "batch_id": batch.batch_id, "error": public_error(exc)})
            break
        safe_response = sanitize_response(response)
        safe_response["batch_id"] = batch.batch_id
        summary.responses.append(safe_response)
        if str(response.get("status", "")).lower() in {"failure"}:
            summary.errors.append({"stage": "insert", "batch_id": batch.batch_id, "error": response.get("message", "failure")})
            break
        summary.batches_sent += 1
        sent_items += len(batch_items)
        _record_postflight_settlement(
            summary,
            client,
            preflight_all=preflight_all,
            preflight_failed=preflight_failed,
            sent_items=sent_items,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
            batch_id=batch.batch_id,
        )
        if (
            summary.errors
            and summary.errors[-1].get("error") == "new_failed_documents"
            and summary.errors[-1].get("retryable", True)
            and reprocess_attempts_used < auto_reprocess_failed_attempts
        ):
            retry_error = summary.errors.pop()
            reprocess_attempts_used += 1
            try:
                retry_response = client.reprocess_failed_documents()
            except httpx.HTTPError as exc:
                summary.errors.append(
                    {
                        "stage": "reprocess_failed",
                        "batch_id": batch.batch_id,
                        "attempt": reprocess_attempts_used,
                        "previous_error": retry_error,
                        "error": public_error(exc),
                    }
                )
                break
            safe_retry_response = sanitize_response(retry_response)
            safe_retry_response["batch_id"] = batch.batch_id
            safe_retry_response["stage"] = "reprocess_failed"
            safe_retry_response["attempt"] = reprocess_attempts_used
            safe_retry_response["previous_error"] = retry_error
            summary.responses.append(safe_retry_response)
            _record_postflight_settlement(
                summary,
                client,
                preflight_all=preflight_all,
                preflight_failed=preflight_failed,
                sent_items=sent_items,
                poll_interval_s=poll_interval_s,
                poll_timeout_s=poll_timeout_s,
                batch_id=batch.batch_id,
            )
        if summary.errors:
            break

    if summary.batches_sent and (not summary.final_status_counts or _active_count(summary.final_status_counts) > 0):
        _record_postflight_settlement(
            summary,
            client,
            preflight_all=preflight_all,
            preflight_failed=preflight_failed,
            sent_items=sent_items,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=poll_timeout_s,
        )
    _write_ingest_summary(report_dir, summary)
    return summary


def collect_eval_queries(
    source_root: Path,
    *,
    limit: int | None = None,
    include_sentinels: bool = True,
    queries_per_card: int = 1,
    craft_only: bool = True,
) -> list[EvalQuery]:
    """Build a corpus-grounded eval set.

    Queries are harvested from the corpus ``retrieval_eval*.md`` cards (their
    authored ``## Eval queries`` / ``## Queries`` sections) so the rubric is
    anchored in the corpus instead of hand-invented terms. Cards are sampled in
    a deterministic, suite-stratified round-robin so a bounded ``limit`` still
    spreads coverage across every suite rather than alphabetically clustering.

    When ``craft_only`` is True (default) the set is restricted to questions a
    practitioner would actually ask. Eval-infrastructure cards (the
    ``04_retrieval_eval_suite`` packages and ``*_eval_pack`` packages, whose
    subject is the retrieval/eval scaffolding rather than cinema craft) are
    skipped, and meta-graph queries ("What does X add to the LightRAG graph?")
    are dropped in favour of the same card's craft questions. This measures
    craft-retrieval quality instead of questions about the index's own
    structure. The filter is structural/semantic (package path + query text)
    and score-blind: it removes meta queries regardless of how they scored. Pass
    ``craft_only=False`` to reproduce the legacy, uncalibrated set.
    """
    root = source_root.expanduser().resolve()
    cards_by_suite: dict[str, list[tuple[Path, str]]] = {}
    for path in root.rglob("retrieval_eval*.md"):
        if _path_has_skipped_part(path):
            continue
        rel = path.relative_to(root).as_posix()
        if craft_only and _is_eval_infra_card(rel):
            continue
        suite = rel.split("/", 1)[0]
        cards_by_suite.setdefault(suite, []).append((path, rel))
    # Deterministic order within each suite (stable across runs, no RNG).
    for suite in cards_by_suite:
        cards_by_suite[suite].sort(key=lambda pr: hashlib.sha1(pr[1].encode("utf-8")).hexdigest())

    queries: list[EvalQuery] = list(_sentinel_queries()) if include_sentinels else []
    for path, rel in _round_robin_cards(cards_by_suite):
        text = path.read_text(encoding="utf-8", errors="replace")
        fragment = path.parent.name
        card_queries = _parse_eval_card(text, rel, fragment)
        if craft_only:
            card_queries = [query for query in card_queries if not _is_meta_query(query.query)]
        queries.extend(card_queries[:queries_per_card])

    deduped: list[EvalQuery] = []
    seen: set[str] = set()
    for query in queries:
        key = query.query.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _round_robin_cards(cards_by_suite: dict[str, list[tuple[Path, str]]]) -> list[tuple[Path, str]]:
    ordered: list[tuple[Path, str]] = []
    suites = sorted(cards_by_suite)
    index = 0
    remaining = True
    while remaining:
        remaining = False
        for suite in suites:
            bucket = cards_by_suite[suite]
            if index < len(bucket):
                ordered.append(bucket[index])
                remaining = True
        index += 1
    return ordered


# Eval-infrastructure packages describe the retrieval/eval scaffolding itself
# (how to evaluate, which packs to "retrieve by") rather than cinema craft.
# Their eval cards ask meta questions a director would never pose, so the craft
# gate skips them. Detected structurally by package location, not title text.
EVAL_INFRA_PATH_TOKENS = ("/04_retrieval_eval_suite/",)
EVAL_INFRA_PACKAGE_SUFFIX = "_eval_pack"

# Meta queries about index membership ("What does X add to the LightRAG graph?")
# are a poor proxy for craft usefulness; the craft gate drops them in favour of
# the same card's craft questions.
META_QUERY_PATTERNS = (re.compile(r"add to the\b.*\bgraph", re.IGNORECASE),)


def _is_eval_infra_card(relative_path: str) -> bool:
    """True for cards whose package is eval/retrieval scaffolding, not craft."""
    lowered = relative_path.lower()
    if any(token in lowered for token in EVAL_INFRA_PATH_TOKENS):
        return True
    return any(part.endswith(EVAL_INFRA_PACKAGE_SUFFIX) for part in lowered.split("/"))


def _is_meta_query(query: str) -> bool:
    """True for meta-graph queries about index membership rather than craft."""
    return any(pattern.search(query) for pattern in META_QUERY_PATTERNS)


def run_eval(
    queries: Sequence[EvalQuery],
    report_dir: Path,
    *,
    base_url: str = DEFAULT_LIGHTRAG_BASE_URL,
    threshold: float = DEFAULT_EVAL_THRESHOLD,
    timeout_s: float = 120.0,
    judge: Judge | None = None,
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    client = LightRAGClient(base_url=base_url, timeout_s=timeout_s)
    results: list[EvalResult] = []
    for query in queries:
        start = time.monotonic()
        try:
            payload = client.query(
                query.query,
                mode=query.mode,
                include_references=True,
                include_chunk_content=True,
                only_need_context=False,
            )
            latency = time.monotonic() - start
            results.append(score_eval_response(query, payload, latency_s=latency, judge=judge))
        except httpx.HTTPError as exc:
            latency = time.monotonic() - start
            results.append(
                EvalResult(
                    query=query.query,
                    score=0.0,
                    usable=False,
                    matched_terms=[],
                    expected_terms=query.expected_terms,
                    reference_count=0,
                    latency_s=latency,
                    source=query.source,
                    error=public_error(exc),
                )
            )
    aggregate = sum(result.score for result in results) / max(1, len(results))
    usable_count = sum(1 for result in results if result.usable)
    report = {
        "threshold": threshold,
        "aggregate_score": round(aggregate, 4),
        "usable_count": usable_count,
        "query_count": len(results),
        "judge_used": judge is not None,
        "rights_unsafe_count": sum(1 for result in results if not result.rights_safe),
        "mean_judge_score": round(_mean(r.judge_score for r in results), 4),
        "mean_retrieval_precision": round(_mean(r.retrieval_precision for r in results), 4),
        "mean_sanity_score": round(_mean(r.sanity_score for r in results), 4),
        "ok": aggregate >= threshold and usable_count > 0,
        "results": [asdict(result) for result in results],
    }
    (report_dir / "eval-report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (report_dir / "eval-report.md").write_text(_eval_markdown(report), encoding="utf-8")
    return report


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return sum(collected) / max(1, len(collected))


# Blend weights for the hardened rubric. Semantic judgement dominates, with
# deterministic retrieval precision and response sanity as objective anchors.
JUDGE_WEIGHT = 0.5
PRECISION_WEIGHT = 0.35
SANITY_WEIGHT = 0.15
RIGHTS_PENALTY = 0.35


def score_eval_response(
    query: EvalQuery,
    payload: dict[str, Any],
    *,
    latency_s: float,
    judge: Judge | None = None,
) -> EvalResult:
    response = str(payload.get("response") or "")
    references = payload.get("references") if isinstance(payload.get("references"), list) else []
    ref_paths: list[str] = []
    content_parts: list[str] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        ref_paths.append(str(ref.get("file_path") or ""))
        content = ref.get("content")
        if isinstance(content, list):
            content_parts.extend(str(item) for item in content[:3])
    haystack = "\n".join([response, *ref_paths, *content_parts]).lower()

    expected = [term for term in query.expected_terms if term]
    matched = [term for term in expected if term.lower() in haystack]
    term_score = len(matched) / max(1, len(expected)) if expected else 0.0

    precision = _retrieval_precision(query, ref_paths, term_score)
    sanity = _sanity_score(response, references, haystack)

    if judge is not None:
        try:
            verdict = judge(query, response)
        except Exception as exc:  # judge transport failures must not crash the run
            verdict = JudgeVerdict(score=0.0, rights_safe=True, reason=f"judge_error: {public_error(exc)}")
    else:
        verdict = JudgeVerdict(
            score=term_score,
            rights_safe=_deterministic_rights_safe(haystack),
            reason="deterministic",
        )

    rights_penalty = 0.0 if verdict.rights_safe else RIGHTS_PENALTY
    score = max(
        0.0,
        min(
            1.0,
            verdict.score * JUDGE_WEIGHT
            + precision * PRECISION_WEIGHT
            + sanity * SANITY_WEIGHT
            - rights_penalty,
        ),
    )
    return EvalResult(
        query=query.query,
        score=round(score, 4),
        usable=score >= DEFAULT_EVAL_THRESHOLD,
        matched_terms=matched,
        expected_terms=expected,
        reference_count=len(references),
        latency_s=round(latency_s, 3),
        judge_score=round(verdict.score, 4),
        retrieval_precision=round(precision, 4),
        sanity_score=round(sanity, 4),
        rights_safe=verdict.rights_safe,
        judge_reason=verdict.reason[:500],
        source=query.source,
    )


def _retrieval_precision(query: EvalQuery, ref_paths: Sequence[str], term_fallback: float) -> float:
    """Did retrieval surface the intended unit? Deterministic, no LLM."""
    joined = "\n".join(ref_paths).lower()
    fragment = (query.expected_path_fragment or "").lower()
    if fragment:
        if fragment in joined:
            return 1.0
        if query.domain:
            tokens = [tok for tok in re.split(r"[^a-z0-9]+", query.domain.lower()) if len(tok) >= 4]
            if any(tok in joined for tok in tokens):
                return 0.5
        return 0.0
    # Sentinel queries carry no package fragment; fall back to term coverage.
    return term_fallback


def _sanity_score(response: str, references: Sequence[Any], haystack: str) -> float:
    reference_score = 0.5 if references else 0.0
    response_score = 0.5 if len(response.strip()) >= 40 else 0.0
    noise = 0.5 if any(pattern in haystack for pattern in NOISY_RESPONSE_PATTERNS) else 0.0
    return max(0.0, reference_score + response_score - noise)


def _deterministic_rights_safe(haystack: str) -> bool:
    warnings = _rights_warnings(haystack)
    if not warnings:
        return True
    return _rights_status(haystack, warnings) != "manual_review"


class LightRAGClient:
    def __init__(self, *, base_url: str = DEFAULT_LIGHTRAG_BASE_URL, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def status_counts(self) -> dict[str, Any]:
        return self._get("/documents/status_counts")

    def pipeline_status(self) -> dict[str, Any]:
        return self._get("/documents/pipeline_status")

    def paginated_documents(self, *, page: int, page_size: int = 200, status_filter: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort_field": "updated_at",
            "sort_direction": "desc",
        }
        if status_filter:
            payload["status_filter"] = status_filter
        return self._post("/documents/paginated", payload)

    def insert_texts(self, texts: list[str], file_sources: list[str]) -> dict[str, Any]:
        return self._post("/documents/texts", {"texts": texts, "file_sources": file_sources})

    def reprocess_failed_documents(self) -> dict[str, Any]:
        return self._post("/documents/reprocess_failed", {})

    def failed_documents(self, *, limit: int = FAILED_DOCUMENT_SNAPSHOT_LIMIT, page_size: int = 50) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        page = 1
        while len(documents) < limit:
            payload = self.paginated_documents(page=page, page_size=page_size, status_filter="failed")
            page_documents = payload.get("documents") if isinstance(payload.get("documents"), list) else []
            for document in page_documents:
                if isinstance(document, dict):
                    documents.append(document)
                    if len(documents) >= limit:
                        break
            pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
            if not pagination.get("has_next") or not page_documents:
                break
            page += 1
        return documents

    def query(self, query: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"query": query, **kwargs}
        return self._post("/query", payload)

    def wait_until_idle(self, *, interval_s: float, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status = self.pipeline_status()
            if not status.get("busy") and not status.get("request_pending"):
                return status
            time.sleep(interval_s)
        return status or {"busy": True, "latest_message": "pipeline_timeout"}

    def wait_until_settled(
        self,
        *,
        interval_s: float,
        timeout_s: float,
        min_total_count: int | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        status: dict[str, Any] = {}
        counts_payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status = self.pipeline_status()
            counts_payload = self.status_counts()
            settled_status = _settle_status(status, counts_payload, min_total_count=min_total_count, timed_out=False)
            if settled_status.get("settled"):
                return settled_status
            time.sleep(interval_s)
        return _settle_status(status, counts_payload, min_total_count=min_total_count, timed_out=True)

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str) -> dict[str, Any]:
        response = self.client.get(path)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}


def _record_postflight_settlement(
    summary: IngestSummary,
    client: LightRAGClient,
    *,
    preflight_all: int,
    preflight_failed: int,
    sent_items: int,
    poll_interval_s: float,
    poll_timeout_s: float,
    batch_id: str | None = None,
) -> None:
    expected_total = preflight_all + sent_items
    error_context = {"stage": "postflight"}
    if batch_id:
        error_context["batch_id"] = batch_id
    try:
        summary.final_pipeline_status = client.wait_until_settled(
            interval_s=poll_interval_s,
            timeout_s=poll_timeout_s,
            min_total_count=expected_total,
        )
        summary.final_status_counts = client.status_counts()
    except httpx.HTTPError as exc:
        summary.errors.append({**error_context, "error": public_error(exc)})
        return

    if summary.final_pipeline_status.get("timed_out") or summary.final_pipeline_status.get("settled") is False:
        summary.errors.append(
            {
                **error_context,
                "error": "pipeline_settle_timeout",
                "active_count": summary.final_pipeline_status.get("active_count"),
                "total_count": summary.final_pipeline_status.get("total_count"),
                "min_total_count": summary.final_pipeline_status.get("min_total_count"),
                "request_pending": summary.final_pipeline_status.get("request_pending"),
            }
        )
        return

    final_active = _active_count(summary.final_status_counts)
    if final_active > 0:
        summary.errors.append({**error_context, "error": "documents_still_active", "active_count": final_active})
        return

    final_total = _all_count(summary.final_status_counts)
    if final_total < expected_total:
        summary.errors.append(
            {
                **error_context,
                "error": "documents_not_materialized",
                "final_total": final_total,
                "expected_total": expected_total,
            }
        )
        return

    final_failed = _failed_count(summary.final_status_counts)
    if final_failed > preflight_failed:
        failure = {
            **error_context,
            "error": "new_failed_documents",
            "preflight_failed": preflight_failed,
            "final_failed": final_failed,
        }
        failure.update(_failed_document_diagnostics(client, summary))
        summary.errors.append(failure)


def _settle_status(
    status: dict[str, Any],
    counts_payload: dict[str, Any],
    *,
    min_total_count: int | None,
    timed_out: bool,
) -> dict[str, Any]:
    total = _all_count(counts_payload)
    active = _active_count(counts_payload)
    total_ready = min_total_count is None or total >= min_total_count
    request_pending = bool(status.get("request_pending"))
    busy = bool(status.get("busy"))
    settled = total_ready and not busy and not request_pending and active == 0
    return {
        **status,
        "settled": settled,
        "timed_out": bool(timed_out and not settled),
        "active_count": active,
        "total_count": total,
        "min_total_count": min_total_count,
        "total_ready": total_ready,
    }


def fetch_existing_document_index(client: LightRAGClient, *, page_size: int = 200) -> ExistingDocumentIndex:
    source_hashes: set[str] = set()
    file_sources: set[str] = set()
    document_ids: set[str] = set()
    page = 1
    while True:
        payload = client.paginated_documents(page=page, page_size=page_size)
        documents = payload.get("documents") if isinstance(payload.get("documents"), list) else []
        for document in documents:
            if not isinstance(document, dict):
                continue
            doc_id = str(document.get("id") or "").strip()
            file_path = str(document.get("file_path") or "").strip()
            summary = str(document.get("content_summary") or "")
            metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
            if doc_id:
                document_ids.add(doc_id)
            if file_path:
                file_sources.add(file_path)
            source_hashes.update(_extract_source_hashes(summary))
            for value in metadata.values():
                if isinstance(value, str):
                    source_hashes.update(_extract_source_hashes(value))
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        if not pagination.get("has_next"):
            break
        page += 1
    return ExistingDocumentIndex(source_hashes=source_hashes, file_sources=file_sources, document_ids=document_ids)


def _failed_document_diagnostics(client: LightRAGClient, summary: IngestSummary) -> dict[str, Any]:
    try:
        failed_documents = client.failed_documents(limit=FAILED_DOCUMENT_SNAPSHOT_LIMIT)
    except httpx.HTTPError as exc:
        error_class = _classify_failed_texts(_pipeline_history_messages(summary.final_pipeline_status))
        return {
            "failed_error_class": error_class,
            "failed_document_snapshot_error": public_error(exc),
            "retryable": error_class not in {"provider_insufficient_balance"},
        }

    error_class = _classify_failed_documents(failed_documents)
    if error_class == "unknown":
        error_class = _classify_failed_texts(_pipeline_history_messages(summary.final_pipeline_status))
    return {
        "failed_error_class": error_class,
        "failed_document_sample": [_public_failed_document(document) for document in failed_documents[:FAILED_DOCUMENT_SNAPSHOT_LIMIT]],
        "retryable": error_class not in {"provider_insufficient_balance"},
    }


def _classify_failed_documents(documents: Sequence[dict[str, Any]]) -> str:
    return _classify_failed_texts(_failed_document_error_text(document) for document in documents)


def _classify_failed_texts(texts: Iterable[str]) -> str:
    haystack = "\n".join(text for text in texts if text).lower()
    if any(pattern in haystack for pattern in NON_RETRYABLE_FAILED_PATTERNS):
        return "provider_insufficient_balance"
    return "unknown"


def _pipeline_history_messages(payload: dict[str, Any]) -> list[str]:
    messages = payload.get("history_messages")
    if not isinstance(messages, list):
        return []
    return [str(message) for message in messages if message]


def _failed_document_error_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("error", "error_msg", "message", "status_message", "content_summary"):
        value = document.get(key)
        if isinstance(value, str):
            parts.append(value)
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        for value in metadata.values():
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def _public_failed_document(document: dict[str, Any]) -> dict[str, str]:
    raw_path = str(document.get("file_path") or document.get("source") or "").strip()
    return {
        "document_id": _public_text(document.get("id") or document.get("document_id") or "", limit=96),
        "file_path": _public_text(raw_path, limit=180),
        "error_class": _classify_failed_texts([_failed_document_error_text(document)]),
        "error": _public_text(_failed_document_error_text(document), limit=240),
    }


def inventory_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory LightRAG cinema craft source suites.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--include-agent-prompts", action="store_true")
    args = parser.parse_args(argv)
    report_dir = args.report_dir or default_report_dir(args.run_id)
    rows = inventory_source(args.source_root, include_agent_prompts=args.include_agent_prompts)
    summary = write_inventory_reports(rows, report_dir)
    print(json.dumps({"run_id": args.run_id, "report_dir": str(report_dir), "inventory": summary}, indent=2, sort_keys=True))
    return 0


def prepare_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare LightRAG cinema craft ingest batches.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--max-batch-chars", type=int, default=DEFAULT_MAX_BATCH_CHARS)
    parser.add_argument("--max-batch-items", type=int, default=DEFAULT_MAX_BATCH_ITEMS)
    parser.add_argument("--limit-items", type=int)
    parser.add_argument("--base-url", default=DEFAULT_LIGHTRAG_BASE_URL)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--include-agent-prompts", action="store_true")
    args = parser.parse_args(argv)
    report_dir = args.report_dir or default_report_dir(args.run_id)
    rows = inventory_source(args.source_root, include_agent_prompts=args.include_agent_prompts)
    write_inventory_reports(rows, report_dir)
    existing_index = None
    if args.skip_existing:
        client = LightRAGClient(base_url=args.base_url)
        existing_index = fetch_existing_document_index(client)
        client.close()
        _write_existing_index_summary(existing_index, report_dir)
    items, batches = prepare_batches(
        args.source_root,
        rows,
        report_dir,
        max_batch_chars=args.max_batch_chars,
        max_batch_items=args.max_batch_items,
        limit_items=args.limit_items,
        existing_index=existing_index,
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "report_dir": str(report_dir),
                "selected_items": len(items),
                "batches": len(batches),
                "chars": sum(len(item.text) for item in items),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def ingest_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run guarded LightRAG cinema craft ingest.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_LIGHTRAG_BASE_URL)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-batch-chars", type=int, default=DEFAULT_MAX_BATCH_CHARS)
    parser.add_argument("--max-batch-items", type=int, default=DEFAULT_MAX_BATCH_ITEMS)
    parser.add_argument("--limit-items", type=int)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--only-suite", default=None, help="Comma-separated suite id tokens to restrict ingest to.")
    parser.add_argument("--poll-timeout-s", type=float, default=1800.0)
    parser.add_argument("--poll-interval-s", type=float, default=5.0)
    parser.add_argument("--auto-reprocess-failed-attempts", type=int, default=0)
    parser.add_argument("--include-agent-prompts", action="store_true")
    args = parser.parse_args(argv)
    report_dir = args.report_dir or default_report_dir(args.run_id)
    rows = inventory_source(args.source_root, include_agent_prompts=args.include_agent_prompts)
    write_inventory_reports(rows, report_dir)
    rows = filter_rows_by_suite(rows, args.only_suite)
    existing_index = None
    if args.skip_existing:
        client = LightRAGClient(base_url=args.base_url)
        existing_index = fetch_existing_document_index(client)
        client.close()
        _write_existing_index_summary(existing_index, report_dir)
    items, batches = prepare_batches(
        args.source_root,
        rows,
        report_dir,
        max_batch_chars=args.max_batch_chars,
        max_batch_items=args.max_batch_items,
        limit_items=args.limit_items,
        existing_index=existing_index,
    )
    summary = run_ingest(
        items,
        batches,
        report_dir,
        run_id=args.run_id,
        base_url=args.base_url,
        apply=args.apply,
        poll_timeout_s=args.poll_timeout_s,
        poll_interval_s=args.poll_interval_s,
        auto_reprocess_failed_attempts=max(0, args.auto_reprocess_failed_attempts),
    )
    print(json.dumps({**asdict(summary), "ok": summary.ok}, indent=2, sort_keys=True))
    return 0 if summary.ok else 1


def eval_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LightRAG cinema craft retrieval eval.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--run-id", default=build_run_id())
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_LIGHTRAG_BASE_URL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--threshold", type=float, default=DEFAULT_EVAL_THRESHOLD)
    parser.add_argument(
        "--judge-provider",
        choices=["claude", "gemini", "deepseek", "codex", "none"],
        default="claude",
        help="LLM judge backend (default: claude OAuth, independent of the synthesis model).",
    )
    parser.add_argument("--judge-model", default=None)
    parser.add_argument(
        "--queries-per-card",
        type=int,
        default=1,
        help="How many queries to sample from each corpus eval card.",
    )
    parser.add_argument(
        "--include-meta-queries",
        action="store_true",
        help=(
            "Include eval-infrastructure cards and meta-graph queries "
            "(legacy uncalibrated set; default excludes them for a craft-only gate)."
        ),
    )
    args = parser.parse_args(argv)
    report_dir = args.report_dir or default_report_dir(args.run_id)
    queries = collect_eval_queries(
        args.source_root,
        limit=args.limit,
        queries_per_card=args.queries_per_card,
        craft_only=not args.include_meta_queries,
    )
    judge = None if args.judge_provider == "none" else make_llm_judge(args.judge_provider, model=args.judge_model)
    report = run_eval(queries, report_dir, base_url=args.base_url, threshold=args.threshold, judge=judge)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


def _find_suite_roots(root: Path) -> list[Path]:
    roots: list[Path] = []
    for manifest in root.rglob("_manifest.json"):
        if _path_has_skipped_part(manifest):
            continue
        roots.append(manifest.parent)
    return sorted(set(roots))


def _load_package_metadata(suite_roots: Sequence[Path]) -> dict[tuple[str, str], dict[str, Any]]:
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    for suite_root in suite_roots:
        suite_id = suite_root.name
        registries = list(suite_root.glob("package_registry.json")) + list(suite_root.glob("registry/package_registry.json"))
        for registry in registries:
            try:
                data = json.loads(registry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                relative_path = str(item.get("relative_path") or item.get("package_id") or "").strip()
                package_id = str(item.get("package_id") or item.get("slug") or relative_path).strip()
                if relative_path:
                    metadata[(suite_id, relative_path)] = item
                if package_id:
                    metadata[(suite_id, package_id)] = item
    return metadata


def _inventory_file(
    root: Path,
    path: Path,
    *,
    package_meta: dict[tuple[str, str], dict[str, Any]],
    max_file_chars: int,
    include_agent_prompts: bool,
) -> InventoryRow:
    rel = path.relative_to(root).as_posix()
    parts = rel.split("/")
    suite_id = parts[0] if parts else "."
    suite_rel = "/".join(parts[1:]) if len(parts) > 1 else path.name
    suffix = path.suffix.lower()
    package_id = _package_id_from_relative(parts)
    role = classify_role(rel)
    metadata = _metadata_for(package_meta, suite_id, parts, package_id)
    domain = _optional_text(metadata.get("domain") or metadata.get("block"))
    priority = _optional_text(metadata.get("priority") or metadata.get("ingestion_priority"))
    skip_reason: str | None = None
    sha: str | None = None
    chars = 0
    rights_warnings: list[str] = []
    rights_status = "clear"

    if path.name in SKIP_FILE_NAMES or path.name.startswith("."):
        skip_reason = "hidden_or_system_file"
    elif _path_has_skipped_part(path):
        skip_reason = "quarantine_path"
    elif suffix in MEDIA_SUFFIXES:
        skip_reason = "media_or_protected_binary"
    elif suffix != MARKDOWN_SUFFIX:
        skip_reason = "non_markdown"
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        chars = len(text)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rights_warnings = _rights_warnings(text)
        rights_status = _rights_status(text, rights_warnings)
        if chars <= 0:
            skip_reason = "empty_file"
        elif rights_status == "manual_review":
            skip_reason = "rights_warning_manual_review"
        elif chars > max_file_chars:
            skip_reason = "oversized_file"
        elif role in CONTROL_PLANE_ROLES and chars > DEFAULT_MAX_CONTROL_FILE_CHARS:
            skip_reason = "oversized_control_plane_file"
        elif role == "agent_prompt" and not include_agent_prompts:
            skip_reason = "agent_prompt_skipped"
        elif role in DEFAULT_SKIP_ROLES:
            skip_reason = f"role_skipped:{role}"

    selected = skip_reason is None
    return InventoryRow(
        suite_id=suite_id,
        source_relative_path=rel,
        suite_relative_path=suite_rel,
        package_id=package_id,
        domain=domain,
        priority=priority,
        role=role,
        suffix=suffix,
        bytes=path.stat().st_size,
        chars=chars,
        sha256=sha,
        selected=selected,
        skip_reason=skip_reason,
        rights_warnings=rights_warnings,
        rights_status=rights_status,
    )


def classify_role(relative_path: str) -> str:
    path = relative_path.lower()
    name = path.rsplit("/", 1)[-1]
    if "/quarantine/" in f"/{path}/":
        return "quarantine"
    if name in {"readme.md", "index.md", "_manifest.md", "00_start_here.md"}:
        return "root_or_package_metadata"
    if name == "source_and_provenance.md":
        return "source_provenance"
    if "rights" in name:
        return "rights_posture"
    if "/concept_cards/" in path:
        return "concept_card"
    if "/craft_translation_cards/" in path:
        return "craft_translation"
    if "/relation_cards/" in path or name == "entity_relation_schema.md":
        return "relation_card"
    if name in {"graph_hints.md", "entity_relation_map.md"}:
        return "graph_hint"
    if "retrieval_eval" in name or "/04_retrieval_eval_suite/" in path:
        return "eval_card"
    if name in {"ingestion_card.md", "metadata_card.md", "chunking_plan.md", "crosswalks.md", "crosswalk_by_task.md", "crosswalk_by_domain.md"}:
        return "ingestion_metadata"
    if name in {"canon_depth_map.md", "round_02_strategy.md", "round_03_strategy.md", "round_04_case_mechanics_strategy.md", "bridge_pack_strategy.md"}:
        return "strategy_or_map"
    if name == "agent_prompts.md":
        return "agent_prompt"
    if name == "package_stats.md":
        return "package_stats"
    return "unknown"


def stable_document_id(row: InventoryRow) -> str:
    digest = hashlib.sha256(row.source_relative_path.encode("utf-8")).hexdigest()[:16]
    stem = re.sub(r"[^a-z0-9]+", "-", Path(row.source_relative_path).stem.lower()).strip("-")[:48]
    return f"lcc-{row.suite_id}-{stem}-{digest}"


def _payload_text(row: InventoryRow, document_id: str, body: str) -> str:
    header = [
        "---",
        f"lightrag_ingest_document_id: {document_id}",
        f"suite_id: {row.suite_id}",
        f"source_relative_path: {row.source_relative_path}",
        f"source_sha256: {row.sha256}",
        f"content_role: {row.role}",
        f"package_id: {row.package_id or ''}",
        f"domain: {row.domain or ''}",
        f"priority: {row.priority or ''}",
        "rights_posture: rights-safe metadata and paraphrased concept card",
        "---",
        "",
    ]
    return "\n".join(header) + body


def _sentinel_queries() -> Iterable[EvalQuery]:
    yield EvalQuery(
        query="Which canon concept helps me make an overexplained scene more ambiguous without making it confusing?",
        expected_terms=["bazin", "ambiguity", "bridge", "rights"],
        source="sentinel:canon_to_repair",
    )
    yield EvalQuery(
        query="How do I translate a photography reference into lighting, blocking, and AI prompt constraints without copying it?",
        expected_terms=["photography", "lighting", "prompt", "rights"],
        source="sentinel:photography_translation",
    )
    yield EvalQuery(
        query="Give me a rights-safe case mechanism for turning a product demo into mythic spectacle.",
        expected_terms=["advertising", "product", "myth", "rights"],
        source="sentinel:advertising_case",
    )
    yield EvalQuery(
        query="How can set design make class or power legible without explanatory dialogue?",
        expected_terms=["architecture", "class", "production design", "power"],
        source="sentinel:production_design",
    )
    yield EvalQuery(
        query="Which canon and Black Label routes help translate Brazilian political excess into modern commercial or documentary form?",
        expected_terms=["brazilian", "cinema novo", "bridge", "commercial"],
        source="sentinel:brazilian_context",
    )


def _parse_markdown_eval_queries(text: str, source: str) -> list[EvalQuery]:
    queries: list[EvalQuery] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in {"type", "query"}:
            continue
        query_text = cells[1] if len(cells) >= 3 else cells[0]
        if len(query_text) < 12 or "?" not in query_text:
            continue
        expected = _expected_terms_from_text(" ".join(cells[2:]))
        queries.append(EvalQuery(query=query_text, expected_terms=expected, source=source))
    return queries


def _expected_terms_from_text(text: str) -> list[str]:
    terms = []
    for candidate in re.split(r"[,+/]| and |\+|;", text.lower()):
        candidate = re.sub(r"[^a-z0-9 _-]+", "", candidate).strip()
        if len(candidate) >= 4 and candidate not in {"expected", "retrieval", "source"}:
            terms.append(candidate)
    return terms[:6] or ["rights", "package"]


def _parse_eval_card(text: str, source: str, fragment: str) -> list[EvalQuery]:
    """Parse a corpus ``retrieval_eval*.md`` card into eval queries.

    Handles the dominant authored format (``## Eval queries`` numbered list plus
    ``## Expected retrieval pattern`` / ``## Expected answer qualities`` bullets)
    and falls back to the legacy pipe-table format for older cards.
    """
    front = _parse_frontmatter(text)
    domain = front.get("domain")
    rights_mode = front.get("rights_mode") or front.get("rights_posture") or front.get("rights_status")
    qualities = _bullet_items(_extract_section(text, ("expected retrieval pattern", "expected answer qualities")))
    numbered = _numbered_items(_extract_section(text, ("eval queries", "queries")))

    if numbered:
        return [
            EvalQuery(
                query=question,
                expected_terms=_card_terms(domain, fragment),
                source=source,
                expected_qualities=qualities,
                expected_path_fragment=fragment,
                domain=domain,
                rights_mode=rights_mode,
            )
            for question in numbered
        ]

    # Legacy pipe-table cards: keep their parsed expected terms, enrich context.
    return [
        replace(
            query,
            expected_qualities=qualities,
            expected_path_fragment=fragment,
            domain=domain,
            rights_mode=rights_mode,
        )
        for query in _parse_markdown_eval_queries(text, source)
    ]


def _card_terms(domain: str | None, fragment: str) -> list[str]:
    """Light deterministic terms for the offline (no-judge) fallback path."""
    terms = _expected_terms_from_text(domain or "") if domain else []
    if not terms:
        terms = [tok for tok in re.split(r"[^a-z0-9]+", fragment.lower()) if len(tok) >= 4][:4]
    return terms or ["rights"]


def _parse_frontmatter(text: str) -> dict[str, str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}
    body = stripped[3:]
    end = body.find("\n---")
    if end == -1:
        return {}
    front: dict[str, str] = {}
    for line in body[:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key and value and not value.startswith("["):
            front[key] = value
    return front


def _extract_section(text: str, header_names: Sequence[str]) -> str:
    lines = text.splitlines()
    wanted = {name.lower() for name in header_names}
    capture = False
    out: list[str] = []
    for line in lines:
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            if capture:
                break
            if title in wanted:
                capture = True
            continue
        if capture:
            out.append(line)
    return "\n".join(out)


def _numbered_items(block: str) -> list[str]:
    items: list[str] = []
    for line in block.splitlines():
        match = re.match(r"\s*\d+\.\s+(.*\S)", line)
        if not match:
            continue
        question = match.group(1).strip()
        if len(question) >= 12 and "?" in question:
            items.append(question)
    return items


def _bullet_items(block: str) -> list[str]:
    items: list[str] = []
    for line in block.splitlines():
        match = re.match(r"\s*[-*]\s+(.*\S)", line)
        if match:
            items.append(match.group(1).strip())
    return items


JUDGE_SYSTEM_PROMPT = (
    "You are a strict, fair retrieval-quality judge for a cinema-craft knowledge graph. "
    "You score how well a candidate answer satisfies the authored expectations for a query. "
    "Judge meaning and craft usefulness, not keyword overlap. Reward concrete, on-topic, "
    "rights-safe guidance grounded in the retrieved material; penalise vague, off-topic, or "
    "imitation-encouraging answers. Respond with a single JSON object only."
)


def make_llm_judge(provider: str = "claude", *, model: str | None = None, timeout_s: float = 900.0) -> Judge:
    """Build an independent LLM judge backed by one of the backend chat clients.

    Default is Claude OAuth: independent from the DeepSeek model LightRAG uses to
    synthesise answers (so the judge is not grading its own model) and requires no
    API key (it rides the local Claude subscription session).
    """
    chat = _build_judge_chat(provider, model=model, timeout_s=timeout_s)

    def judge(query: EvalQuery, response: str) -> JudgeVerdict:
        prompt = _render_judge_prompt(query, response)
        raw = chat.complete_chat(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        return _parse_judge_verdict(raw)

    return judge


def _env_value(key: str) -> str | None:
    """Read an env var, falling back to backend/.env (values are never logged)."""
    value = os.environ.get(key)
    if value:
        return value
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def _build_judge_chat(provider: str, *, model: str | None, timeout_s: float) -> Any:
    provider = provider.lower()
    if provider == "claude":
        from .providers import ClaudeOAuthChatClient

        return ClaudeOAuthChatClient(model=model or "claude-sonnet-4-6", timeout_s=timeout_s)
    if provider == "codex":
        from .providers import CodexOAuthChatClient

        return CodexOAuthChatClient(model=model or "gpt-5.5", timeout_s=timeout_s)
    if provider == "gemini":
        from .providers import GeminiChatClient

        api_key = _env_value("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for the gemini judge provider.")
        return GeminiChatClient(
            api_key=api_key,
            model=model or _env_value("GEMINI_CHAT_MODEL") or "gemini-3-flash-preview",
            timeout_s=timeout_s,
        )
    if provider == "deepseek":
        from .providers import DeepSeekChatClient

        api_key = _env_value("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for the deepseek judge provider.")
        return DeepSeekChatClient(
            api_key=api_key,
            model=model or _env_value("DEEPSEEK_MODEL") or "deepseek-v4-pro",
            base_url=_env_value("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
            timeout_s=timeout_s,
        )
    raise ValueError(f"Unknown judge provider: {provider!r}")


def _render_judge_prompt(query: EvalQuery, response: str) -> str:
    qualities = query.expected_qualities or [
        f"Directly and concretely answers: {query.query}",
        "Stays rights-safe and avoids imitation or fabricated quotes.",
    ]
    quality_block = "\n".join(f"- {item}" for item in qualities)
    return (
        f"QUERY:\n{query.query}\n\n"
        f"DOMAIN: {query.domain or 'unspecified'}\n"
        f"RIGHTS MODE: {query.rights_mode or 'unspecified'}\n\n"
        f"A STRONG ANSWER SHOULD SATISFY:\n{quality_block}\n\n"
        f"CANDIDATE ANSWER:\n{response.strip() or '(empty)'}\n\n"
        "Score from 0.0 (useless/off-topic) to 1.0 (fully satisfies the expectations) and decide "
        "whether the answer stays rights-safe (no imitation advice, fabricated quotes, or copyrighted "
        "reproduction). Return ONLY a JSON object: "
        '{"score": <float 0..1>, "rights_safe": <true|false>, "reason": "<one sentence>"}'
    )


def _parse_judge_verdict(raw: str) -> JudgeVerdict:
    text = (raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            score = float(data.get("score"))
            return JudgeVerdict(
                score=max(0.0, min(1.0, score)),
                rights_safe=bool(data.get("rights_safe", True)),
                reason=str(data.get("reason", "")).strip(),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    score_match = re.search(r"score\D+([01](?:\.\d+)?)", text, re.IGNORECASE)
    score = max(0.0, min(1.0, float(score_match.group(1)))) if score_match else 0.0
    rights_safe = not re.search(r"rights[_ ]safe\W+(false|no)\b", text, re.IGNORECASE)
    return JudgeVerdict(score=score, rights_safe=rights_safe, reason="parsed_fallback")


def _rights_warnings(text: str) -> list[str]:
    lowered = text.lower()
    return [pattern for pattern in RIGHTS_WARNING_PATTERNS if pattern in lowered]


def _rights_status(text: str, warnings: Sequence[str]) -> str:
    if not warnings:
        return "clear"
    lowered = text.lower()
    if any(pattern in lowered for pattern in RIGHTS_SAFE_CONTEXT_PATTERNS):
        return "warning_safe_context"
    return "manual_review"


def _path_has_skipped_part(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES or part.startswith(".") for part in path.parts)


def _package_id_from_relative(parts: list[str]) -> str | None:
    if "packages" not in parts:
        return None
    index = parts.index("packages")
    remaining = parts[index + 1 :]
    if not remaining:
        return None
    if len(remaining) >= 3 and re.match(r"^\d{2}_round_", remaining[0]) and "." not in remaining[1]:
        return remaining[1]
    return remaining[0]


def _metadata_for(
    package_meta: dict[tuple[str, str], dict[str, Any]],
    suite_id: str,
    parts: list[str],
    package_id: str | None,
) -> dict[str, Any]:
    if package_id and (suite_id, package_id) in package_meta:
        return package_meta[(suite_id, package_id)]
    if "packages" in parts:
        index = parts.index("packages")
        relative_parts = parts[index:]
        for length in range(len(relative_parts), 0, -1):
            key = "/".join(relative_parts[:length])
            if (suite_id, key) in package_meta:
                return package_meta[(suite_id, key)]
    return {}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _make_batch(index: int, items: Sequence[BatchItem], char_count: int) -> Batch:
    return Batch(
        batch_id=f"batch-{index:04d}",
        item_count=len(items),
        char_count=char_count,
        document_ids=[item.document_id for item in items],
    )


def _batch_item_manifest(item: BatchItem) -> dict[str, Any]:
    return {
        "document_id": item.document_id,
        "source_sha256": item.source_sha256,
        "suite_id": item.suite_id,
        "source_relative_path": item.source_relative_path,
        "package_id": item.package_id,
        "role": item.role,
        "char_count": len(item.text),
        "rights_status": item.rights_status,
        "rights_warnings": item.rights_warnings,
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _write_ingest_summary(report_dir: Path, summary: IngestSummary) -> None:
    payload = {**asdict(summary), "ok": summary.ok}
    (report_dir / "ingest-summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (report_dir / "ingest-summary.md").write_text(_ingest_markdown(payload), encoding="utf-8")


def _write_existing_index_summary(existing_index: ExistingDocumentIndex, report_dir: Path) -> None:
    payload = {
        "document_ids": len(existing_index.document_ids),
        "file_sources": len(existing_index.file_sources),
        "source_hashes": len(existing_index.source_hashes),
    }
    (report_dir / "existing-index-summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _failed_count(payload: dict[str, Any]) -> int:
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else payload
    if not isinstance(counts, dict):
        return 0
    return int(counts.get("failed", 0) or counts.get("FAILED", 0) or 0)


def _active_count(payload: dict[str, Any]) -> int:
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else payload
    if not isinstance(counts, dict):
        return 0
    return sum(int(counts.get(key, 0) or 0) for key in ("pending", "processing", "preprocessed"))


def _all_count(payload: dict[str, Any]) -> int:
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else payload
    if not isinstance(counts, dict):
        return 0
    return int(counts.get("all", 0) or counts.get("ALL", 0) or 0)


def sanitize_response(response: dict[str, Any]) -> dict[str, Any]:
    allowed = {"status", "message", "track_id"}
    return {key: value for key, value in response.items() if key in allowed}


def public_error(exc: BaseException) -> str:
    return _public_text(str(exc), limit=500)


def _public_text(value: Any, *, limit: int) -> str:
    text = str(value)
    text = re.sub(r"/Users/[^\s)'\"]+", "<local-path>", text)
    text = re.sub(r"postgres://[^\s)'\"]+", "<dsn>", text)
    return text[:limit]


def _extract_source_hashes(text: str) -> set[str]:
    if not text:
        return set()
    hashes: set[str] = set()
    for match in re.finditer(
        r"(?:source[_ -]?sha-?256|original source sha-?256|manifest source sha-?256)\s*[:=]\s*`?([a-f0-9]{64})`?",
        text,
        flags=re.IGNORECASE,
    ):
        hashes.add(match.group(1).lower())
    return hashes


def _inventory_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# LightRAG Cinema Craft Inventory",
        "",
        f"- Total files: {summary['total_files']}",
        f"- Selected files: {summary['selected_files']}",
        f"- Skipped files: {summary['skipped_files']}",
        f"- Selected characters: {summary['selected_chars']}",
        f"- Rights warning files: {summary['rights_warning_files']}",
        "",
        "## By Suite",
        "",
        "| Suite | Total | Selected | Skipped | Chars |",
        "|---|---:|---:|---:|---:|",
    ]
    for suite, data in summary["by_suite"].items():
        lines.append(f"| {suite} | {data['total']} | {data['selected']} | {data['skipped']} | {data['chars']} |")
    lines.extend(["", "## Skip Reasons", "", "| Reason | Count |", "|---|---:|"])
    for reason, count in summary["by_skip_reason"].items():
        lines.append(f"| {reason} | {count} |")
    lines.append("")
    return "\n".join(lines)


def _ingest_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# LightRAG Cinema Craft Ingest Summary",
            "",
            f"- Run id: {summary['run_id']}",
            f"- Dry run: {summary['dry_run']}",
            f"- OK: {summary['ok']}",
            f"- Batches: {summary['batches_sent']} / {summary['batches_total']}",
            f"- Items: {summary['items_total']}",
            f"- Characters: {summary['chars_total']}",
            f"- Errors: {len(summary['errors'])}",
            "",
        ]
    )


def _eval_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# LightRAG Cinema Craft Eval Report",
        "",
        f"- OK: {report['ok']}",
        f"- Aggregate score: {report['aggregate_score']}",
        f"- Threshold: {report['threshold']}",
        f"- Usable: {report['usable_count']} / {report['query_count']}",
        f"- Judge used: {report.get('judge_used', False)}",
        f"- Mean judge / precision / sanity: "
        f"{report.get('mean_judge_score', 0.0)} / "
        f"{report.get('mean_retrieval_precision', 0.0)} / "
        f"{report.get('mean_sanity_score', 0.0)}",
        f"- Rights-unsafe answers: {report.get('rights_unsafe_count', 0)}",
        "",
        "| Score | Judge | Precision | Sanity | Rights | Usable | Query |",
        "|---:|---:|---:|---:|:--:|:--:|---|",
    ]
    for result in report["results"]:
        rights = "ok" if result.get("rights_safe", True) else "REVIEW"
        lines.append(
            f"| {result['score']:.4f} "
            f"| {result.get('judge_score', 0.0):.2f} "
            f"| {result.get('retrieval_precision', 0.0):.2f} "
            f"| {result.get('sanity_score', 0.0):.2f} "
            f"| {rights} | {result['usable']} | {result['query']} |"
        )
    lines.append("")
    return "\n".join(lines)
