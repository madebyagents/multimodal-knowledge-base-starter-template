import { useEffect, useRef } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import type { GraphPayload, GraphVisualNode } from "@/lib/api";

const ROUTE_COLORS: Record<string, string> = {
  "core-pack": "#b6ff9d",
  "source-routing": "#ffd86b",
  "visual-analysis-cards": "#bca7ff",
  "visual-reference-assets": "#74d9ff",
  "treatment-ppm-pitch": "#ffb46b",
  "craft-field-manuals": "#88e18b",
  "commercial-verticals": "#ff8db3",
  "director-tools": "#93a9ff",
  "qc-repair": "#f07a6d",
  "ai-systems": "#7ee7d4",
  unrouted: "#8c96a8",
};

export function GraphCanvas({
  payload,
  selectedNodeId,
  onSelectNode,
}: {
  payload: GraphPayload;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const rendererRef = useRef<Sigma | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || payload.nodes.length === 0) return;

    const graph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
    const nodeRank = new Map(payload.nodes.map((node, index) => [node.id, index]));
    const radius = Math.max(2, Math.sqrt(payload.nodes.length) * 2.2);

    payload.nodes.forEach((node, index) => {
      const angle = (index / Math.max(payload.nodes.length, 1)) * Math.PI * 2;
      const degreeBoost = Math.min(node.weighted_degree || node.degree || 1, 50) / 50;
      const nodeRadius = radius * (0.65 + degreeBoost * 0.45);
      const color = routeColor(node);
      graph.addNode(node.id, {
        x: Math.cos(angle) * nodeRadius,
        y: Math.sin(angle) * nodeRadius,
        label: node.label,
        size: Math.max(3, Math.min(13, 3 + Math.sqrt(node.degree + 1))),
        baseSize: Math.max(3, Math.min(13, 3 + Math.sqrt(node.degree + 1))),
        color,
        baseColor: color,
        highlighted: false,
        route: node.routes[0] ?? "unrouted",
      });
    });

    payload.edges.forEach((edge, index) => {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) return;
      const edgeKey = graph.hasEdge(edge.id) ? `${edge.id}-${index}` : edge.id;
      graph.addEdgeWithKey(edgeKey, edge.source, edge.target, {
        label: edge.keywords.slice(0, 2).join(", "),
        size: Math.max(0.6, Math.min(4, Math.sqrt(edge.weight || 1))),
        baseSize: Math.max(0.6, Math.min(4, Math.sqrt(edge.weight || 1))),
        color: "rgba(183, 195, 214, 0.26)",
        baseColor: "rgba(183, 195, 214, 0.26)",
        weight: edge.weight,
        route: edge.routes[0] ?? "unrouted",
      });
    });

    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!prefersReducedMotion && payload.nodes.length <= 280) {
      try {
        forceAtlas2.assign(graph, {
          iterations: payload.nodes.length < 120 ? 95 : 55,
          settings: {
            gravity: 1.2,
            scalingRatio: 8,
            slowDown: 3,
            edgeWeightInfluence: 0.35,
            barnesHutOptimize: payload.nodes.length > 160,
          },
        });
      } catch {
        // Deterministic radial positions are already assigned; keep the graph usable.
      }
    } else {
      graph.forEachNode((nodeId) => {
        const index = nodeRank.get(nodeId) ?? 0;
        const ring = 1 + (index % 5) * 0.18;
        const angle = (index / Math.max(payload.nodes.length, 1)) * Math.PI * 2;
        graph.setNodeAttribute(nodeId, "x", Math.cos(angle) * radius * ring);
        graph.setNodeAttribute(nodeId, "y", Math.sin(angle) * radius * ring);
      });
    }

    const renderer = new Sigma(graph, container, {
      allowInvalidContainer: true,
      defaultNodeColor: "#b6ff9d",
      defaultEdgeColor: "rgba(183, 195, 214, 0.24)",
      renderEdgeLabels: false,
      labelDensity: 0.08,
      labelGridCellSize: 80,
      labelRenderedSizeThreshold: 8,
      zIndex: true,
    });

    renderer.on("clickNode", ({ node }) => onSelectNode(node));
    renderer.on("clickStage", () => onSelectNode(null));

    graphRef.current = graph;
    rendererRef.current = renderer;

    return () => {
      renderer.kill();
      graph.clear();
      graphRef.current = null;
      rendererRef.current = null;
      container.innerHTML = "";
    };
  }, [onSelectNode, payload]);

  useEffect(() => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (!graph || !renderer) return;
    const neighbors = new Set<string>();
    if (selectedNodeId && graph.hasNode(selectedNodeId)) {
      graph.forEachNeighbor(selectedNodeId, (neighbor) => neighbors.add(neighbor));
    }
    graph.forEachNode((nodeId, attrs) => {
      const selected = selectedNodeId === nodeId;
      const adjacent = neighbors.has(nodeId);
      const baseSize = Number(attrs.baseSize ?? attrs.size ?? 3);
      graph.setNodeAttribute(nodeId, "color", selected ? "#ffffff" : adjacent ? "#d9ffc8" : attrs.baseColor);
      graph.setNodeAttribute(nodeId, "size", selected ? 16 : adjacent ? Math.max(baseSize, 10) : baseSize);
      graph.setNodeAttribute(nodeId, "zIndex", selected ? 10 : adjacent ? 6 : 1);
    });
    graph.forEachEdge((edgeId, attrs, source, target) => {
      const baseSize = Number(attrs.baseSize ?? attrs.size ?? 1);
      const active =
        selectedNodeId == null ||
        source === selectedNodeId ||
        target === selectedNodeId ||
        (neighbors.has(source) && neighbors.has(target));
      graph.setEdgeAttribute(
        edgeId,
        "color",
        active ? "rgba(207, 255, 185, 0.46)" : "rgba(137, 148, 169, 0.12)",
      );
      graph.setEdgeAttribute(edgeId, "size", active ? Math.max(baseSize, 1.4) : Math.max(baseSize * 0.65, 0.4));
      graph.setEdgeAttribute(edgeId, "zIndex", active ? 4 : 0);
    });
    renderer.refresh();
  }, [selectedNodeId]);

  if (payload.nodes.length === 0) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-md border border-dashed border-border/70 bg-background/30 text-sm text-muted-foreground">
        No graph nodes in this bounded view.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={`Visual graph with ${payload.returned_nodes} nodes and ${payload.returned_edges} edges`}
      className="graph-canvas h-full min-h-[420px] w-full rounded-md border border-border/70 bg-background/50"
    />
  );
}

function routeColor(node: GraphVisualNode): string {
  for (const route of node.routes) {
    if (ROUTE_COLORS[route]) return ROUTE_COLORS[route];
  }
  return ROUTE_COLORS.unrouted;
}
