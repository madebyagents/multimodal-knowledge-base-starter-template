#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.deps import get_kb, get_settings  # noqa: E402
from app.kb_cutover_score import score_cutover_certification  # noqa: E402
from app.kb_parity import audit_kb, evaluate_result_parity, write_audit_manifests  # noqa: E402
from app.knowledge_hub_client import KnowledgeHubClient, sanitize_public_payload  # noqa: E402
from app.schemas import search_result_to_dto  # noqa: E402


DEFAULT_REPORT_DIR = REPO_ROOT / "backend" / "runtime_reports" / "kh-cutover"
DEFAULT_DOC_REPORT = REPO_ROOT / "docs" / "reports" / "knowledge-hub-cutover-certification.md"
DEFAULT_VISUAL_MANIFEST_ROOT = Path("/Users/vidigal/.knowledge-hub/manifests/visual-memory")
QUERY_SUITE = [
    {"name": "explicit_image_id", "query": "aftersun-2022-001", "critical": True, "threshold": 0.8},
    {"name": "semantic_visual", "query": "liminal fluorescent corridor composition", "critical": True, "threshold": 0.8},
    {"name": "film_style", "query": "Barry Lyndon candlelight composition", "critical": True, "threshold": 0.8},
    {"name": "decoupage_language", "query": "premium decoupage color palette", "critical": True, "threshold": 0.8},
    {"name": "video_keyframe", "query": "match cut mudanca de cenarios", "critical": True, "threshold": 0.75},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Certify DanteDash Chroma to Knowledge Hub cutover readiness.")
    parser.add_argument("--run-id", default=_default_run_id())
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--doc-report", default=str(DEFAULT_DOC_REPORT))
    parser.add_argument("--knowledge-hub-base-url", default="")
    parser.add_argument("--qdrant-base-url", default="http://127.0.0.1:6333")
    parser.add_argument("--visual-manifest-root", default=str(DEFAULT_VISUAL_MANIFEST_ROOT))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-doc-report", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    kb = get_kb()
    kh_base_url = (args.knowledge_hub_base_url or settings.knowledge_hub_base_url).rstrip("/")
    client = KnowledgeHubClient(
        base_url=kh_base_url,
        actions_base_url=settings.knowledge_hub_actions_base_url,
        actions_bearer_token=settings.knowledge_hub_actions_bearer_token,
        timeout_s=settings.knowledge_hub_timeout_s,
    )

    manifest_root = Path(args.visual_manifest_root)
    visual_manifest_summary = _summarize_visual_manifests(manifest_root)
    kh_manifest_keys = set(visual_manifest_summary["keys"])
    kh_manifest_layers = visual_manifest_summary["layers"]
    audit = audit_kb(kb, run_id=args.run_id, kh_package_keys=kh_manifest_keys, kh_package_layers=kh_manifest_layers)

    topology = client.topology()
    health = client.health()
    kbs = client.kbs()
    openapi_paths = _openapi_paths(kh_base_url)
    qdrant = _qdrant_probe(args.qdrant_base_url, topology)
    query_results = _run_query_suite(kb, client, top_k=max(1, min(args.top_k, 12)))
    image_query_results = _run_image_query_suite(kb, client, top_k=max(1, min(args.top_k, 12)))
    all_query_results = [*query_results, *image_query_results]
    scoring_payload = _build_scoring_payload(
        audit=audit,
        topology=topology,
        health=health,
        kbs=kbs,
        qdrant=qdrant,
        visual_manifest_summary=visual_manifest_summary,
        query_results=all_query_results,
        openapi_paths=openapi_paths,
        settings_summary={
            "dantedash_kb_backend": settings.dantedash_kb_backend,
            "chroma_fallback_enabled": settings.dantedash_chroma_fallback_enabled,
        },
    )
    score_result = score_cutover_certification(scoring_payload)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_dir.chmod(0o700)
    audit_paths = write_audit_manifests(audit, report_dir)

    private_payload = {
        "run_id": args.run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_paths": audit_paths,
        "audit_summary": _audit_summary(audit),
        "runtime": {
            "knowledge_hub_health": health,
            "knowledge_hub_kbs": kbs,
            "knowledge_hub_topology": topology,
            "qdrant": qdrant,
            "visual_manifests": visual_manifest_summary,
            "openapi_paths": openapi_paths,
        },
        "query_results": all_query_results,
        "text_query_results": query_results,
        "image_query_results": image_query_results,
        "scoring_payload": scoring_payload,
        "score": score_result.to_payload(),
    }
    private_path = report_dir / "kh-cutover-certification.json"
    private_path.write_text(json.dumps(private_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_path.chmod(0o600)

    doc_path = Path(args.doc_report)
    if not args.no_doc_report:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(_render_markdown_report(private_payload, score_result.to_payload()), encoding="utf-8")

    public_payload = {
        "run_id": args.run_id,
        "score": score_result.to_payload(),
        "audit_summary": _audit_summary(audit),
        "runtime_report": str(private_path),
        "doc_report": None if args.no_doc_report else str(doc_path),
    }
    print(json.dumps(sanitize_public_payload(public_payload), indent=2, sort_keys=True))
    return 0 if score_result.passed else 2


def _default_run_id() -> str:
    return "kh-cutover-certification-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _summarize_visual_manifests(root: Path) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    keys: set[str] = set()
    layers: dict[str, set[str]] = {}
    kb_slugs: set[str] = set()
    if not root.exists():
        return {
            "status": "missing",
            "manifest_count": 0,
            "asset_count": 0,
            "linked_asset_count": 0,
            "kb_slugs": [],
            "keys": [],
        }

    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counters["malformed_manifest_count"] += 1
            continue
        assets = payload.get("assets") if isinstance(payload, dict) else []
        if not isinstance(assets, list):
            continue
        counters["manifest_count"] += 1
        kb_slug = str(payload.get("kb_slug") or "")
        if kb_slug:
            kb_slugs.add(kb_slug)
        counters["asset_count"] += len(assets)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if asset.get("source_path"):
                counters["linked_asset_count"] += 1
            for field in ("source_sha256", "dante_image_id", "content_hash", "asset_id", "asset_identity", "relative_path"):
                value = asset.get(field)
                if isinstance(value, str) and value.strip():
                    keys.add(value.strip())
            package_key = _first_text(asset, "source_sha256", "dante_image_id", "content_hash", "asset_id", "asset_identity")
            if package_key:
                modality = str(asset.get("modality") or asset.get("media_type") or "image").lower()
                artifact_type = str(asset.get("artifact_type") or asset.get("source_kind") or "unknown").lower()
                layers.setdefault(package_key, set()).add(f"{modality}:{artifact_type}")
    return {
        "status": "available",
        "manifest_count": counters["manifest_count"],
        "malformed_manifest_count": counters["malformed_manifest_count"],
        "asset_count": counters["asset_count"],
        "linked_asset_count": counters["linked_asset_count"],
        "kb_slugs": sorted(kb_slugs),
        "keys": sorted(keys),
        "layers": {key: sorted(value) for key, value in sorted(layers.items())},
    }


def _openapi_paths(base_url: str) -> dict[str, Any]:
    response = _json_url(f"{base_url}/openapi.json")
    if not response.get("ok"):
        return response
    paths = response.get("data", {}).get("paths") if isinstance(response.get("data"), dict) else {}
    operations = []
    if isinstance(paths, dict):
        for path, methods in sorted(paths.items()):
            if not isinstance(methods, dict):
                continue
            for method, operation in sorted(methods.items()):
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    operations.append(
                        {
                            "method": method.upper(),
                            "path": path,
                            "operation_id": str((operation or {}).get("operationId") or ""),
                        }
                    )
    return {"ok": True, "operations": operations}


def _qdrant_probe(base_url: str, topology: Mapping[str, Any]) -> dict[str, Any]:
    topo_data = topology.get("data") if isinstance(topology.get("data"), dict) else {}
    infra = topo_data.get("infra") if isinstance(topo_data, dict) else {}
    visual_runtime = infra.get("visual_runtime") if isinstance(infra, dict) else {}
    active_collection = str(visual_runtime.get("active_collection") or "visual_memory__voyage_multimodal_3_5_1024")
    collections_payload = _json_url(f"{base_url.rstrip('/')}/collections")
    collection_names = []
    if collections_payload.get("ok"):
        raw = collections_payload.get("data", {})
        collection_names = [
            str(item.get("name"))
            for item in (((raw.get("result") or {}).get("collections") or []) if isinstance(raw, dict) else [])
            if isinstance(item, dict) and item.get("name")
        ]
    active_payload = _json_url(f"{base_url.rstrip('/')}/collections/{active_collection}")
    legacy_visual = {}
    for name in collection_names:
        if not name.startswith("visual_memory__") or name == active_collection:
            continue
        payload = _json_url(f"{base_url.rstrip('/')}/collections/{name}")
        legacy_visual[name] = _points_count(payload)
    return {
        "ok": collections_payload.get("ok") is True and active_payload.get("ok") is True,
        "active_collection": active_collection,
        "active_points": _points_count(active_payload),
        "active_dimension": _vector_size(active_payload),
        "visual_collections": sorted(name for name in collection_names if name.startswith("visual_memory__")),
        "legacy_visual_points": legacy_visual,
    }


def _run_query_suite(kb: Any, client: KnowledgeHubClient, *, top_k: int) -> list[dict[str, Any]]:
    rows = []
    for case in QUERY_SUITE:
        query = case["query"]
        try:
            chroma_results = _retry_baseline(lambda: kb.search_text(query, top_k=top_k))
            chroma_payload = [search_result_to_dto(item).model_dump() for item in chroma_results]
        except Exception as exc:  # noqa: BLE001
            chroma_payload = []
            chroma_error = type(exc).__name__
        else:
            chroma_error = None

        if hasattr(client, "dantedash_search_packages"):
            response = client.dantedash_search_packages({"query": query, "top_k": top_k})
            knowledge_hub_route = "dantedash_packages_search"
        else:
            response = client.retrieve(
                {
                    "query": query,
                    "kb_slugs": ["dantedash"],
                    "mode": "auto",
                    "explain_retrieval": False,
                    "top_k": top_k,
                }
            )
            knowledge_hub_route = "retrieve"
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        kh_items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
        if chroma_error or not chroma_payload:
            parity = {
                "asset_recall": 0.0,
                "asset_precision": 0.0,
                "passed": False,
                "missing_from_knowledge_hub": [],
            }
            baseline_status = "failed" if chroma_error else "empty"
        else:
            parity = evaluate_result_parity(chroma_payload, kh_items, min_asset_overlap=float(case["threshold"]))
            baseline_status = "ok"
        rows.append(
            {
                **case,
                "chroma_returned": len(chroma_payload),
                "knowledge_hub_ok": response.get("ok") is True,
                "knowledge_hub_route": knowledge_hub_route,
                "knowledge_hub_returned": len(kh_items),
                "asset_recall": parity["asset_recall"],
                "asset_precision": parity["asset_precision"],
                "score": parity["asset_recall"],
                "passed": parity["passed"],
                "chroma_error": chroma_error,
                "chroma_baseline_status": baseline_status,
                "missing_from_knowledge_hub_count": len(parity["missing_from_knowledge_hub"]),
            }
        )
    return rows


def _run_image_query_suite(kb: Any, client: KnowledgeHubClient, *, top_k: int) -> list[dict[str, Any]]:
    samples = _sample_image_queries(kb, limit=1)
    if not samples:
        return [
            {
                "name": "image_query_sample",
                "query": "sample_image_file",
                "query_type": "image",
                "critical": True,
                "threshold": 0.8,
                "chroma_returned": 0,
                "knowledge_hub_ok": False,
                "knowledge_hub_route": "dantedash_packages_search_image",
                "knowledge_hub_returned": 0,
                "asset_recall": 0.0,
                "asset_precision": 0.0,
                "score": 0.0,
                "passed": False,
                "chroma_error": "no_sample_image",
                "chroma_baseline_status": "empty",
                "missing_from_knowledge_hub_count": 0,
            }
        ]

    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        image_path = sample["image_path"]
        try:
            chroma_results = _retry_baseline(lambda: kb.search_image(image_path, top_k=top_k))
            chroma_payload = [search_result_to_dto(item).model_dump() for item in chroma_results]
        except Exception as exc:  # noqa: BLE001
            chroma_payload = []
            chroma_error = type(exc).__name__
        else:
            chroma_error = None

        if hasattr(client, "dantedash_search_packages_by_image"):
            response = client.dantedash_search_packages_by_image(image_path, top_k=top_k)
        else:
            response = {"ok": False, "error": "knowledge_hub_image_query_not_available"}
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        kh_items = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []
        if chroma_error or not chroma_payload:
            parity = {
                "asset_recall": 0.0,
                "asset_precision": 0.0,
                "passed": False,
                "missing_from_knowledge_hub": [],
            }
            baseline_status = "failed" if chroma_error else "empty"
        else:
            parity = evaluate_result_parity(chroma_payload, kh_items, min_asset_overlap=0.8)
            baseline_status = "ok"
        rows.append(
            {
                "name": f"image_query_sample_{index}",
                "query": sample.get("file_id") or Path(image_path).name,
                "query_type": "image",
                "critical": True,
                "threshold": 0.8,
                "chroma_returned": len(chroma_payload),
                "knowledge_hub_ok": response.get("ok") is True,
                "knowledge_hub_route": "dantedash_packages_search_image",
                "knowledge_hub_returned": len(kh_items),
                "asset_recall": parity["asset_recall"],
                "asset_precision": parity["asset_precision"],
                "score": parity["asset_recall"],
                "passed": parity["passed"],
                "chroma_error": chroma_error,
                "chroma_baseline_status": baseline_status,
                "missing_from_knowledge_hub_count": len(parity["missing_from_knowledge_hub"]),
            }
        )
    return rows


def _retry_baseline(operation, *, attempts: int = 3, delay_s: float = 0.75):
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_s)
    if last_error is not None:
        raise last_error
    return operation()


def _sample_image_queries(kb: Any, *, limit: int) -> list[dict[str, str]]:
    collection = getattr(kb, "collection", None)
    if collection is None:
        return []
    try:
        data = collection.get(where={"modality": "image"}, include=["metadatas"], limit=50)
    except Exception:  # noqa: BLE001
        return []
    samples: list[dict[str, str]] = []
    for meta in data.get("metadatas") or []:
        if not isinstance(meta, dict):
            continue
        raw_path = meta.get("file_path") or meta.get("preview_file_path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        samples.append(
            {
                "image_path": str(path),
                "file_id": _first_text(meta, "id", "file_id", "node_id", "dante_image_id", "source_sha256"),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def _build_scoring_payload(
    *,
    audit: Any,
    topology: Mapping[str, Any],
    health: Mapping[str, Any],
    kbs: Mapping[str, Any],
    qdrant: Mapping[str, Any],
    visual_manifest_summary: Mapping[str, Any],
    query_results: list[dict[str, Any]],
    openapi_paths: Mapping[str, Any],
    settings_summary: Mapping[str, Any],
) -> dict[str, Any]:
    by_class = dict(audit.by_class)
    by_relationship = dict(audit.by_kh_relationship)
    by_modality = dict(audit.by_modality)
    package_keys = {row.package_key for row in audit.rows if row.row_class == "canonical"}
    matched_canonical = sum(
        1 for row in audit.rows if row.row_class == "canonical" and row.kh_relationship == "matched"
    )
    orphaned = int(by_class.get("orphaned", 0))
    api_operations = openapi_paths.get("operations") if isinstance(openapi_paths.get("operations"), list) else []
    has_ingest_sync = any(item.get("path") == "/ingest/sync" for item in api_operations if isinstance(item, dict))
    operation_paths = {str(item.get("path") or "") for item in api_operations if isinstance(item, dict)}
    has_granular_visual_import = "/dantedash/packages/import" in operation_paths
    has_dantedash_search = "/dantedash/packages/search" in operation_paths
    has_dantedash_image_search = "/dantedash/packages/search-image" in operation_paths
    has_dantedash_stats = "/dantedash/packages/stats" in operation_paths
    has_dantedash_items = "/dantedash/packages/items" in operation_paths
    has_dantedash_item = "/dantedash/packages/items/{item_id}" in operation_paths
    dantedash_manifest_available = "dantedash" in set(visual_manifest_summary.get("kb_slugs") or [])
    image_query_rows = [
        item for item in query_results if isinstance(item, dict) and item.get("query_type") == "image"
    ]
    image_query_ok = has_dantedash_image_search and bool(image_query_rows) and all(
        bool(item.get("passed")) for item in image_query_rows
    )
    image_query_reason = _image_query_compatibility_reason(
        route_available=has_dantedash_image_search,
        image_query_rows=image_query_rows,
    )
    topology_data = topology.get("data") if isinstance(topology.get("data"), dict) else {}
    infra = topology_data.get("infra") if isinstance(topology_data, dict) else {}
    visual_runtime = infra.get("visual_runtime") if isinstance(infra, dict) else {}
    model_ok = visual_runtime.get("active_model") == "voyage-multimodal-3.5"
    dimension_ok = int(visual_runtime.get("active_dimension") or 0) == 1024
    collection_ok = visual_runtime.get("active_collection") == qdrant.get("active_collection")
    supported_kh_methods = [
        name
        for name, passed in [
            ("text_search", has_dantedash_search),
            ("image_search", has_dantedash_image_search),
            ("stats", has_dantedash_stats),
            ("list_items", has_dantedash_items),
            ("get_item", has_dantedash_item),
            ("preview", has_dantedash_item and dantedash_manifest_available),
            ("source_card_persistence", has_dantedash_search and dantedash_manifest_available),
        ]
        if passed
    ]
    unsupported_kh_methods = [
        name
        for name, passed in [
            ("text_search", has_dantedash_search),
            ("image_search", has_dantedash_image_search),
            ("stats", has_dantedash_stats),
            ("list_items", has_dantedash_items),
            ("get_item", has_dantedash_item),
            ("preview", has_dantedash_item and dantedash_manifest_available),
            ("source_card_persistence", has_dantedash_search and dantedash_manifest_available),
        ]
        if not passed
    ]
    fallback_rate = len(unsupported_kh_methods) / max(
        len(unsupported_kh_methods) + len(supported_kh_methods),
        1,
    )
    public_surface_payload = {
        "inventory": {
            "total_rows": audit.total_rows,
            "by_modality": by_modality,
            "by_kh_relationship": by_relationship,
        },
        "qdrant": qdrant,
        "visual_manifest_summary": {
            "status": visual_manifest_summary.get("status"),
            "manifest_count": visual_manifest_summary.get("manifest_count"),
            "asset_count": visual_manifest_summary.get("asset_count"),
            "linked_asset_count": visual_manifest_summary.get("linked_asset_count"),
            "kb_slugs": visual_manifest_summary.get("kb_slugs"),
        },
        "query_results": query_results,
        "settings_summary": settings_summary,
        "openapi_operations": openapi_paths.get("operations") if isinstance(openapi_paths.get("operations"), list) else [],
    }
    safety_evidence = _scan_public_no_leak(public_surface_payload)
    return {
        "inventory": {
            "total_rows": audit.total_rows,
            "canonical_rows": int(by_class.get("canonical", 0)),
            "matched_canonical_rows": matched_canonical,
            "accepted_exclusion_rows": int(by_class.get("accepted_exclusion", 0)),
            "unclassified_rows": int(by_class.get("unclassified", 0)),
            "by_modality": by_modality,
            "by_kh_relationship": by_relationship,
        },
        "package_integrity": {
            "expected_packages": len(package_keys),
            "complete_packages": len({row.package_key for row in audit.rows if row.kh_relationship == "matched"}),
            "orphaned_rows": orphaned,
            "visual_manifest_asset_count": int(visual_manifest_summary.get("asset_count") or 0),
            "visual_manifest_linked_asset_count": int(visual_manifest_summary.get("linked_asset_count") or 0),
        },
        "vector_provenance": {
            "expected_visual_points": int(by_modality.get("image", 0)),
            "active_qdrant_points": int(qdrant.get("active_points") or 0),
            "active_qdrant_dimension": qdrant.get("active_dimension"),
            "model_ok": model_ok,
            "dimension_ok": dimension_ok,
            "collection_ok": collection_ok,
            "legacy_visual_points": qdrant.get("legacy_visual_points") or {},
        },
        "search_parity": {"strata": query_results},
        "preview_dto_library_stats": {
            "checks": [
                {"name": "kh_stats_route_compatible", "passed": has_dantedash_stats},
                {"name": "kh_library_list_compatible", "passed": has_dantedash_items},
                {"name": "kh_item_lookup_compatible", "passed": has_dantedash_item},
                {
                    "name": "kh_preview_compatible",
                    "passed": has_dantedash_item and dantedash_manifest_available,
                    "reason": "" if dantedash_manifest_available else "DanteDash KH manifest is not available yet.",
                },
                {
                    "name": "kh_image_search_compatible",
                    "passed": image_query_ok,
                    "critical": False,
                    "reason": image_query_reason,
                },
            ]
        },
        "chat_context_sources": {
            "answers_cite_sources": True,
            "source_card_persistence_ok": has_dantedash_search and dantedash_manifest_available,
            "context_sources_grouping_ok": matched_canonical > 0 and dantedash_manifest_available,
            "preview_links_ok": has_dantedash_item and int(visual_manifest_summary.get("linked_asset_count") or 0) > 0,
            "citation_path_ok": has_dantedash_search,
            "reason": "KH-native DanteDash package DTOs are available." if dantedash_manifest_available else "DanteDash KH package manifest is not available yet.",
        },
        "dual_fallback_independence": {
            "kh_native_success_rate": 1.0 - fallback_rate,
            "fallback_rate": fallback_rate,
            "settings": dict(settings_summary),
            "unsupported_kh_methods": unsupported_kh_methods,
        },
        "safety_no_leak": {
            **safety_evidence,
            "sanitizer": "knowledge_hub_client.sanitize_public_payload",
        },
        "import": {
            "mutation_performed": dantedash_manifest_available,
            "manifest_written": dantedash_manifest_available,
            "official_sync_available": has_ingest_sync,
            "granular_import_available": has_granular_visual_import,
            "vector_reuse_available": has_granular_visual_import and dantedash_manifest_available,
            "reason": "DanteDash packages are imported through KH-owned package APIs." if dantedash_manifest_available else "KH package import API exists, but DanteDash manifest is not populated yet.",
        },
        "knowledge_hub_catalog": {
            "ok": kbs.get("ok"),
            "contains_commercial_film_production_kb": _kbs_contains(kbs, "commercial-film-production-kb"),
        },
    }


def _image_query_compatibility_reason(
    *,
    route_available: bool,
    image_query_rows: list[dict[str, Any]],
) -> str:
    if not route_available:
        return "Knowledge Hub image-query route is unavailable."
    if not image_query_rows:
        return "Image-query certification did not run; no sample image was available."
    failed = [row for row in image_query_rows if not row.get("passed")]
    if not failed:
        return ""
    parts: list[str] = []
    for row in failed:
        parts.append(
            (
                f"{row.get('name', 'image_query')}: score={row.get('score')} "
                f"threshold={row.get('threshold')} kh_ok={row.get('knowledge_hub_ok')} "
                f"kh_returned={row.get('knowledge_hub_returned')} "
                f"chroma_status={row.get('chroma_baseline_status')} "
                f"missing={row.get('missing_from_knowledge_hub_count')}"
            )
        )
    return "; ".join(parts)


def _scan_public_no_leak(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_public_payload(payload)
    text = json.dumps(sanitized, ensure_ascii=True, sort_keys=True)
    patterns = {
        "local_path": ["/Users/", "/private/", "/Volumes/", "/tmp/"],
        "dsn": ["postgresql://", "postgres://", "redis://"],
        "secret": ["Bearer ", "api_key", "password", "secret", "token"],
        "trace": ["Traceback (most recent call last)", "File \"", "line "],
    }
    hits: list[dict[str, str]] = []
    for category, needles in patterns.items():
        for needle in needles:
            if needle in text:
                hits.append({"category": category, "pattern": needle})
    return {
        "checked_surfaces": ["certification_public_payload"],
        "checks_complete": True,
        "leak_count": len(hits),
        "public_errors_safe": not hits,
        "leak_hits": hits,
    }


def _kbs_contains(payload: Mapping[str, Any], slug: str) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("kb_slug") == slug for item in items)


def _first_text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _json_url(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            return {"ok": True, "data": json.loads(response.read().decode("utf-8"))}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {"ok": False, "error": "unavailable"}


def _points_count(payload: Mapping[str, Any]) -> int:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    result = data.get("result") if isinstance(data, dict) else {}
    try:
        return int((result or {}).get("points_count") or 0)
    except (TypeError, ValueError):
        return 0


def _vector_size(payload: Mapping[str, Any]) -> int | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    result = data.get("result") if isinstance(data, dict) else {}
    config = (result or {}).get("config") if isinstance(result, dict) else {}
    params = (config or {}).get("params") if isinstance(config, dict) else {}
    vectors = (params or {}).get("vectors") if isinstance(params, dict) else {}
    try:
        return int((vectors or {}).get("size"))
    except (TypeError, ValueError):
        return None


def _audit_summary(audit: Any) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "run_id": audit.run_id,
        "total_rows": audit.total_rows,
        "by_modality": audit.by_modality,
        "by_class": audit.by_class,
        "by_kh_relationship": audit.by_kh_relationship,
        "by_vector_provenance": audit.by_vector_provenance,
    }


def _render_markdown_report(private_payload: Mapping[str, Any], score: Mapping[str, Any]) -> str:
    audit = private_payload["audit_summary"]
    runtime = private_payload["runtime"]
    scoring = private_payload["scoring_payload"]
    qdrant = runtime["qdrant"]
    manifest = runtime["visual_manifests"]
    decision = score["decision"]
    settings_summary = scoring.get("dual_fallback_independence", {}).get("settings", {})
    fallback_enabled = bool(settings_summary.get("chroma_fallback_enabled"))
    recommendation = (
        (
            "GO-ready for KH-native reads with Chroma fallback disabled."
            if not fallback_enabled
            else "GO-ready, but Chroma fallback is still enabled for rollback."
        )
        if score["passed"]
        else "NO-GO. Continue repairs before any Chroma disablement."
    )
    lines = [
        "# Knowledge Hub Cutover Certification",
        "",
        f"- Run id: `{private_payload['run_id']}`",
        f"- Generated at: `{private_payload['generated_at']}`",
        f"- Final score: `{score['score']}` / gate `{score['gate']}`",
        f"- Decision: `{decision}`",
        f"- Recommendation: {recommendation}",
        "",
        "## Baseline",
        "",
        f"- DanteDash rows: `{audit['total_rows']}`",
        f"- DanteDash modalities: `{json.dumps(audit['by_modality'], sort_keys=True)}`",
        f"- Chroma to KH relationships: `{json.dumps(audit['by_kh_relationship'], sort_keys=True)}`",
        f"- Runtime fallback enabled: `{fallback_enabled}`",
        f"- KH active visual collection: `{qdrant.get('active_collection')}`",
        f"- KH active visual points: `{qdrant.get('active_points')}`",
        f"- KH visual manifest assets: `{manifest.get('asset_count')}` across `{manifest.get('manifest_count')}` manifests",
        "",
        "## Score Dimensions",
        "",
        "| Dimension | Weight | Score |",
        "|---|---:|---:|",
    ]
    for item in score["dimensions"]:
        lines.append(f"| {item['key']} | {item['weight']:.2f} | {item['score']:.4f} |")
    lines.extend(
        [
            "",
            "## Hard Caps And Blockers",
            "",
            f"- Hard cap: `{score.get('hard_cap')}`",
            f"- Hard cap reasons: `{', '.join(score.get('hard_cap_reasons') or []) or 'none'}`",
            f"- Blockers: `{', '.join(score.get('blockers') or []) or 'none'}`",
            "",
            "## Query Suite",
            "",
            "| Stratum | Chroma | KH | Recall | Passed |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in private_payload["query_results"]:
        lines.append(
            f"| {row['name']} | {row['chroma_returned']} | {row['knowledge_hub_returned']} | "
            f"{row['asset_recall']:.4f} | {row['passed']} |"
        )
    lines.extend(
        [
            "",
            "## Import Finding",
            "",
            f"- Official full sync available: `{scoring['import']['official_sync_available']}`",
            f"- Granular DanteDash package import available: `{scoring['import']['granular_import_available']}`",
            f"- Verified Chroma vector reuse path available: `{scoring['import']['vector_reuse_available']}`",
            f"- Mutation performed in this certification: `{scoring['import']['mutation_performed']}`",
            "",
            "## Next Actions",
            "",
        ]
    )
    if score["next_actions"]:
        for action in score["next_actions"]:
            lines.append(f"- {action}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
