import { useQuery } from "@tanstack/react-query";
import {
  api,
  type GraphHealthResponse,
  type GraphNodeDetail,
  type GraphSearchResponse,
  type GraphSubgraphResponse,
  type GraphSummaryResponse,
} from "@/lib/api";

export function useGraphHealth(args?: { load?: boolean }) {
  const load = args?.load ?? false;
  return useQuery<GraphHealthResponse>({
    queryKey: ["graph-health", load],
    queryFn: () => api.graphHealth({ load }),
    staleTime: 30_000,
    retry: 1,
  });
}

export function useGraphSummary(args?: {
  enabled?: boolean;
  topNodesLimit?: number;
  maxNodes?: number;
  maxEdges?: number;
}) {
  const enabled = args?.enabled ?? true;
  const topNodesLimit = args?.topNodesLimit ?? 40;
  const maxNodes = args?.maxNodes ?? 700;
  const maxEdges = args?.maxEdges ?? 1400;
  return useQuery<GraphSummaryResponse>({
    queryKey: ["graph-summary", topNodesLimit, maxNodes, maxEdges],
    queryFn: () =>
      api.graphSummary({
        top_nodes_limit: topNodesLimit,
        max_nodes: maxNodes,
        max_edges: maxEdges,
      }),
    enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useGraphSearch(args: {
  query: string;
  limit?: number;
  entityType?: string | null;
  route?: string | null;
  enabled?: boolean;
}) {
  const query = args.query.trim();
  const limit = args.limit ?? 20;
  const entityType = args.entityType ?? null;
  const route = args.route ?? null;
  const enabled = (args.enabled ?? true) && query.length > 0;
  return useQuery<GraphSearchResponse>({
    queryKey: ["graph-search", query, limit, entityType, route],
    queryFn: () =>
      api.graphSearch({
        q: query,
        limit,
        entity_type: entityType,
        route,
      }),
    enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useGraphSubgraph(args: {
  nodeId?: string | null;
  depth?: number;
  maxNodes?: number;
  maxEdges?: number;
  entityType?: string | null;
  route?: string | null;
  enabled?: boolean;
}) {
  const nodeId = args.nodeId ?? null;
  const depth = args.depth ?? 1;
  const maxNodes = args.maxNodes ?? 220;
  const maxEdges = args.maxEdges ?? 900;
  const entityType = args.entityType ?? null;
  const route = args.route ?? null;
  const enabled = args.enabled ?? true;
  return useQuery<GraphSubgraphResponse>({
    queryKey: ["graph-subgraph", nodeId, depth, maxNodes, maxEdges, entityType, route],
    queryFn: () =>
      api.graphSubgraph({
        node_id: nodeId,
        depth,
        max_nodes: maxNodes,
        max_edges: maxEdges,
        entity_type: entityType,
        route,
      }),
    enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useGraphNode(args: {
  nodeId?: string | null;
  edgeLimit?: number;
  enabled?: boolean;
}) {
  const nodeId = args.nodeId ?? null;
  const edgeLimit = args.edgeLimit ?? 80;
  const enabled = (args.enabled ?? true) && nodeId != null;
  return useQuery<GraphNodeDetail>({
    queryKey: ["graph-node", nodeId, edgeLimit],
    queryFn: () => api.graphNode(nodeId as string, { edge_limit: edgeLimit }),
    enabled,
    staleTime: 60_000,
    retry: 1,
  });
}
