from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graph_explorer import GraphExplorer
from app.routes.graph import get_graph_explorer, router


def write_graphml(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="n0" for="node" attr.name="entity_id" attr.type="string"/>
  <key id="n1" for="node" attr.name="entity_type" attr.type="string"/>
  <key id="n2" for="node" attr.name="description" attr.type="string"/>
  <key id="n3" for="node" attr.name="source_id" attr.type="string"/>
  <key id="n4" for="node" attr.name="file_path" attr.type="string"/>
  <key id="n5" for="node" attr.name="created_at" attr.type="string"/>
  <key id="e0" for="edge" attr.name="weight" attr.type="double"/>
  <key id="e1" for="edge" attr.name="description" attr.type="string"/>
  <key id="e2" for="edge" attr.name="keywords" attr.type="string"/>
  <key id="e3" for="edge" attr.name="source_id" attr.type="string"/>
  <key id="e4" for="edge" attr.name="file_path" attr.type="string"/>
  <graph edgedefault="undirected">
    <node id="Commercial-Film-Production-Kb">
      <data key="n0">Commercial-Film-Production-Kb</data>
      <data key="n1">content</data>
      <data key="n2">Core pack for Knowledge Hub retrieval&lt;SEP&gt;LightRAG Obsidian routing handoff</data>
      <data key="n3">chunk-root&lt;SEP&gt;chunk-route</data>
      <data key="n4">bl-root--README.md&lt;SEP&gt;bl-route--source-routing__04-treatment-ppm-pitch-source-routing.md</data>
      <data key="n5">1781459307</data>
    </node>
    <node id="visual/cards/aftersun-2022-001">
      <data key="n0">Visual Analysis Cards</data>
      <data key="n1">content</data>
      <data key="n2">Gemini visual cards for film stills</data>
      <data key="n3">chunk-visual</data>
      <data key="n4">bl-visual--visual-analysis-cards__film-stills__aftersun-2022__aftersun-2022-001.md</data>
    </node>
    <node id="Treatment PPM Pitch">
      <data key="n0">Treatment PPM Pitch</data>
      <data key="n1">concept</data>
      <data key="n2">Pitch and PPM routing capsule</data>
      <data key="n3">chunk-pitch</data>
      <data key="n4">/private/tmp/secret.md&lt;SEP&gt;../unsafe.md&lt;SEP&gt;bl-route--source-routing__04-treatment-ppm-pitch-source-routing.md</data>
    </node>
    <edge source="Commercial-Film-Production-Kb" target="visual/cards/aftersun-2022-001">
      <data key="e0">2.5</data>
      <data key="e1">Core pack exposes visual card routing</data>
      <data key="e2">routing,visual cards</data>
      <data key="e3">chunk-root</data>
      <data key="e4">bl-root--README.md</data>
    </edge>
    <edge source="Commercial-Film-Production-Kb" target="Treatment PPM Pitch">
      <data key="e0">1.25</data>
      <data key="e1">Core pack routes into pitch production</data>
      <data key="e2">pitch,ppm</data>
      <data key="e3">chunk-route</data>
      <data key="e4">bl-route--source-routing__04-treatment-ppm-pitch-source-routing.md</data>
    </edge>
  </graph>
</graphml>
""",
        encoding="utf-8",
    )


def graph_client(graphml: Path) -> TestClient:
    os.environ["DANTE_LIGHTRAG_GRAPHML_PATH"] = str(graphml)
    get_graph_explorer.cache_clear()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_graph_explorer_parses_sep_routes_and_sanitized_sources(tmp_path: Path) -> None:
    graphml = tmp_path / "graph.graphml"
    write_graphml(graphml)
    before = graphml.stat().st_mtime_ns
    explorer = GraphExplorer(graphml)

    summary = explorer.summary(max_nodes=10, max_edges=10)
    assert summary["node_count"] == 3
    assert summary["edge_count"] == 2
    assert summary["graph"]["returned_nodes"] == 3

    detail = explorer.node_detail("Commercial-Film-Production-Kb")
    assert detail["source_ids"] == ["chunk-root", "chunk-route"]
    assert detail["source_files"] == [
        "bl-root--README.md",
        "bl-route--source-routing__04-treatment-ppm-pitch-source-routing.md",
    ]
    assert "core-pack" in detail["routes"]
    assert "source-routing" in detail["routes"]
    assert "treatment-ppm-pitch" in detail["routes"]
    assert detail["obsidian_hints"][1]["best_effort_rel_path"].endswith(
        "source-routing/04-treatment-ppm-pitch-source-routing.md"
    )

    sanitized = explorer.node_detail("Treatment PPM Pitch")
    assert "/private" not in " ".join(sanitized["source_files"])
    assert ".." not in " ".join(sanitized["source_files"])
    assert graphml.stat().st_mtime_ns == before


def test_graph_explorer_cache_reports_fresh_and_stale(tmp_path: Path) -> None:
    graphml = tmp_path / "graph.graphml"
    write_graphml(graphml)
    explorer = GraphExplorer(graphml)

    loaded = explorer.health(load=True)
    assert loaded["cache"]["fresh"] is True
    assert loaded["cache"]["stale"] is False

    stat = graphml.stat()
    os.utime(graphml, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))

    stale = explorer.health()
    assert stale["cache"]["fresh"] is False
    assert stale["cache"]["stale"] is True


def test_graph_routes_are_bounded_redacted_and_support_slash_ids(tmp_path: Path) -> None:
    graphml = tmp_path / "graph.graphml"
    write_graphml(graphml)

    with graph_client(graphml) as client:
        health = client.get("/api/graph/health?load=true")
        assert health.status_code == 200
        health_payload = health.json()
        assert health_payload["node_count"] == 3
        assert health_payload["source"]["source_name"] == "graph.graphml"
        assert str(tmp_path) not in str(health_payload)
        assert "path" not in health_payload["source"]

        search = client.get("/api/graph/search", params={"q": "visual cards", "limit": 2})
        assert search.status_code == 200
        results = search.json()["results"]
        assert results[0]["id"] == "visual/cards/aftersun-2022-001"
        assert len(results) <= 2

        subgraph = client.get(
            "/api/graph/subgraph",
            params={"node_id": "Commercial-Film-Production-Kb", "depth": 1, "max_nodes": 10},
        )
        assert subgraph.status_code == 200
        payload = subgraph.json()["graph"]
        assert payload["returned_nodes"] == 3
        assert payload["returned_edges"] == 2

        slash_id = "visual/cards/aftersun-2022-001"
        detail = client.get(f"/api/graph/node/{quote(slash_id, safe='')}")
        assert detail.status_code == 200
        assert detail.json()["id"] == slash_id

    get_graph_explorer.cache_clear()


def test_missing_graph_source_health_is_non_crashing_and_load_routes_fail(tmp_path: Path) -> None:
    graphml = tmp_path / "missing.graphml"

    with graph_client(graphml) as client:
        health = client.get("/api/graph/health")
        assert health.status_code == 200
        assert health.json()["ok"] is False

        summary = client.get("/api/graph/summary")
        assert summary.status_code == 404
        assert summary.json()["detail"] == "graph_source_missing"

    get_graph_explorer.cache_clear()


def test_graph_rejects_unsafe_xml_declarations(tmp_path: Path) -> None:
    graphml = tmp_path / "graph.graphml"
    graphml.write_text(
        """<?xml version="1.0"?>
<!DOCTYPE graphml [<!ENTITY unsafe SYSTEM "file:///etc/passwd">]>
<graphml><graph><node id="x"><data key="n0">&unsafe;</data></node></graph></graphml>
""",
        encoding="utf-8",
    )

    with graph_client(graphml) as client:
        health = client.get("/api/graph/health?load=true")
        assert health.status_code == 200
        assert health.json()["ok"] is False
        assert health.json()["error"] == "graph_xml_unsafe_declaration"

        search = client.get("/api/graph/search", params={"q": "unsafe"})
        assert search.status_code == 503
        assert search.json()["detail"] == "graph_xml_unsafe_declaration"

    get_graph_explorer.cache_clear()
