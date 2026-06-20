import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  ChevronsUpDown,
  FileText,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  RotateCcw,
  Send,
  Square,
  User,
  Bot,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/EmptyState";
import { Markdown } from "@/components/Markdown";
import { ModalityBadge } from "@/components/ModalityBadge";
import { PreviewThumb } from "@/components/PreviewThumb";
import {
  PreviewDialog,
  type PreviewDialogItem,
} from "@/components/PreviewDialog";
import {
  CHAT_MODELS,
  useChat,
  type ChatMessage,
  type ChatModelId,
} from "@/hooks/useChat";
import type { ChatWorkspace } from "@/hooks/useChatWorkspace";
import type { PersistedChatMessage, SearchResult } from "@/lib/api";
import { formatSourceLocation } from "@/lib/utils";

const CONTEXT_WIDTH_KEY = "dante-dashboard-context-width";
const CONTEXT_OPEN_KEY = "dante-dashboard-context-open";
const CHAT_MODEL_KEY = "dante-dashboard-chat-model";
const CHAT_TOP_K_KEY = "dante-dashboard-chat-top-k";
const CHAT_TOP_K_OPTIONS = [3, 5, 8, 12] as const;

type ChatTopK = (typeof CHAT_TOP_K_OPTIONS)[number];
type ContextScope = "all" | "latest";
type ContextSourceFilter = "all" | "visual";

interface SourceCluster {
  key: string;
  primary: SearchResult;
  sources: SearchResult[];
  topScore: number;
}

interface ContextGroup {
  answerIndex: number;
  sourceGroups: SourceCluster[];
  visualAttachments: number;
  excerpt: string;
}

interface ChatPanelProps {
  workspace: ChatWorkspace;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function readStoredNumber(key: string, fallback: number, min: number, max: number) {
  if (typeof window === "undefined") return fallback;
  const stored = Number(window.localStorage.getItem(key));
  return Number.isFinite(stored) ? clamp(stored, min, max) : fallback;
}

function readStoredBoolean(key: string, fallback: boolean) {
  if (typeof window === "undefined") return fallback;
  const stored = window.localStorage.getItem(key);
  if (stored === "true") return true;
  if (stored === "false") return false;
  return fallback;
}

function readStoredChatModel(fallback: ChatModelId): ChatModelId {
  if (typeof window === "undefined") return fallback;
  const stored = window.localStorage.getItem(CHAT_MODEL_KEY);
  return CHAT_MODELS.some((model) => model.id === stored)
    ? (stored as ChatModelId)
    : fallback;
}

function isChatTopK(value: number): value is ChatTopK {
  return CHAT_TOP_K_OPTIONS.some((option) => option === value);
}

function readStoredChatTopK(fallback: ChatTopK): ChatTopK {
  if (typeof window === "undefined") return fallback;
  const stored = Number(window.localStorage.getItem(CHAT_TOP_K_KEY));
  return Number.isFinite(stored) && isChatTopK(stored) ? stored : fallback;
}

function metadataString(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function sourceAssetKey(src: SearchResult) {
  return (
    metadataString(src.metadata, "dante_image_id") ??
    metadataString(src.metadata, "source_sha256") ??
    metadataString(src.metadata, "linked_image_file_id") ??
    metadataString(src.metadata, "preview_image_file_id") ??
    src.file_id ??
    src.node_id
  );
}

function sourcePreviewRank(src: SearchResult) {
  let rank = 0;
  if (src.preview_url) rank += 4;
  if (src.modality === "image") rank += 2;
  if (src.snippet) rank += 1;
  return rank;
}

function choosePrimarySource(current: SearchResult, next: SearchResult) {
  const currentRank = sourcePreviewRank(current);
  const nextRank = sourcePreviewRank(next);
  if (nextRank > currentRank) return next;
  if (nextRank === currentRank && next.score > current.score) return next;
  return current;
}

function groupSourcesByAsset(sources: SearchResult[]) {
  const grouped = new Map<string, SourceCluster>();

  for (const src of sources) {
    const key = sourceAssetKey(src);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, {
        key,
        primary: src,
        sources: [src],
        topScore: src.score,
      });
      continue;
    }

    existing.sources.push(src);
    existing.primary = choosePrimarySource(existing.primary, src);
    existing.topScore = Math.max(existing.topScore, src.score);
  }

  return Array.from(grouped.values());
}

function sourceClusterSnippet(cluster: SourceCluster) {
  return cluster.sources.find((src) => src.snippet)?.snippet ?? "";
}

function sourceHasVisual(src: SearchResult) {
  return (
    src.modality === "image" ||
    Boolean(src.preview_url) ||
    metadataString(src.metadata, "linked_image_file_id") != null ||
    metadataString(src.metadata, "preview_image_file_id") != null
  );
}

function clusterHasVisual(cluster: SourceCluster) {
  return cluster.sources.some(sourceHasVisual);
}

function collectAssistantContextGroups(messages: ChatMessage[]) {
  const groups: ContextGroup[] = [];
  let answerIndex = 0;

  for (const message of messages) {
    if (message.role !== "assistant") continue;
    answerIndex += 1;
    if (message.sources && message.sources.length > 0) {
      groups.push({
        answerIndex,
        sourceGroups: groupSourcesByAsset(message.sources),
        visualAttachments: message.visualAttachments ?? 0,
        excerpt: message.content.replace(/\s+/g, " ").trim(),
      });
    }
  }

  return groups;
}

function persistedToChatMessage(message: PersistedChatMessage): ChatMessage {
  if (message.role === "user") {
    return {
      id: message.id,
      role: "user",
      content: message.content,
    };
  }

  return {
    id: message.id,
    role: "assistant",
    content: message.content,
    sources: message.sources.length > 0 ? message.sources : undefined,
    visualAttachments: message.visual_attachments,
    error:
      message.status === "complete" ? undefined : "This answer did not complete.",
  };
}

function Bubble({
  message,
  onSourceClick,
}: {
  message: ChatMessage;
  onSourceClick: (r: SearchResult) => void;
}) {
  const isUser = message.role === "user";
  const sourceGroups =
    message.role === "assistant" && message.sources
      ? groupSourcesByAsset(message.sources)
      : [];

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "border border-border/60 bg-muted text-muted-foreground"
        }`}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={`max-w-[78%] rounded-lg border px-3.5 py-2.5 text-sm ${
          isUser
            ? "border-primary/35 bg-primary/10 text-foreground"
            : "surface-card bg-card/95"
        }`}
      >
        {message.content ? (
          isUser ? (
            <p className="whitespace-pre-wrap leading-relaxed">
              {message.content}
            </p>
          ) : (
            <>
              <Markdown>{message.content}</Markdown>
              {message.streaming && (
                <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground/50 align-middle" />
              )}
            </>
          )
        ) : message.role === "assistant" && message.streaming ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
          </span>
        ) : null}

        {message.role === "assistant" && message.error && (
          <p className="mt-2 text-xs text-destructive">{message.error}</p>
        )}

        {message.role === "assistant" &&
          message.sources &&
          message.sources.length > 0 && (
            <div className="mt-3 border-t pt-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Sources ({sourceGroups.length}
                {sourceGroups.length !== message.sources.length
                  ? ` assets · ${message.sources.length} cards`
                  : ""}
                {message.visualAttachments
                  ? ` · ${message.visualAttachments} visual`
                  : ""}
                )
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {sourceGroups.map((cluster) => {
                  const src = cluster.primary;
                  const location = formatSourceLocation(
                    src.modality,
                    src.metadata,
                  );
                  return (
                    <button
                      key={cluster.key}
                      type="button"
                      onClick={() => onSourceClick(src)}
                      className="chat-source-button flex items-center gap-2 rounded-md border bg-background/70 p-2 text-left transition-colors hover:border-primary/35 hover:bg-accent"
                    >
                      <div className="media-frame h-10 w-10 shrink-0 overflow-hidden rounded border border-border/40">
                        <PreviewThumb
                          url={src.preview_url}
                          modality={src.modality}
                          alt={src.display_name}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium">
                          {src.display_name}
                        </div>
                        {location && (
                          <div className="mt-0.5 truncate text-[11px] font-medium text-foreground/80">
                            {location}
                          </div>
                        )}
                        <div className="mt-0.5 flex items-center gap-1.5">
                          <ModalityBadge
                            modality={src.modality}
                            showLabel={false}
                          />
                          <span className="text-[10px] tabular-nums text-muted-foreground">
                            {(cluster.topScore * 100).toFixed(0)}%
                          </span>
                          {cluster.sources.length > 1 && (
                            <span className="text-[10px] text-muted-foreground">
                              {cluster.sources.length} layers
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
      </div>
    </div>
  );
}

function ContextPanel({
  groups,
  onSourceClick,
  onClose,
  width,
  scope,
  onScopeChange,
  sourceFilter,
  onSourceFilterChange,
}: {
  groups: ContextGroup[];
  onSourceClick: (r: SearchResult) => void;
  onClose: () => void;
  width: number;
  scope: ContextScope;
  onScopeChange: (scope: ContextScope) => void;
  sourceFilter: ContextSourceFilter;
  onSourceFilterChange: (filter: ContextSourceFilter) => void;
}) {
  const scopedGroups = scope === "latest" ? groups.slice(-1) : groups;
  const visibleGroups =
    sourceFilter === "visual"
      ? scopedGroups
          .map((group) => ({
            ...group,
            sourceGroups: group.sourceGroups.filter(clusterHasVisual),
          }))
          .filter((group) => group.sourceGroups.length > 0)
      : scopedGroups;
  const totalAssets = visibleGroups.reduce(
    (sum, group) => sum + group.sourceGroups.length,
    0,
  );
  const totalSourceCards = visibleGroups.reduce(
    (sum, group) =>
      sum +
      group.sourceGroups.reduce(
        (groupSum, cluster) => groupSum + cluster.sources.length,
        0,
      ),
    0,
  );
  const totalVisualAttachments = visibleGroups.reduce(
    (sum, group) => sum + group.visualAttachments,
    0,
  );
  const emptyFilteredContext = groups.length > 0 && visibleGroups.length === 0;

  return (
    <aside
      className="context-panel flex min-h-0 shrink-0 flex-col overflow-hidden border-l"
      style={{ width }}
    >
      <div className="context-panel-header flex h-[58px] shrink-0 items-center justify-between border-b px-4">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h3 className="truncate text-base font-semibold">Context</h3>
            <span className="truncate text-xs text-muted-foreground">
              Sources
            </span>
          </div>
          <p className="truncate text-[11px] text-muted-foreground">
            Linked previews and evidence from this chat
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="context-icon-button"
            onClick={onClose}
            aria-label="Close context panel"
          >
            <PanelRightClose className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="comfortable-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        {groups.length === 0 ? (
          <div className="context-empty flex h-full flex-col items-center justify-center px-5 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-md border">
              <FileText className="h-5 w-5" />
            </div>
            <h4 className="text-sm font-semibold">No active context yet</h4>
            <p className="mt-1 max-w-[25rem] text-sm text-muted-foreground">
              Ask a question in chat and this pane will hold the cited evidence,
              visual links, and preview cards from every answer.
            </p>
          </div>
        ) : emptyFilteredContext ? (
          <div className="context-empty flex h-full flex-col items-center justify-center px-5 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-md border">
              <FileText className="h-5 w-5" />
            </div>
            <h4 className="text-sm font-semibold">No visual sources here</h4>
            <p className="mt-1 max-w-[25rem] text-sm text-muted-foreground">
              Switch back to all sources to inspect the cited text evidence.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="context-summary rounded-md border px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Conversation context
                </div>
                <div className="context-filter-row flex shrink-0 items-center gap-1">
                  <Button
                    variant={scope === "all" ? "secondary" : "ghost"}
                    size="sm"
                    className="h-6 px-2 text-[11px]"
                    onClick={() => onScopeChange("all")}
                  >
                    All
                  </Button>
                  <Button
                    variant={scope === "latest" ? "secondary" : "ghost"}
                    size="sm"
                    className="h-6 px-2 text-[11px]"
                    onClick={() => onScopeChange("latest")}
                  >
                    Latest
                  </Button>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span>{visibleGroups.length} answers</span>
                  <span>{totalAssets} assets</span>
                  {totalSourceCards !== totalAssets && (
                    <span>{totalSourceCards} source cards</span>
                  )}
                  {totalVisualAttachments > 0 && (
                    <span>{totalVisualAttachments} visual attachments</span>
                  )}
                </div>
                <Button
                  variant={sourceFilter === "visual" ? "secondary" : "ghost"}
                  size="sm"
                  className="h-6 shrink-0 px-2 text-[11px]"
                  onClick={() =>
                    onSourceFilterChange(
                      sourceFilter === "visual" ? "all" : "visual",
                    )
                  }
                >
                  {sourceFilter === "visual" ? "Visual" : "All sources"}
                </Button>
              </div>
            </div>

            {visibleGroups.map((group) => (
              <section key={group.answerIndex} className="flex flex-col gap-2">
                <div className="px-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Answer #{group.answerIndex}
                  </div>
                  {group.excerpt && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                      {group.excerpt}
                    </p>
                  )}
                </div>

                {group.sourceGroups.map((cluster, index) => {
                  const src = cluster.primary;
                  const snippet = sourceClusterSnippet(cluster);
                  const location = formatSourceLocation(
                    src.modality,
                    src.metadata,
                  );
                  return (
                    <button
                      key={`${group.answerIndex}-${cluster.key}-${index}`}
                      type="button"
                      onClick={() => onSourceClick(src)}
                      className="context-source-card rounded-md border p-3 text-left transition-colors"
                    >
                      <div className="flex gap-3">
                        <div className="media-frame h-16 w-16 shrink-0 overflow-hidden rounded border border-border/40">
                          <PreviewThumb
                            url={src.preview_url}
                            modality={src.modality}
                            alt={src.display_name}
                          />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="context-source-index">
                              #{group.answerIndex}.{index + 1}
                            </span>
                            <ModalityBadge modality={src.modality} />
                            <span className="text-[11px] tabular-nums text-muted-foreground">
                              {(cluster.topScore * 100).toFixed(0)}%
                            </span>
                            {cluster.sources.length > 1 && (
                              <span className="text-[11px] text-muted-foreground">
                                {cluster.sources.length} layers
                              </span>
                            )}
                          </div>
                          <div className="mt-1 truncate text-sm font-semibold">
                            {src.display_name}
                          </div>
                          {location && (
                            <div className="mt-0.5 truncate text-xs text-muted-foreground">
                              {location}
                            </div>
                          )}
                        </div>
                      </div>
                      {snippet && (
                        <p className="mt-3 line-clamp-4 text-xs leading-relaxed text-muted-foreground">
                          {snippet}
                        </p>
                      )}
                    </button>
                  );
                })}
              </section>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

export function ChatPanel({ workspace }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [chatModel, setChatModel] = useState<ChatModelId>(() =>
    readStoredChatModel("deepseek-v4-pro"),
  );
  const [topK, setTopK] = useState<ChatTopK>(() => readStoredChatTopK(5));
  const [contextOpen, setContextOpen] = useState(() =>
    readStoredBoolean(CONTEXT_OPEN_KEY, true),
  );
  const [contextWidth, setContextWidth] = useState(() =>
    readStoredNumber(CONTEXT_WIDTH_KEY, 420, 320, 640),
  );
  const [contextScope, setContextScope] = useState<ContextScope>("all");
  const [contextSourceFilter, setContextSourceFilter] =
    useState<ContextSourceFilter>("all");
  const scrollRef = useRef<HTMLDivElement>(null);
  const [previewItem, setPreviewItem] = useState<PreviewDialogItem | null>(
    null,
  );
  const activeThreadDetail =
    workspace.threadDetail?.id === workspace.selectedThreadId
      ? workspace.threadDetail
      : null;
  const persistedMessages = useMemo(
    () => activeThreadDetail?.messages.map(persistedToChatMessage) ?? [],
    [activeThreadDetail],
  );
  const { messages, isStreaming, send, reset, stop } = useChat({
    initialMessages: persistedMessages,
    projectId: workspace.selectedProjectId,
    threadId: workspace.selectedThreadId,
    onCompleted: workspace.refreshThread,
  });
  const contextGroups = useMemo(
    () => collectAssistantContextGroups(messages),
    [messages],
  );
  const selectedThreadTitle =
    activeThreadDetail?.title ?? workspace.selectedThread?.title ?? "Chat";

  useEffect(() => {
    window.localStorage.setItem(CHAT_MODEL_KEY, chatModel);
  }, [chatModel]);

  useEffect(() => {
    const savedModel = workspace.selectedThread?.chat_model;
    if (
      !isStreaming &&
      savedModel &&
      CHAT_MODELS.some((model) => model.id === savedModel)
    ) {
      setChatModel(savedModel as ChatModelId);
    }
  }, [workspace.selectedThread?.id, workspace.selectedThread?.chat_model, isStreaming]);

  useEffect(() => {
    window.localStorage.setItem(CHAT_TOP_K_KEY, String(topK));
  }, [topK]);

  useEffect(() => {
    const savedTopK = workspace.selectedThread?.top_k;
    if (!isStreaming && savedTopK != null && isChatTopK(savedTopK)) {
      setTopK(savedTopK);
    }
  }, [workspace.selectedThread?.id, workspace.selectedThread?.top_k, isStreaming]);

  useEffect(() => {
    window.localStorage.setItem(CONTEXT_OPEN_KEY, String(contextOpen));
  }, [contextOpen]);

  useEffect(() => {
    window.localStorage.setItem(CONTEXT_WIDTH_KEY, String(contextWidth));
  }, [contextWidth]);

  useEffect(() => {
    // Smooth scrolling per token queues dozens of animations and feels janky.
    // Snap-scroll while streaming, animate only when the stream settles.
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: isStreaming ? "auto" : "smooth",
    });
  }, [messages, isStreaming]);

  const submit = () => {
    const q = draft.trim();
    if (!q || isStreaming || !workspace.selectedThreadId) return;
    setDraft("");
    void send(q, {
      model: chatModel,
      topK,
      projectId: workspace.selectedProjectId,
      threadId: workspace.selectedThreadId,
    });
  };

  const startNewChat = () => {
    if (isStreaming) stop();
    if (workspace.selectedProjectId) {
      workspace.createThread(chatModel, topK);
    } else {
      reset();
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const openPreviewForSource = (src: SearchResult) =>
    setPreviewItem({
      display_name: src.display_name,
      modality: src.modality,
      preview_url: src.preview_url,
      snippet: src.snippet,
      score: src.score,
      metadata: src.metadata,
    });

  const startContextResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();

    const startX = event.clientX;
    const startWidth = contextWidth;

    const onMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidth - (moveEvent.clientX - startX);
      setContextWidth(clamp(nextWidth, 320, 640));
    };

    const onUp = () => {
      document.body.classList.remove("is-resizing-panel");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };

    document.body.classList.add("is-resizing-panel");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <section className="chat-screen -m-4 flex h-[calc(100%+2rem)] min-w-0 flex-col overflow-hidden md:-m-6 md:h-[calc(100%+3rem)]">
      <div className="chat-workspace flex min-h-0 flex-1 overflow-hidden rounded-none border-0">
        <div
          className={`chat-main-shell flex min-w-0 flex-1 flex-col p-4 md:p-6 ${
            contextOpen ? "lg:pr-0" : ""
          }`}
        >
          <Card className="chat-panel-card flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-none border-0 shadow-none">
          <header className="chat-panel-header flex shrink-0 flex-col gap-3 border-b px-4 py-3 md:px-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">
                {selectedThreadTitle}
              </h2>
              <p className="max-w-full break-words text-xs text-muted-foreground">
                Grounded answers with cited sources from your knowledge base.
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {!contextOpen && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setContextOpen(true)}
                  className="hidden lg:inline-flex"
                >
                  <PanelRightOpen className="h-4 w-4" />
                  Context
                </Button>
              )}
              {(messages.length > 0 || workspace.selectedThreadId) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={startNewChat}
                  disabled={workspace.isCreatingThread}
                >
                  <RotateCcw className="h-4 w-4" />
                  New chat
                </Button>
              )}
            </div>
          </header>

          <div
            ref={scrollRef}
            className="chat-panel-scroll comfortable-scrollbar flex-1 overflow-y-auto p-4"
            role="log"
            aria-live="polite"
          >
            {messages.length === 0 ? (
              <EmptyState
                icon={MessageSquare}
                title="Ask anything about your knowledge base"
                description="The assistant retrieves relevant items, looks at the visuals when helpful, and cites its sources."
                className="border-0 bg-transparent py-8"
              />
            ) : (
              <div className="flex flex-col gap-4">
                {messages.map((m, i) => (
                  <Bubble
                    key={m.id ?? `${m.role}-${i}`}
                    message={m}
                    onSourceClick={openPreviewForSource}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="chat-panel-composer border-t p-3">
            <div className="chat-composer-box flex items-end gap-2 rounded-md border p-2">
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Ask a question..."
                rows={1}
                className="chat-panel-input max-h-40 min-h-10 resize-none border-0 bg-transparent py-2 leading-5 shadow-none field-sizing-content focus-visible:ring-0 focus-visible:ring-offset-0"
              />
              {isStreaming ? (
                <Button
                  onClick={stop}
                  variant="outline"
                  className="chat-send-button shrink-0"
                  aria-label="Stop"
                >
                  <Square className="h-4 w-4" />
                  Stop
                </Button>
              ) : (
                <Button
                  onClick={submit}
                  className="chat-send-button shrink-0"
                  disabled={
                    draft.trim().length === 0 || !workspace.selectedThreadId
                  }
                  aria-label="Send"
                >
                  <Send className="h-4 w-4" />
                  Send
                </Button>
              )}
            </div>

            <div className="chat-composer-meta mt-2 flex min-h-8 flex-wrap items-center gap-2 pt-1">
              <label className="chat-model-control relative inline-flex min-w-0 max-w-full items-center gap-2 rounded-md border px-2 py-1">
                <Bot className="h-3.5 w-3.5 shrink-0" />
                <span className="shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Model
                </span>
                <select
                  value={chatModel}
                  onChange={(event) =>
                    setChatModel(event.target.value as ChatModelId)
                  }
                  disabled={isStreaming}
                  className="chat-model-select h-7 min-w-[13rem] max-w-[17rem] appearance-none truncate border-0 bg-transparent py-0 pl-0 pr-7 text-xs font-medium outline-none transition-colors disabled:opacity-60"
                >
                  {CHAT_MODELS.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.label}
                    </option>
                  ))}
                </select>
                <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              </label>
              <label className="chat-topk-control relative inline-flex min-w-0 items-center gap-2 rounded-md border px-2 py-1">
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Sources
                </span>
                <select
                  value={topK}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (isChatTopK(next)) setTopK(next);
                  }}
                  disabled={isStreaming}
                  className="chat-topk-select h-7 min-w-[3.25rem] appearance-none border-0 bg-transparent py-0 pl-0 pr-7 text-xs font-medium outline-none transition-colors disabled:opacity-60"
                >
                  {CHAT_TOP_K_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              </label>
            </div>
          </div>
        </Card>
        </div>

        {contextOpen && (
          <div className="context-panel-shell hidden min-h-0 shrink-0 lg:flex">
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize context panel"
              className="app-resize-handle app-resize-handle-context hidden lg:block"
              onPointerDown={startContextResize}
            />
            <ContextPanel
              groups={contextGroups}
              onSourceClick={openPreviewForSource}
              onClose={() => setContextOpen(false)}
              width={contextWidth}
              scope={contextScope}
              onScopeChange={setContextScope}
              sourceFilter={contextSourceFilter}
              onSourceFilterChange={setContextSourceFilter}
            />
          </div>
        )}
      </div>

      <PreviewDialog
        open={previewItem !== null}
        onOpenChange={(v) => !v && setPreviewItem(null)}
        item={previewItem}
      />
    </section>
  );
}
