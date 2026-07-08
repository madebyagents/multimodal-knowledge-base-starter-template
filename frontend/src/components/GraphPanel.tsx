import {
  Component,
  lazy,
  Suspense,
  useCallback,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Database,
  ExternalLink,
  GitBranch,
  Loader2,
  Network,
  Pause,
  Play,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  useGraphHealth,
  useGraphNode,
  useGraphSearch,
  useGraphSubgraph,
  useGraphSummary,
} from "@/hooks/useGraph";
import type { GraphNodeCard, GraphNodeDetail, GraphPayload } from "@/lib/api";

const LazyGraphCanvas = lazy(() =>
  import("@/components/GraphCanvas").then((module) => ({
    default: module.GraphCanvas,
  })),
);

export function GraphPanel() {
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [routeFilter, setRouteFilter] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [visualEnabled, setVisualEnabled] = useState(false);
  const [visualErrorKey, setVisualErrorKey] = useState(0);

  const health = useGraphHealth();
  const graphExists = health.data?.source.exists === true;
  const summary = useGraphSummary({
    enabled: graphExists,
    topNodesLimit: 48,
    maxNodes: 700,
    maxEdges: 1400,
  });
  const search = useGraphSearch({
    query: submitted,
    limit: 30,
    entityType: entityFilter || null,
    route: routeFilter || null,
    enabled: graphExists,
  });
  const subgraph = useGraphSubgraph({
    nodeId: selectedNodeId,
    depth: 1,
    maxNodes: 260,
    maxEdges: 900,
    entityType: entityFilter || null,
    route: routeFilter || null,
    enabled: graphExists && selectedNodeId != null,
  });
  const nodeDetail = useGraphNode({
    nodeId: selectedNodeId,
    edgeLimit: 80,
    enabled: graphExists && selectedNodeId != null,
  });

  const routeOptions = summary.data?.route_counts ?? [];
  const entityOptions = summary.data?.entity_type_counts ?? [];
  const resultNodes = submitted.trim()
    ? (search.data?.results ?? [])
    : (summary.data?.top_nodes ?? []);
  const visualPayload = selectedNodeId && subgraph.data ? subgraph.data.graph : summary.data?.graph;
  const statusText = statusLabel({
    graphExists,
    healthLoading: health.isLoading,
    summaryLoading: summary.isLoading,
    error: health.data?.error ?? null,
    cacheLoaded: health.data?.cache.loaded ?? false,
    cacheFresh: health.data?.cache.fresh ?? false,
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(draft.trim());
  };

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
  }, []);

  const resetVisualError = () => setVisualErrorKey((value) => value + 1);

  const selectedCard = useMemo(() => {
    if (!selectedNodeId) return null;
    return (
      nodeDetail.data ??
      search.data?.results.find((node) => node.id === selectedNodeId) ??
      summary.data?.top_nodes.find((node) => node.id === selectedNodeId) ??
      subgraph.data?.center ??
      null
    );
  }, [nodeDetail.data, search.data?.results, selectedNodeId, subgraph.data?.center, summary.data?.top_nodes]);

  return (
    <section className="flex h-full min-w-0 flex-col gap-4">
      <header className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">Graph</h2>
          <p className="max-w-full break-words text-sm text-muted-foreground">
            Black Label LightRAG map, read-only.
          </p>
        </div>
        <div
          aria-live="polite"
          className={cn(
            "inline-flex w-fit items-center gap-2 rounded-md border px-2.5 py-1 text-xs",
            graphExists
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-destructive/35 bg-destructive/10 text-destructive",
          )}
        >
          <Database className="h-3.5 w-3.5" />
          {statusText}
        </div>
      </header>

      <div className="slack-panel grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[320px_minmax(0,1fr)_330px]">
        <aside className="comfortable-scrollbar min-h-0 overflow-y-auto border-b border-border/70 p-4 lg:border-b-0 lg:border-r">
          <form onSubmit={onSubmit} className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Search graph..."
                className="slack-panel-input pl-9"
                autoComplete="off"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button type="submit" disabled={!draft.trim() || !graphExists}>
                Search
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!submitted}
                onClick={() => {
                  setDraft("");
                  setSubmitted("");
                }}
              >
                Clear
              </Button>
            </div>
            <div className="grid grid-cols-1 gap-2">
              <label className="space-y-1 text-xs text-muted-foreground">
                Route
                <select
                  value={routeFilter}
                  onChange={(event) => setRouteFilter(event.target.value)}
                  disabled={!graphExists}
                  className="slack-panel-input h-9 w-full rounded-md border border-input bg-background px-2 text-xs"
                >
                  <option value="">All routes</option>
                  {routeOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} ({item.count})
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                Entity
                <select
                  value={entityFilter}
                  onChange={(event) => setEntityFilter(event.target.value)}
                  disabled={!graphExists}
                  className="slack-panel-input h-9 w-full rounded-md border border-input bg-background px-2 text-xs"
                >
                  <option value="">All entities</option>
                  {entityOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} ({item.count})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </form>

          {(routeFilter || entityFilter) && (
            <div className="mt-3 flex flex-wrap gap-2">
              {routeFilter && (
                <FilterChip
                  label={routeOptions.find((item) => item.id === routeFilter)?.label ?? routeFilter}
                  onClear={() => setRouteFilter("")}
                />
              )}
              {entityFilter && <FilterChip label={entityFilter} onClear={() => setEntityFilter("")} />}
            </div>
          )}

          <div className="mt-5 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                {submitted ? "Results" : "Top Nodes"}
              </h3>
              {(search.isFetching || summary.isFetching) && (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              )}
            </div>
            {!graphExists ? (
              <InlineState
                icon={AlertTriangle}
                title="Graph source unavailable"
                description="Graph APIs are ready, but the external GraphML source was not found."
              />
            ) : summary.isError || search.isError ? (
              <InlineState
                icon={AlertTriangle}
                title="Graph read failed"
                description="The graph source could not be read safely."
              />
            ) : resultNodes.length === 0 ? (
              <InlineState
                icon={Network}
                title={submitted ? "No matches" : "Loading graph"}
                description={submitted ? "Try another query or filter." : "Top nodes will appear here."}
              />
            ) : (
              <div className="space-y-2">
                {resultNodes.map((node) => (
                  <NodeRow
                    key={node.id}
                    node={node}
                    active={selectedNodeId === node.id}
                    onClick={() => selectNode(node.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </aside>

        <main className="flex min-h-[520px] min-w-0 flex-col border-b border-border/70 lg:border-b-0">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium">
                <GitBranch className="h-4 w-4 text-primary" />
                {visualEnabled ? "Visual graph" : "Visual paused"}
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                {visualPayload
                  ? `${visualPayload.returned_nodes} nodes, ${visualPayload.returned_edges} edges`
                  : "Bounded graph payload"}
              </div>
            </div>
            {visualEnabled ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setVisualEnabled(false)}
                aria-label="Pause visual graph"
              >
                <Pause className="h-4 w-4" />
                Pause visual
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={() => {
                  resetVisualError();
                  setVisualEnabled(true);
                }}
                disabled={!graphExists || !visualPayload}
                aria-label="Show visual graph"
              >
                <Play className="h-4 w-4" />
                Show visual
              </Button>
            )}
          </div>

          <div className="min-h-0 flex-1 p-4">
            {visualEnabled && visualPayload ? (
              <GraphVisualBoundary key={visualErrorKey} onReset={() => setVisualEnabled(false)}>
                <Suspense
                  fallback={
                    <div className="flex h-full min-h-[420px] items-center justify-center rounded-md border border-border/70 bg-background/30 text-sm text-muted-foreground">
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Loading visual renderer
                    </div>
                  }
                >
                  <LazyGraphCanvas
                    payload={visualPayload}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={selectNode}
                  />
                </Suspense>
              </GraphVisualBoundary>
            ) : (
              <div className="flex h-full min-h-[420px] flex-col items-center justify-center rounded-md border border-dashed border-border/70 bg-background/30 px-6 text-center">
                <div className="rounded-md border border-primary/30 bg-primary/10 p-3 text-primary">
                  <Network className="h-6 w-6" />
                </div>
                <h3 className="mt-4 text-sm font-medium">Visual renderer paused</h3>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">
                  Search, filters, node detail, and source hints remain active without mounting canvas.
                </p>
              </div>
            )}
          </div>
        </main>

        <aside className="comfortable-scrollbar min-h-0 overflow-y-auto p-4">
          <Inspector
            node={selectedCard}
            loading={nodeDetail.isFetching && selectedNodeId != null}
            graphPayload={visualPayload}
          />
        </aside>
      </div>
    </section>
  );
}

class GraphVisualBoundary extends Component<
  { children: ReactNode; onReset: () => void },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full min-h-[420px] flex-col items-center justify-center rounded-md border border-destructive/40 bg-destructive/5 px-6 text-center">
          <AlertTriangle className="h-6 w-6 text-destructive" />
          <h3 className="mt-3 text-sm font-medium">Visual renderer unavailable</h3>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            The graph API is still available. Pause the visual and keep using the lists.
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={this.props.onReset}>
            Pause visual
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <button
      type="button"
      onClick={onClear}
      className="inline-flex min-h-8 items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 text-xs text-primary"
    >
      {label}
      <X className="h-3 w-3" />
    </button>
  );
}

function NodeRow({
  node,
  active,
  onClick,
}: {
  node: GraphNodeCard;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-md border p-3 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-primary/55 bg-primary/12"
          : "border-border/70 bg-background/35 hover:border-primary/35 hover:bg-muted/30",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{node.label}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge>{node.entity_type}</Badge>
            {node.route_labels.slice(0, 2).map((route) => (
              <Badge key={route}>{route}</Badge>
            ))}
          </div>
        </div>
        <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {node.degree}
        </span>
      </div>
      {node.description && (
        <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {node.description}
        </p>
      )}
    </button>
  );
}

function Inspector({
  node,
  loading,
  graphPayload,
}: {
  node: GraphNodeCard | GraphNodeDetail | null;
  loading: boolean;
  graphPayload?: GraphPayload;
}) {
  if (!node) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-md border border-dashed border-border/70 bg-background/30 px-5 text-center">
        <Network className="h-7 w-7 text-muted-foreground" />
        <h3 className="mt-3 text-sm font-medium">No node selected</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick a result or a visual node.
        </p>
        {graphPayload && (
          <div className="mt-4 rounded-md border border-border/70 px-3 py-2 text-xs text-muted-foreground">
            {graphPayload.returned_nodes} nodes in current view
          </div>
        )}
      </div>
    );
  }

  const detail = node as GraphNodeDetail;
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.12em] text-muted-foreground">
          Inspector
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        </div>
        <h3 className="mt-2 break-words text-base font-semibold">{node.label}</h3>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge>{node.entity_type}</Badge>
          {node.route_labels.map((route) => (
            <Badge key={route}>{route}</Badge>
          ))}
        </div>
      </div>

      {node.description && (
        <section className="rounded-md border border-border/70 bg-background/35 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Description
          </h4>
          <p className="mt-2 text-sm leading-relaxed text-foreground/90">{node.description}</p>
        </section>
      )}

      {node.source_files.length > 0 && (
        <section className="rounded-md border border-border/70 bg-background/35 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Source Hints
          </h4>
          <div className="mt-2 space-y-1">
            {node.source_files.slice(0, 8).map((file) => (
              <div key={file} className="break-all rounded bg-muted/30 px-2 py-1 text-xs text-muted-foreground">
                {file}
              </div>
            ))}
          </div>
        </section>
      )}

      {node.obsidian_hints.length > 0 && (
        <section className="rounded-md border border-border/70 bg-background/35 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Links
          </h4>
          <div className="mt-2 space-y-2">
            {node.obsidian_hints.slice(0, 4).map((hint) => (
              <a
                key={hint.obsidian_uri}
                href={hint.obsidian_uri}
                className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-2 py-1.5 text-xs text-primary hover:bg-primary/10"
              >
                <span className="min-w-0 truncate">{hint.best_effort_rel_path}</span>
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
              </a>
            ))}
          </div>
        </section>
      )}

      {detail.adjacent_edges?.length > 0 && (
        <section className="rounded-md border border-border/70 bg-background/35 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Adjacent Edges
          </h4>
          <div className="mt-2 space-y-2">
            {detail.adjacent_edges.slice(0, 12).map((edge) => (
              <div key={edge.id} className="rounded-md bg-muted/25 p-2 text-xs">
                <div className="font-medium">{edge.other_node_id ?? edge.target}</div>
                {edge.description && (
                  <div className="mt-1 line-clamp-2 text-muted-foreground">{edge.description}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {node.prepared_queries.length > 0 && (
        <section className="rounded-md border border-border/70 bg-background/35 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Queries
          </h4>
          <div className="mt-2 space-y-2">
            {node.prepared_queries.map((query) => (
              <div key={`${query.surface}-${query.query}`} className="rounded-md bg-muted/25 p-2 text-xs">
                <div className="font-medium">{query.surface}</div>
                <div className="mt-1 break-words text-muted-foreground">{query.query}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function InlineState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof AlertTriangle;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-md border border-dashed border-border/70 bg-background/30 p-4 text-center">
      <Icon className="mx-auto h-5 w-5 text-muted-foreground" />
      <div className="mt-2 text-sm font-medium">{title}</div>
      <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</div>
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded border border-border/70 bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground">
      {children}
    </span>
  );
}

function statusLabel(args: {
  graphExists: boolean;
  healthLoading: boolean;
  summaryLoading: boolean;
  error: string | null;
  cacheLoaded: boolean;
  cacheFresh: boolean;
}) {
  if (args.healthLoading) return "Checking source";
  if (!args.graphExists) return "Source missing";
  if (args.error) return args.error;
  if (args.summaryLoading) return "Loading graph";
  if (!args.cacheLoaded) return "Cold";
  return args.cacheFresh ? "Loaded" : "Stale";
}
