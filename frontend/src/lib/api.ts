// Typed API client mirroring backend/app/schemas.py.

export interface SearchResult {
  node_id: string;
  score: number;
  modality: string;
  display_name: string;
  file_id: string;
  metadata: Record<string, unknown>;
  snippet: string;
  preview_url: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
}

export interface IngestItem {
  file_id: string;
  original_name: string;
  modality: string;
  node_ids: string[];
  total_pages?: number | null;
  duration_seconds?: number | null;
  preview_url?: string | null;
}

export interface IngestResponse {
  items: IngestItem[];
  total: number;
}

export interface Item {
  file_id: string;
  original_name: string;
  modality: string;
  upload_time: string;
  node_ids: string[];
  preview_url: string | null;
}

export interface ItemsResponse {
  items: Item[];
  total: number;
  returned: number;
  limit: number | null;
  offset: number;
}

export interface Stats {
  total: number;
  by_modality: Record<string, number>;
}

export interface GraphSource {
  source_name: string;
  exists: boolean;
  size_bytes: number | null;
  mtime_ns: number | null;
  mtime_iso: string | null;
  metadata_hash: string | null;
}

export interface GraphCache {
  loaded: boolean;
  fresh: boolean;
  stale: boolean;
  loaded_at: string | null;
  metadata_hash: string | null;
}

export interface GraphCountItem {
  id: string;
  label: string;
  count: number;
}

export interface GraphObsidianHint {
  source_file: string;
  best_effort_rel_path: string;
  obsidian_uri: string;
}

export interface GraphPreparedQuery {
  surface: string;
  query: string;
}

export interface GraphNodeCard {
  id: string;
  label: string;
  entity_type: string;
  routes: string[];
  route_labels: string[];
  source_families: string[];
  degree: number;
  weighted_degree: number;
  description: string;
  source_files: string[];
  source_ids: string[];
  obsidian_hints: GraphObsidianHint[];
  prepared_queries: GraphPreparedQuery[];
  score?: number | null;
  snippet?: string | null;
}

export interface GraphEdgeCard {
  id: string;
  source: string;
  target: string;
  other_node_id: string | null;
  weight: number;
  keywords: string[];
  routes: string[];
  route_labels: string[];
  source_files: string[];
  description: string;
}

export interface GraphNodeDetail extends GraphNodeCard {
  descriptions: string[];
  created_at: string | null;
  truncate: string | null;
  adjacent_edges: GraphEdgeCard[];
}

export interface GraphVisualNode {
  id: string;
  label: string;
  entity_type: string;
  routes: string[];
  route_labels: string[];
  source_families: string[];
  degree: number;
  weighted_degree: number;
  description: string;
}

export interface GraphVisualEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
  routes: string[];
  route_labels: string[];
  keywords: string[];
  description: string;
}

export interface GraphPayload {
  nodes: GraphVisualNode[];
  edges: GraphVisualEdge[];
  returned_nodes: number;
  returned_edges: number;
  truncated_edges: boolean;
}

export interface GraphHealthResponse {
  ok: boolean;
  dataset_id: string;
  source: GraphSource;
  loaded: boolean;
  cache: GraphCache;
  node_count: number | null;
  edge_count: number | null;
  loaded_at: string | null;
  read_only: boolean;
  error: string | null;
}

export interface GraphSummaryResponse {
  dataset_id: string;
  source: GraphSource;
  cache: GraphCache;
  node_count: number;
  edge_count: number;
  entity_type_counts: GraphCountItem[];
  route_counts: GraphCountItem[];
  source_family_counts: GraphCountItem[];
  top_nodes: GraphNodeCard[];
  graph: GraphPayload;
}

export interface GraphSearchResponse {
  query: string;
  results: GraphNodeCard[];
}

export interface GraphSubgraphResponse {
  dataset_id: string;
  center: GraphNodeCard | null;
  depth: number;
  graph: GraphPayload;
}

export interface Project {
  id: string;
  name: string;
  memory: string;
  instructions: string;
  created_at: string;
  updated_at: string;
  thread_count: number;
  latest_thread_at: string | null;
}

export interface ProjectsResponse {
  projects: Project[];
}

export interface ChatThread {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  chat_model: string | null;
  top_k: number | null;
  archived: boolean;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ThreadsResponse {
  threads: ChatThread[];
}

export interface PersistedChatMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  chat_model: string | null;
  top_k: number | null;
  status: string;
  visual_attachments: number;
  citation_validation?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  sources: SearchResult[];
}

export interface ThreadDetail extends ChatThread {
  project: Project;
  messages: PersistedChatMessage[];
}

export interface WorkspaceBootstrapResponse {
  project: Project;
  thread: ChatThread;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }
}

export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async bootstrapWorkspace(): Promise<WorkspaceBootstrapResponse> {
    return jsonOrThrow(
      await fetch("/api/workspace/bootstrap", { method: "POST" }),
    );
  },

  async projects(): Promise<ProjectsResponse> {
    return jsonOrThrow(await fetch("/api/projects"));
  },

  async createProject(args: { name: string }): Promise<Project> {
    return jsonOrThrow(
      await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args),
      }),
    );
  },

  async updateProject(
    projectId: string,
    args: { name?: string; memory?: string; instructions?: string },
  ): Promise<Project> {
    return jsonOrThrow(
      await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args),
      }),
    );
  },

  async threads(
    projectId: string,
    args?: { include_archived?: boolean },
  ): Promise<ThreadsResponse> {
    const params = new URLSearchParams();
    if (args?.include_archived) params.set("include_archived", "true");
    const query = params.toString();
    return jsonOrThrow(
      await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/threads${query ? `?${query}` : ""}`,
      ),
    );
  },

  async createThread(args: {
    project_id: string;
    title?: string;
    chat_model?: string | null;
    top_k?: number | null;
  }): Promise<ChatThread> {
    return jsonOrThrow(
      await fetch("/api/threads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args),
      }),
    );
  },

  async updateThread(
    threadId: string,
    args: {
      title?: string;
      summary?: string;
      chat_model?: string | null;
      top_k?: number | null;
      archived?: boolean;
      pinned?: boolean;
    },
  ): Promise<ChatThread> {
    return jsonOrThrow(
      await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args),
      }),
    );
  },

  async thread(threadId: string): Promise<ThreadDetail> {
    return jsonOrThrow(await fetch(`/api/threads/${encodeURIComponent(threadId)}`));
  },

  async stats(): Promise<Stats> {
    return jsonOrThrow(await fetch("/api/stats"));
  },

  async graphHealth(args?: { load?: boolean }): Promise<GraphHealthResponse> {
    const params = new URLSearchParams();
    if (args?.load) params.set("load", "true");
    const query = params.toString();
    return jsonOrThrow(await fetch(`/api/graph/health${query ? `?${query}` : ""}`));
  },

  async graphSummary(args?: {
    top_nodes_limit?: number;
    max_nodes?: number;
    max_edges?: number;
  }): Promise<GraphSummaryResponse> {
    const params = new URLSearchParams();
    if (args?.top_nodes_limit != null) {
      params.set("top_nodes_limit", String(args.top_nodes_limit));
    }
    if (args?.max_nodes != null) params.set("max_nodes", String(args.max_nodes));
    if (args?.max_edges != null) params.set("max_edges", String(args.max_edges));
    const query = params.toString();
    return jsonOrThrow(await fetch(`/api/graph/summary${query ? `?${query}` : ""}`));
  },

  async graphSearch(args: {
    q: string;
    limit?: number;
    entity_type?: string | null;
    route?: string | null;
  }): Promise<GraphSearchResponse> {
    const params = new URLSearchParams({ q: args.q });
    if (args.limit != null) params.set("limit", String(args.limit));
    if (args.entity_type) params.set("entity_type", args.entity_type);
    if (args.route) params.set("route", args.route);
    return jsonOrThrow(await fetch(`/api/graph/search?${params.toString()}`));
  },

  async graphSubgraph(args?: {
    node_id?: string | null;
    depth?: number;
    max_nodes?: number;
    max_edges?: number;
    entity_type?: string | null;
    route?: string | null;
  }): Promise<GraphSubgraphResponse> {
    const params = new URLSearchParams();
    if (args?.node_id) params.set("node_id", args.node_id);
    if (args?.depth != null) params.set("depth", String(args.depth));
    if (args?.max_nodes != null) params.set("max_nodes", String(args.max_nodes));
    if (args?.max_edges != null) params.set("max_edges", String(args.max_edges));
    if (args?.entity_type) params.set("entity_type", args.entity_type);
    if (args?.route) params.set("route", args.route);
    const query = params.toString();
    return jsonOrThrow(await fetch(`/api/graph/subgraph${query ? `?${query}` : ""}`));
  },

  async graphNode(
    nodeId: string,
    args?: { edge_limit?: number },
  ): Promise<GraphNodeDetail> {
    const params = new URLSearchParams();
    if (args?.edge_limit != null) params.set("edge_limit", String(args.edge_limit));
    const query = params.toString();
    return jsonOrThrow(
      await fetch(
        `/api/graph/node/${encodeURIComponent(nodeId)}${query ? `?${query}` : ""}`,
      ),
    );
  },

  async items(args?: {
    limit?: number | null;
    offset?: number;
  }): Promise<ItemsResponse> {
    const params = new URLSearchParams();
    if (args?.limit != null) params.set("limit", String(args.limit));
    if (args?.offset != null && args.offset > 0) {
      params.set("offset", String(args.offset));
    }
    const query = params.toString();
    return jsonOrThrow(await fetch(`/api/items${query ? `?${query}` : ""}`));
  },

  async search(args: {
    query: string;
    top_k?: number;
    modality_filter?: string[] | null;
  }): Promise<SearchResponse> {
    return jsonOrThrow(
      await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args),
      }),
    );
  },

  async searchImage(args: {
    file: File;
    top_k?: number;
    modality_filter?: string[];
  }): Promise<SearchResponse> {
    const form = new FormData();
    form.append("file", args.file);
    if (args.top_k != null) form.append("top_k", String(args.top_k));
    if (args.modality_filter?.length) {
      form.append("modality_filter", args.modality_filter.join(","));
    }
    return jsonOrThrow(
      await fetch("/api/search/image", { method: "POST", body: form }),
    );
  },

  async ingest(args: {
    files: File[];
    tags?: string;
    video_frame_interval_s?: number;
  }): Promise<IngestResponse> {
    const form = new FormData();
    for (const f of args.files) form.append("files", f);
    if (args.tags) form.append("tags", args.tags);
    if (args.video_frame_interval_s != null) {
      form.append(
        "video_frame_interval_s",
        String(args.video_frame_interval_s),
      );
    }
    return jsonOrThrow(
      await fetch("/api/ingest", { method: "POST", body: form }),
    );
  },

  async deleteItem(fileId: string): Promise<{ deleted: number }> {
    return jsonOrThrow(
      await fetch(`/api/items/${encodeURIComponent(fileId)}`, {
        method: "DELETE",
      }),
    );
  },

  async clear(): Promise<{ cleared: boolean }> {
    return jsonOrThrow(await fetch("/api/clear", { method: "POST" }));
  },
};
