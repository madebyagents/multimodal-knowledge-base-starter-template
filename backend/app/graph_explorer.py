"""Read-only LightRAG GraphML explorer for the Black Label graph."""
from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

DEFAULT_GRAPHML_PATH = Path(
    "/Users/vidigal/Obsidian_Dante_AI_RAG_DATA/"
    "neural_memory_voyage_2048/graph_chunk_entity_relation.graphml"
)
DEFAULT_DATASET_ID = "commercial-film-production-kb"
SEP = "<SEP>"

MAX_SOURCE_BYTES = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_BYTES", str(220 * 1024 * 1024)))
MAX_GRAPH_KEYS = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_KEYS", "2048"))
MAX_GRAPH_NODES = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_NODES", "300000"))
MAX_GRAPH_EDGES = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_EDGES", "900000"))
MAX_DATA_FIELDS = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_DATA_FIELDS", "96"))
MAX_FIELD_CHARS = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_FIELD_CHARS", "12000"))
MAX_LIST_ITEMS = int(os.getenv("DANTE_LIGHTRAG_GRAPHML_MAX_LIST_ITEMS", "220"))
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GraphExplorerError(RuntimeError):
    """Stable, redacted graph explorer error."""

    status_code = 503

    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


class GraphSourceMissing(GraphExplorerError):
    status_code = 404


class GraphNodeMissing(GraphExplorerError):
    status_code = 404


@dataclass(frozen=True)
class RouteRule:
    id: str
    label: str
    patterns: tuple[str, ...]


ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        "core-pack",
        "Core Pack",
        (
            "readme.md",
            "index.md",
            "commercial-film-production-kb",
            "core pack",
            "fast ingest",
            "lightrag source",
        ),
    ),
    RouteRule(
        "source-routing",
        "Source Routing",
        ("source-routing__", "source routing", "routecap", "routegrp", "routing capsule"),
    ),
    RouteRule(
        "overview-manifests",
        "Overview And Manifests",
        ("00-overview-and-manifests", "overview", "manifest"),
    ),
    RouteRule(
        "agent-operating-system",
        "Agent Operating System",
        ("01-agent-operating-system", "agent operating system"),
    ),
    RouteRule(
        "craft-field-manuals",
        "Craft Field Manuals",
        ("02-craft-field-manuals", "craft field manuals", "composition", "lighting", "lens"),
    ),
    RouteRule(
        "commercial-verticals",
        "Commercial Verticals",
        ("03-commercial-verticals", "commercial verticals", "brand", "vertical"),
    ),
    RouteRule(
        "treatment-ppm-pitch",
        "Treatment, PPM And Pitch",
        ("04-treatment-ppm-pitch", "treatment", "ppm", "pitch"),
    ),
    RouteRule(
        "ai-filmmaking-prompt-control",
        "AI Filmmaking And Prompt Control",
        ("05-ai-filmmaking-and-prompt-control", "prompt control", "ai filmmaking"),
    ),
    RouteRule(
        "director-tools",
        "Black Label Director Tools",
        ("06-black-label-a-director-tools", "director tools", "black label a"),
    ),
    RouteRule(
        "qc-repair",
        "QC, Repair And Finishing",
        ("07-black-label-b-qc-repair", "qc repair", "repair", "finishing"),
    ),
    RouteRule("ai-systems", "Black Label AI Systems", ("08-black-label-c-ai-systems", "ai systems")),
    RouteRule(
        "remaining-bundles",
        "Remaining Bundles",
        ("09-black-label-remaining-bundles", "remaining bundles"),
    ),
    RouteRule(
        "templates-rubrics-checklists",
        "Templates, Rubrics And Checklists",
        ("11-templates-rubrics-checklists", "templates", "rubrics", "checklists"),
    ),
    RouteRule(
        "tools-pipelines-data",
        "Tools, Pipelines And Data",
        ("12-tools-pipelines-and-data", "tools", "pipelines", "sqlite fts"),
    ),
    RouteRule(
        "visual-analysis-cards",
        "Visual Analysis Cards",
        ("visual-analysis-cards", "visual analysis cards", "film-stills", "shotdeck-batches"),
    ),
    RouteRule(
        "visual-reference-assets",
        "Visual Reference Assets",
        ("13-visual-reference-assets", "source-assets", "visual reference"),
    ),
)


@dataclass
class SourceState:
    path: Path
    exists: bool
    regular_file: bool = False
    source_name: str = ""
    size_bytes: int | None = None
    mtime_ns: int | None = None
    mtime_iso: str | None = None
    metadata_hash: str | None = None


@dataclass
class GraphNode:
    id: str
    label: str
    entity_type: str
    descriptions: list[str]
    source_ids: list[str]
    source_files: list[str]
    created_at: str | None
    truncate: str | None
    routes: list[str]
    route_labels: list[str]
    source_families: list[str]
    degree: int = 0
    weighted_degree: float = 0.0
    edge_ids: list[str] = field(default_factory=list)
    neighbors: set[str] = field(default_factory=set)
    search_text: str = ""


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    weight: float
    descriptions: list[str]
    keywords: list[str]
    source_ids: list[str]
    source_files: list[str]
    created_at: str | None
    truncate: str | None
    routes: list[str]
    route_labels: list[str]
    source_families: list[str]
    search_text: str = ""


@dataclass
class GraphSnapshot:
    state: SourceState
    loaded_at_iso: str
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    adjacency: dict[str, list[GraphEdge]]
    entity_type_counts: dict[str, int]
    route_counts: dict[str, int]
    source_family_counts: dict[str, int]


class GraphExplorer:
    """Lazy, bounded, read-only GraphML index with DTO helpers."""

    def __init__(self, graphml_path: Path | str = DEFAULT_GRAPHML_PATH) -> None:
        self.graphml_path = Path(graphml_path).expanduser()
        self._lock = threading.RLock()
        self._snapshot: GraphSnapshot | None = None

    def health(self, *, load: bool = False) -> dict[str, Any]:
        state = self._source_state()
        snapshot = self._snapshot
        error: str | None = None
        if load and state.exists:
            try:
                snapshot = self._load()
            except GraphExplorerError as exc:
                error = exc.public_message
        elif load and not state.exists:
            error = "graph_source_missing"
        return {
            "ok": state.exists and error is None,
            "dataset_id": DEFAULT_DATASET_ID,
            "source": self._source_payload(state),
            "loaded": snapshot is not None,
            "cache": self._cache_status(state, snapshot),
            "node_count": len(snapshot.nodes) if snapshot else None,
            "edge_count": len(snapshot.edges) if snapshot else None,
            "loaded_at": snapshot.loaded_at_iso if snapshot else None,
            "read_only": True,
            "error": error,
        }

    def summary(self, *, top_nodes_limit: int = 40, max_nodes: int = 700, max_edges: int = 1400) -> dict[str, Any]:
        snapshot = self._load()
        graph = self._graph_payload(
            snapshot,
            node_ids=self._overview_node_ids(snapshot, max_nodes=max_nodes),
            max_edges=max_edges,
        )
        return {
            "dataset_id": DEFAULT_DATASET_ID,
            "source": self._source_payload(snapshot.state),
            "cache": self._cache_status(self._source_state(), snapshot),
            "node_count": len(snapshot.nodes),
            "edge_count": len(snapshot.edges),
            "entity_type_counts": _sorted_count_items(snapshot.entity_type_counts, limit=80),
            "route_counts": _sorted_count_items(snapshot.route_counts, limit=80),
            "source_family_counts": _sorted_count_items(snapshot.source_family_counts, limit=80),
            "top_nodes": [
                self._node_card(node)
                for node in sorted(
                    snapshot.nodes.values(),
                    key=lambda n: (-n.weighted_degree, -n.degree, n.label.lower()),
                )[:top_nodes_limit]
            ],
            "graph": graph,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        entity_type: str | None = None,
        route: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self._load()
        clean_query = query.strip()
        if not clean_query:
            return {"query": query, "results": []}
        query_lc = clean_query.lower()
        tokens = [part for part in query_lc.split() if part]
        results: list[tuple[float, GraphNode]] = []
        for node in snapshot.nodes.values():
            if not _node_matches(node, entity_type=entity_type, route=route):
                continue
            score = _score_node(node, query_lc=query_lc, tokens=tokens)
            if score > 0:
                results.append((score, node))
        results.sort(key=lambda item: (-item[0], -item[1].weighted_degree, item[1].label.lower()))
        return {
            "query": query,
            "results": [
                self._node_card(node, score=round(score, 4), snippet_query=query_lc)
                for score, node in results[:limit]
            ],
        }

    def subgraph(
        self,
        *,
        node_id: str | None = None,
        depth: int = 1,
        max_nodes: int = 220,
        max_edges: int = 900,
        entity_type: str | None = None,
        route: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self._load()
        if node_id and node_id not in snapshot.nodes:
            raise GraphNodeMissing("node_not_found")
        if node_id:
            node_ids = self._neighborhood_node_ids(
                snapshot,
                node_id=node_id,
                depth=depth,
                max_nodes=max_nodes,
                entity_type=entity_type,
                route=route,
            )
            center = self._node_card(snapshot.nodes[node_id])
        else:
            node_ids = self._overview_node_ids(
                snapshot,
                max_nodes=max_nodes,
                entity_type=entity_type,
                route=route,
            )
            center = None
        return {
            "dataset_id": DEFAULT_DATASET_ID,
            "center": center,
            "depth": depth,
            "graph": self._graph_payload(snapshot, node_ids=node_ids, max_edges=max_edges),
        }

    def node_detail(self, node_id: str, *, edge_limit: int = 80) -> dict[str, Any]:
        snapshot = self._load()
        if node_id not in snapshot.nodes:
            raise GraphNodeMissing("node_not_found")
        node = snapshot.nodes[node_id]
        adjacent = sorted(
            snapshot.adjacency.get(node_id, []),
            key=lambda e: (-e.weight, _other_node_id(e, node_id).lower()),
        )[:edge_limit]
        return {
            **self._node_card(node, include_full=True),
            "adjacent_edges": [
                self._edge_card(edge, include_description=True, focus_node_id=node_id)
                for edge in adjacent
            ],
        }

    def _load(self) -> GraphSnapshot:
        with self._lock:
            state = self._source_state()
            self._validate_source(state)
            if self._snapshot and self._is_cache_fresh(state, self._snapshot):
                return self._snapshot
            _reject_unsafe_xml(state.path)
            self._snapshot = _parse_graphml(state.path, state=state)
            return self._snapshot

    def _source_state(self) -> SourceState:
        path = self.graphml_path.resolve(strict=False)
        source_name = path.name or "graph_chunk_entity_relation.graphml"
        if not path.exists():
            return SourceState(path=path, exists=False, source_name=source_name)
        stat = path.stat()
        mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        metadata_hash = hashlib.sha256(
            f"{source_name}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()
        return SourceState(
            path=path,
            exists=True,
            regular_file=path.is_file(),
            source_name=source_name,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            mtime_iso=mtime_iso,
            metadata_hash=metadata_hash,
        )

    def _validate_source(self, state: SourceState) -> None:
        if not state.exists:
            raise GraphSourceMissing("graph_source_missing")
        if not state.regular_file:
            raise GraphExplorerError("graph_source_not_regular_file")
        if state.path.suffix.lower() != ".graphml":
            raise GraphExplorerError("graph_source_must_be_graphml")
        if state.size_bytes is not None and state.size_bytes > MAX_SOURCE_BYTES:
            raise GraphExplorerError("graph_source_too_large")

    def _cache_status(self, state: SourceState, snapshot: GraphSnapshot | None) -> dict[str, Any]:
        if not snapshot:
            return {"loaded": False, "fresh": False, "stale": False}
        fresh = self._is_cache_fresh(state, snapshot)
        return {
            "loaded": True,
            "fresh": fresh,
            "stale": not fresh,
            "loaded_at": snapshot.loaded_at_iso,
            "metadata_hash": snapshot.state.metadata_hash,
        }

    @staticmethod
    def _is_cache_fresh(state: SourceState, snapshot: GraphSnapshot) -> bool:
        return (
            state.exists
            and state.size_bytes == snapshot.state.size_bytes
            and state.mtime_ns == snapshot.state.mtime_ns
        )

    def _overview_node_ids(
        self,
        snapshot: GraphSnapshot,
        *,
        max_nodes: int,
        entity_type: str | None = None,
        route: str | None = None,
    ) -> list[str]:
        pinned = [
            "Commercial-Film-Production-Kb",
            "Black Label Lightrag Source",
            "Source-Routing Markdown",
            "Visual Analysis Cards",
            "Core Pack",
        ]
        selected: list[str] = []
        for node_id in pinned:
            node = snapshot.nodes.get(node_id)
            if node and _node_matches(node, entity_type=entity_type, route=route):
                selected.append(node.id)
        for node in sorted(
            snapshot.nodes.values(),
            key=lambda n: (-n.weighted_degree, -n.degree, n.label.lower()),
        ):
            if len(selected) >= max_nodes:
                break
            if node.id in selected:
                continue
            if not _node_matches(node, entity_type=entity_type, route=route):
                continue
            selected.append(node.id)
        return selected

    def _neighborhood_node_ids(
        self,
        snapshot: GraphSnapshot,
        *,
        node_id: str,
        depth: int,
        max_nodes: int,
        entity_type: str | None,
        route: str | None,
    ) -> list[str]:
        max_depth = max(0, min(depth, 3))
        selected: list[str] = [node_id]
        selected_set = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while queue and len(selected) < max_nodes:
            current, distance = queue.popleft()
            if distance >= max_depth:
                continue
            edges = sorted(
                snapshot.adjacency.get(current, []),
                key=lambda e: (-e.weight, _other_node_id(e, current).lower()),
            )
            for edge in edges:
                other_id = _other_node_id(edge, current)
                if other_id in selected_set:
                    continue
                other = snapshot.nodes.get(other_id)
                if not other or not _node_matches(other, entity_type=entity_type, route=route):
                    continue
                selected.append(other_id)
                selected_set.add(other_id)
                queue.append((other_id, distance + 1))
                if len(selected) >= max_nodes:
                    break
        return selected

    def _graph_payload(
        self,
        snapshot: GraphSnapshot,
        *,
        node_ids: list[str],
        max_edges: int,
    ) -> dict[str, Any]:
        selected = set(node_ids)
        edges = [
            edge
            for edge in snapshot.edges
            if edge.source in selected and edge.target in selected
        ]
        total_edges = len(edges)
        edges.sort(key=lambda e: (-e.weight, e.source.lower(), e.target.lower(), e.id))
        edges = edges[:max_edges]
        return {
            "nodes": [
                self._node_graph_dto(snapshot.nodes[node_id])
                for node_id in node_ids
                if node_id in snapshot.nodes
            ],
            "edges": [self._edge_graph_dto(edge) for edge in edges],
            "returned_nodes": len([node_id for node_id in node_ids if node_id in snapshot.nodes]),
            "returned_edges": len(edges),
            "truncated_edges": total_edges > len(edges),
        }

    def _node_graph_dto(self, node: GraphNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "label": node.label,
            "entity_type": node.entity_type,
            "routes": node.routes,
            "route_labels": node.route_labels,
            "source_families": node.source_families,
            "degree": node.degree,
            "weighted_degree": round(node.weighted_degree, 4),
            "description": _truncate(" ".join(node.descriptions), 360),
        }

    def _edge_graph_dto(self, edge: GraphEdge) -> dict[str, Any]:
        return {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "weight": edge.weight,
            "routes": edge.routes,
            "route_labels": edge.route_labels,
            "keywords": edge.keywords[:10],
            "description": _truncate(" ".join(edge.descriptions), 240),
        }

    def _node_card(
        self,
        node: GraphNode,
        *,
        score: float | None = None,
        snippet_query: str | None = None,
        include_full: bool = False,
    ) -> dict[str, Any]:
        descriptions = node.descriptions if include_full else node.descriptions[:3]
        payload: dict[str, Any] = {
            "id": node.id,
            "label": node.label,
            "entity_type": node.entity_type,
            "routes": node.routes,
            "route_labels": node.route_labels,
            "source_families": node.source_families,
            "degree": node.degree,
            "weighted_degree": round(node.weighted_degree, 4),
            "description": _truncate(" ".join(descriptions), 1100 if include_full else 420),
            "source_files": node.source_files[:60 if include_full else 8],
            "source_ids": node.source_ids[:80 if include_full else 8],
            "obsidian_hints": [
                hint
                for hint in (_obsidian_hint(item) for item in node.source_files[:20 if include_full else 4])
                if hint is not None
            ],
            "prepared_queries": _prepared_queries(node),
        }
        if score is not None:
            payload["score"] = score
        if snippet_query:
            payload["snippet"] = _snippet(node.search_text, snippet_query)
        if include_full:
            payload["descriptions"] = node.descriptions
            payload["created_at"] = node.created_at
            payload["truncate"] = node.truncate
        return payload

    def _edge_card(
        self,
        edge: GraphEdge,
        *,
        include_description: bool = False,
        focus_node_id: str | None = None,
    ) -> dict[str, Any]:
        other_node_id = _other_node_id(edge, focus_node_id) if focus_node_id else None
        return {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "other_node_id": other_node_id,
            "weight": edge.weight,
            "keywords": edge.keywords[:20],
            "routes": edge.routes,
            "route_labels": edge.route_labels,
            "source_files": edge.source_files[:10],
            "description": _truncate(
                " ".join(edge.descriptions),
                540 if include_description else 180,
            ),
        }

    @staticmethod
    def _source_payload(state: SourceState) -> dict[str, Any]:
        return {
            "source_name": state.source_name,
            "exists": state.exists,
            "size_bytes": state.size_bytes,
            "mtime_ns": state.mtime_ns,
            "mtime_iso": state.mtime_iso,
            "metadata_hash": state.metadata_hash,
        }


def build_from_env() -> GraphExplorer:
    return GraphExplorer(os.getenv("DANTE_LIGHTRAG_GRAPHML_PATH", str(DEFAULT_GRAPHML_PATH)))


def _parse_graphml(path: Path, *, state: SourceState) -> GraphSnapshot:
    key_names: dict[str, str] = {}
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    adjacency: dict[str, list[GraphEdge]] = {}

    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            tag = _strip_namespace(elem.tag)
            if tag == "key":
                if len(key_names) >= MAX_GRAPH_KEYS:
                    raise GraphExplorerError("graph_key_limit_exceeded")
                key_id = elem.attrib.get("id")
                attr_name = elem.attrib.get("attr.name")
                if key_id and attr_name:
                    key_names[_safe_text(key_id, 180)] = _safe_text(attr_name, 180)
                elem.clear()
            elif tag == "node":
                if len(nodes) >= MAX_GRAPH_NODES:
                    raise GraphExplorerError("graph_node_limit_exceeded")
                node = _parse_node(elem, key_names)
                nodes[node.id] = node
                elem.clear()
            elif tag == "edge":
                if len(edges) >= MAX_GRAPH_EDGES:
                    raise GraphExplorerError("graph_edge_limit_exceeded")
                edge = _parse_edge(elem, key_names, edge_index=len(edges))
                edges.append(edge)
                adjacency.setdefault(edge.source, []).append(edge)
                adjacency.setdefault(edge.target, []).append(edge)
                elem.clear()
    except ET.ParseError as exc:
        raise GraphExplorerError("graph_parse_error") from exc

    for edge in edges:
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if not source or not target:
            continue
        source.degree += 1
        target.degree += 1
        source.weighted_degree += edge.weight
        target.weighted_degree += edge.weight
        source.edge_ids.append(edge.id)
        target.edge_ids.append(edge.id)
        source.neighbors.add(target.id)
        target.neighbors.add(source.id)

    entity_type_counts = Counter(node.entity_type for node in nodes.values())
    route_counts: Counter[str] = Counter()
    source_family_counts: Counter[str] = Counter()
    for node in nodes.values():
        route_counts.update(node.routes or ["unrouted"])
        source_family_counts.update(node.source_families or ["unknown"])

    return GraphSnapshot(
        state=state,
        loaded_at_iso=datetime.now(timezone.utc).isoformat(),
        nodes=nodes,
        edges=edges,
        adjacency=adjacency,
        entity_type_counts=dict(entity_type_counts),
        route_counts=dict(route_counts),
        source_family_counts=dict(source_family_counts),
    )


def _parse_node(elem: ET.Element, key_names: dict[str, str]) -> GraphNode:
    attrs = _data_attrs(elem, key_names)
    source_files = [_safe_source_hint(item) for item in _split(attrs.get("file_path"))]
    source_ids = _split(attrs.get("source_id"))
    descriptions = _split(attrs.get("description"))
    label = _safe_text(attrs.get("entity_id") or elem.attrib.get("id") or "")
    node_id = _safe_text(elem.attrib.get("id") or label)
    entity_type = _safe_text(attrs.get("entity_type") or "unknown", 160).lower()
    routes = _infer_routes([node_id, label, entity_type, *source_files, *descriptions[:3]])
    source_families = _infer_source_families(source_files, node_id=node_id)
    node = GraphNode(
        id=node_id,
        label=label or node_id,
        entity_type=entity_type,
        descriptions=descriptions,
        source_ids=source_ids,
        source_files=source_files,
        created_at=_safe_text(attrs.get("created_at"), 120) or None,
        truncate=_safe_text(attrs.get("truncate"), 120) or None,
        routes=routes,
        route_labels=[_route_label(route_id) for route_id in routes],
        source_families=source_families,
    )
    node.search_text = " ".join(
        [
            node.id,
            node.label,
            node.entity_type,
            " ".join(node.descriptions),
            " ".join(node.source_files),
            " ".join(node.source_ids),
            " ".join(node.routes),
            " ".join(node.route_labels),
            " ".join(node.source_families),
        ]
    ).lower()
    return node


def _parse_edge(elem: ET.Element, key_names: dict[str, str], *, edge_index: int) -> GraphEdge:
    attrs = _data_attrs(elem, key_names)
    source_files = [_safe_source_hint(item) for item in _split(attrs.get("file_path"))]
    descriptions = _split(attrs.get("description"))
    keywords = _split_keywords(attrs.get("keywords"))
    source = _safe_text(elem.attrib.get("source", ""))
    target = _safe_text(elem.attrib.get("target", ""))
    routes = _infer_routes([source, target, *source_files, *descriptions[:2], *keywords])
    edge = GraphEdge(
        id=_safe_text(elem.attrib.get("id") or f"e{edge_index}", 240),
        source=source,
        target=target,
        weight=_to_float(attrs.get("weight"), default=1.0),
        descriptions=descriptions,
        keywords=keywords,
        source_ids=_split(attrs.get("source_id")),
        source_files=source_files,
        created_at=_safe_text(attrs.get("created_at"), 120) or None,
        truncate=_safe_text(attrs.get("truncate"), 120) or None,
        routes=routes,
        route_labels=[_route_label(route_id) for route_id in routes],
        source_families=_infer_source_families(source_files, node_id=f"{source} {target}"),
    )
    edge.search_text = " ".join(
        [
            edge.source,
            edge.target,
            " ".join(edge.descriptions),
            " ".join(edge.keywords),
            " ".join(edge.source_files),
            " ".join(edge.routes),
        ]
    ).lower()
    return edge


def _data_attrs(elem: ET.Element, key_names: dict[str, str]) -> dict[str, str | None]:
    attrs: dict[str, str | None] = {}
    count = 0
    for child in elem:
        if _strip_namespace(child.tag) != "data":
            continue
        count += 1
        if count > MAX_DATA_FIELDS:
            raise GraphExplorerError("graph_data_field_limit_exceeded")
        key = _safe_text(child.attrib.get("key") or "", 180)
        name = key_names.get(key, key)
        attrs[name] = _safe_text(child.text)
    return attrs


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value.split(SEP):
        item = _safe_text(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def _split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    parts: list[str] = []
    for chunk in value.split(SEP):
        parts.extend(piece.strip() for piece in chunk.split(","))
    seen: set[str] = set()
    result: list[str] = []
    for item in parts:
        clean = _safe_text(item, 220)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
        if len(result) >= MAX_LIST_ITEMS:
            break
    return result


def _reject_unsafe_xml(path: Path) -> None:
    needles = (b"<!doctype", b"<!entity")
    tail = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            window = (tail + chunk).lower()
            if any(needle in window for needle in needles):
                raise GraphExplorerError("graph_xml_unsafe_declaration")
            tail = window[-32:]


def _safe_text(value: str | None, max_chars: int = MAX_FIELD_CHARS) -> str:
    if not value:
        return ""
    text = CONTROL_CHARS_RE.sub(" ", str(value))
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _safe_source_hint(value: str) -> str:
    text = _safe_text(value, 1200)
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if normalized.startswith("/") or normalized.startswith("~") or ".." in parts:
        return Path(normalized).name or "[redacted-path]"
    return normalized


def _is_safe_relative_path(value: str) -> bool:
    if not value or value.startswith("/") or value.startswith("~"):
        return False
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    return ".." not in parts


def _infer_routes(parts: list[str]) -> list[str]:
    haystack = " ".join(parts).lower()
    routes = [rule.id for rule in ROUTE_RULES if any(pattern in haystack for pattern in rule.patterns)]
    if not routes:
        return ["unrouted"]
    return routes


def _infer_source_families(source_files: list[str], *, node_id: str) -> list[str]:
    families: set[str] = set()
    haystack = " ".join([node_id, *source_files]).lower()
    if "visual-analysis-cards" in haystack:
        families.add("visual-analysis-cards")
    if "source-routing__" in haystack or "source-routing" in haystack:
        families.add("source-routing")
    if "routecap" in haystack:
        families.add("routing-capsule")
    if "routegrp" in haystack:
        families.add("routing-group")
    if "readme.md" in haystack or "index.md" in haystack or "moc.md" in haystack:
        families.add("core-pack")
    if "source-assets" in haystack or "film-stills/" in haystack:
        families.add("visual-assets")
    return sorted(families) if families else ["black-label"]


def _route_label(route_id: str) -> str:
    for rule in ROUTE_RULES:
        if rule.id == route_id:
            return rule.label
    if route_id == "unrouted":
        return "Unrouted"
    return route_id.replace("-", " ").title()


def _score_node(node: GraphNode, *, query_lc: str, tokens: list[str]) -> float:
    text = node.search_text
    label_lc = node.label.lower()
    score = 0.0
    if query_lc == label_lc:
        score += 200.0
    if query_lc in label_lc:
        score += 90.0
    if query_lc in text:
        score += 35.0
    for token in tokens:
        if token in label_lc:
            score += 18.0
        elif token in text:
            score += 4.0
    if score:
        score += min(node.weighted_degree, 100.0) / 25.0
    return score


def _node_matches(node: GraphNode, *, entity_type: str | None, route: str | None) -> bool:
    return (not entity_type or node.entity_type == entity_type) and (not route or route in node.routes)


def _sorted_count_items(counts: dict[str, int], *, limit: int) -> list[dict[str, Any]]:
    return [
        {"id": key, "label": _route_label(key), "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _other_node_id(edge: GraphEdge, node_id: str | None) -> str:
    if node_id == edge.source:
        return edge.target
    if node_id == edge.target:
        return edge.source
    return edge.target


def _prepared_queries(node: GraphNode) -> list[dict[str, str]]:
    route_text = ", ".join(node.route_labels[:3])
    return [
        {
            "surface": "Knowledge Hub",
            "query": f"{DEFAULT_DATASET_ID} {node.label} {route_text}".strip(),
        },
        {"surface": "LightRAG", "query": node.label},
        {
            "surface": "Obsidian",
            "query": f"{node.label} source:{node.source_files[0]}" if node.source_files else node.label,
        },
    ]


def _obsidian_hint(source_file: str) -> dict[str, str] | None:
    rel = _safe_source_hint(source_file)
    if not rel:
        return None
    if "--" in rel:
        rel = rel.split("--", 1)[1]
    rel = rel.replace("__", "/")
    if not rel.startswith(DEFAULT_DATASET_ID):
        rel = f"{DEFAULT_DATASET_ID}/{rel}"
    if not _is_safe_relative_path(rel):
        return None
    return {
        "source_file": source_file,
        "best_effort_rel_path": rel,
        "obsidian_uri": f"obsidian://open?vault=Dante&file={quote(rel)}",
    }


def _snippet(text: str, query_lc: str, *, size: int = 260) -> str:
    if not text:
        return ""
    idx = text.find(query_lc)
    if idx < 0:
        return _truncate(text, size)
    start = max(0, idx - size // 3)
    end = min(len(text), start + size)
    return _truncate(text[start:end], size)


def _truncate(value: str, max_chars: int) -> str:
    text = _safe_text(value, max_chars * 2)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _to_float(value: str | None, *, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
