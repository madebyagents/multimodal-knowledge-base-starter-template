import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Archive,
  Database,
  Folder,
  Loader2,
  MessageSquare,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Save,
  Search,
  Settings,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ModalityBadge } from "@/components/ModalityBadge";
import { useStats } from "@/hooks/useStats";
import { useClear } from "@/hooks/useClear";
import { useIngest } from "@/hooks/useIngest";
import type { ChatWorkspace } from "@/hooks/useChatWorkspace";
import { type Modality } from "@/lib/utils";

const MODALITIES: Modality[] = ["image", "pdf", "video", "text"];

interface SidebarProps {
  width: number;
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  workspace: ChatWorkspace;
}

export function Sidebar({ width, onResizeStart, workspace }: SidebarProps) {
  const { data: stats, isLoading } = useStats();
  const clear = useClear();
  const ingest = useIngest();
  const fileInput = useRef<HTMLInputElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [projectNameDraft, setProjectNameDraft] = useState("");
  const [isAddingProject, setIsAddingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [threadTitleDraft, setThreadTitleDraft] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const sidebarStyle = {
    "--sidebar-width": `${width}px`,
  } as CSSProperties;

  const hasStats = stats != null;
  const total = stats?.total ?? 0;
  const canClear = hasStats && total > 0;
  const activeThreads = workspace.threads.filter((thread) => !thread.archived);
  const pinnedThreads = workspace.threads.filter((thread) => thread.pinned).length;
  const filteredThreads = useMemo(() => {
    const query = threadSearch.trim().toLowerCase();
    if (!query) return workspace.threads;
    return workspace.threads.filter((thread) =>
      thread.title.toLowerCase().includes(query),
    );
  }, [threadSearch, workspace.threads]);

  useEffect(() => {
    setMemoryDraft(workspace.selectedProject?.memory ?? "");
    setProjectNameDraft(workspace.selectedProject?.name ?? "");
  }, [
    workspace.selectedProject?.id,
    workspace.selectedProject?.memory,
    workspace.selectedProject?.name,
  ]);

  const defaultProjectName = () => `Project ${workspace.projects.length + 1}`;

  const onPickFiles = () => fileInput.current?.click();

  const onCreateProject = () => {
    setNewProjectName(defaultProjectName());
    setIsAddingProject(true);
  };

  const onCancelProjectCreation = () => {
    if (workspace.isCreatingProject) return;
    setNewProjectName("");
    setIsAddingProject(false);
  };

  const onSubmitProjectCreation = () => {
    if (workspace.isCreatingProject) return;
    const name = newProjectName.trim() || defaultProjectName();
    workspace.createProject(name, {
      onSuccess: () => {
        setNewProjectName("");
        setIsAddingProject(false);
      },
    });
  };

  const onSubmitProjectName = () => {
    if (workspace.isUpdatingProject) return;
    const current = workspace.selectedProject?.name ?? "";
    const name = projectNameDraft.trim();
    if (!name || name === current) return;
    workspace.renameProject(name);
  };

  const onSaveProjectMemory = () => {
    workspace.updateProjectMemory(
      memoryDraft,
      workspace.selectedProject?.instructions,
    );
  };

  const onStartThreadRename = (threadId: string, currentTitle: string) => {
    setEditingThreadId(threadId);
    setThreadTitleDraft(currentTitle);
  };

  const onCancelThreadRename = () => {
    if (workspace.isUpdatingThread) return;
    setEditingThreadId(null);
    setThreadTitleDraft("");
  };

  const onSubmitThreadRename = (threadId: string, currentTitle: string) => {
    if (workspace.isUpdatingThread) return;
    const title = threadTitleDraft.trim();
    if (!title || title === currentTitle) {
      onCancelThreadRename();
      return;
    }
    workspace.renameThread(threadId, title, {
      onSuccess: () => {
        setEditingThreadId(null);
        setThreadTitleDraft("");
      },
    });
  };

  const onFilesChosen = (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : [];
    if (files.length === 0) return;
    ingest.mutate({ files });
    event.target.value = "";
  };

  const onClear = () => {
    if (!canClear) return;
    if (
      window.confirm(
        `Permanently delete all ${total} items from the knowledge base?`,
      )
    ) {
      clear.mutate();
    }
  };

  return (
    <aside
      style={sidebarStyle}
      className="app-sidebar relative flex max-h-[44vh] w-full shrink-0 flex-col overflow-hidden border-b bg-card md:h-screen md:max-h-none md:w-[var(--sidebar-width)] md:border-b-0 md:border-r"
    >
      <div className="app-sidebar-brand shrink-0 border-b border-border/60" />

      <div className="sidebar-workspace-header shrink-0 border-b px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Workspace
            </div>
            <div className="mt-1 truncate text-sm font-semibold text-foreground">
              {workspace.selectedProject?.name ?? "No project selected"}
            </div>
            <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>{activeThreads.length} active</span>
              {pinnedThreads > 0 && <span>{pinnedThreads} pinned</span>}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="sidebar-quiet-icon h-8 w-8 shrink-0"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open workspace settings"
          >
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="comfortable-scrollbar flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 py-3">
        <section className="shrink-0">
          <div className="sidebar-section-label mb-2 flex items-center justify-between gap-2">
            <div>Projects</div>
            <Button
              variant="ghost"
              size="icon"
              className="sidebar-quiet-icon h-7 w-7"
              onClick={onCreateProject}
              disabled={
                workspace.isLoading || workspace.isCreatingProject || isAddingProject
              }
              aria-label="New project"
            >
              {workspace.isCreatingProject ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
          {isAddingProject && (
            <div className="sidebar-inline-editor mb-2 flex items-center gap-1 rounded-md border p-1">
              <Input
                autoFocus
                value={newProjectName}
                onChange={(event) => setNewProjectName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onSubmitProjectCreation();
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onCancelProjectCreation();
                  }
                }}
                placeholder="Project name"
                className="h-7 min-w-0 flex-1 px-2 text-xs"
                aria-label="Project name"
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={onSubmitProjectCreation}
                disabled={workspace.isCreatingProject}
                aria-label="Create project"
              >
                {workspace.isCreatingProject ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={onCancelProjectCreation}
                disabled={workspace.isCreatingProject}
                aria-label="Cancel project creation"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
          <div className="comfortable-scrollbar flex max-h-40 flex-col gap-1 overflow-y-auto pr-1">
            {workspace.projects.length === 0 && workspace.isLoading ? (
              <>
                <Skeleton className="h-9" />
                <Skeleton className="h-9" />
              </>
            ) : workspace.projects.length === 0 ? (
              <div className="sidebar-empty-state rounded-md border border-dashed px-3 py-3 text-xs">
                No projects yet
              </div>
            ) : (
              workspace.projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => workspace.selectProject(project)}
                  className={`sidebar-project-row flex min-h-9 items-center gap-2 rounded-md border px-2.5 py-2 text-left text-sm transition-colors ${
                    workspace.selectedProjectId === project.id
                      ? "is-active"
                      : ""
                  }`}
                >
                  <Folder className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{project.name}</span>
                  <span className="shrink-0 text-[10px] tabular-nums">
                    {project.thread_count}
                  </span>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="flex min-h-0 flex-1 flex-col">
          <div className="sidebar-section-label mb-2 flex items-center justify-between gap-2">
            <div>Threads</div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant={workspace.includeArchivedThreads ? "secondary" : "ghost"}
                size="icon"
                className="sidebar-quiet-icon h-7 w-7"
                onClick={() =>
                  workspace.setIncludeArchivedThreads(
                    !workspace.includeArchivedThreads,
                  )
                }
                aria-label={
                  workspace.includeArchivedThreads
                    ? "Hide archived threads"
                    : "Show archived threads"
                }
              >
                <Archive className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="sidebar-quiet-icon h-7 w-7"
                onClick={() => workspace.createThread()}
                disabled={!workspace.selectedProjectId || workspace.isCreatingThread}
                aria-label="New thread"
              >
                {workspace.isCreatingThread ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </div>
          <label className="sidebar-search mb-2 flex h-8 items-center gap-2 rounded-md border px-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Input
              value={threadSearch}
              onChange={(event) => setThreadSearch(event.target.value)}
              placeholder="Search threads"
              className="h-6 flex-1 border-0 bg-transparent px-0 py-0 text-xs shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
              aria-label="Search threads"
            />
          </label>
          <div className="comfortable-scrollbar flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
            {workspace.threads.length === 0 && workspace.isLoading ? (
              <>
                <Skeleton className="h-11" />
                <Skeleton className="h-11" />
              </>
            ) : filteredThreads.length === 0 ? (
              <div className="sidebar-empty-state rounded-md border border-dashed px-3 py-3 text-xs">
                {threadSearch.trim()
                  ? "No matching threads"
                  : workspace.includeArchivedThreads
                    ? "No threads yet"
                    : "No active threads"}
              </div>
            ) : (
              filteredThreads.map((thread) => (
                <div
                  key={thread.id}
                  className={`sidebar-thread-row group flex min-h-11 items-center gap-1 rounded-md border px-2 py-1.5 transition-colors ${
                    workspace.selectedThreadId === thread.id
                      ? "is-active"
                      : thread.archived
                        ? "is-archived"
                        : ""
                  }`}
                >
                  {editingThreadId === thread.id ? (
                    <>
                      <Input
                        autoFocus
                        value={threadTitleDraft}
                        onChange={(event) =>
                          setThreadTitleDraft(event.target.value)
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            onSubmitThreadRename(thread.id, thread.title);
                          }
                          if (event.key === "Escape") {
                            event.preventDefault();
                            onCancelThreadRename();
                          }
                        }}
                        className="h-7 min-w-0 flex-1 px-2 text-xs"
                        aria-label="Thread title"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => onSubmitThreadRename(thread.id, thread.title)}
                        disabled={workspace.isUpdatingThread}
                        aria-label="Save thread title"
                      >
                        {workspace.isUpdatingThread ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Save className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={onCancelThreadRename}
                        disabled={workspace.isUpdatingThread}
                        aria-label="Cancel thread rename"
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => workspace.selectThread(thread)}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate text-sm">
                          {thread.title}
                        </span>
                        {thread.message_count > 0 && (
                          <span className="sidebar-count-pill shrink-0 text-[10px] tabular-nums">
                            {thread.message_count}
                          </span>
                        )}
                      </button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="sidebar-row-action h-6 w-6 shrink-0"
                        onClick={() => workspace.pinThread(thread.id, !thread.pinned)}
                        disabled={workspace.isUpdatingThread}
                        aria-label={thread.pinned ? "Unpin thread" : "Pin thread"}
                      >
                        {thread.pinned ? (
                          <PinOff className="h-3 w-3" />
                        ) : (
                          <Pin className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="sidebar-row-action h-6 w-6 shrink-0"
                        onClick={() =>
                          onStartThreadRename(thread.id, thread.title)
                        }
                        aria-label="Rename thread"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="sidebar-row-action h-6 w-6 shrink-0"
                        onClick={() =>
                          workspace.archiveThread(thread.id, !thread.archived)
                        }
                        disabled={workspace.isUpdatingThread}
                        aria-label={
                          thread.archived ? "Unarchive thread" : "Archive thread"
                        }
                      >
                        <Archive className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <div className="sidebar-footer shrink-0 border-t px-3 py-3">
        <Button
          variant="ghost"
          className="sidebar-settings-button h-10 w-full justify-start px-3"
          onClick={() => setSettingsOpen(true)}
        >
          <Settings className="h-4 w-4" />
          <span className="min-w-0 flex-1 text-left">Settings</span>
        </Button>
      </div>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="settings-dialog-panel max-w-3xl p-0" showClose>
          <DialogHeader className="settings-dialog-header border-b px-5 py-4">
            <DialogTitle>Settings</DialogTitle>
            <DialogDescription>
              Project memory, knowledge base status, and local file actions.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 p-5 md:grid-cols-[1.05fr_0.95fr]">
            <section className="settings-section rounded-md border p-4">
              <div className="mb-3 flex items-center gap-2">
                <Folder className="h-4 w-4 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold">Project</h3>
                  <p className="text-xs text-muted-foreground">
                    Name and curated memory for this workspace.
                  </p>
                </div>
              </div>

              {workspace.selectedProject ? (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                      Project name
                    </label>
                    <div className="flex gap-2">
                      <Input
                        value={projectNameDraft}
                        onChange={(event) =>
                          setProjectNameDraft(event.target.value)
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            onSubmitProjectName();
                          }
                        }}
                        className="min-w-0 flex-1"
                        aria-label="Project name"
                      />
                      <Button
                        variant="secondary"
                        onClick={onSubmitProjectName}
                        disabled={
                          workspace.isUpdatingProject ||
                          !projectNameDraft.trim() ||
                          projectNameDraft.trim() ===
                            workspace.selectedProject.name
                        }
                      >
                        {workspace.isUpdatingProject ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        Save
                      </Button>
                    </div>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                      Project memory
                    </label>
                    <Textarea
                      value={memoryDraft}
                      onChange={(event) => setMemoryDraft(event.target.value)}
                      placeholder="Key decisions, preferences, constraints..."
                      rows={8}
                      className="min-h-40 resize-y text-sm"
                    />
                    <div className="mt-2 flex justify-end">
                      <Button
                        onClick={onSaveProjectMemory}
                        disabled={workspace.isUpdatingProject}
                      >
                        {workspace.isUpdatingProject ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        Save memory
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="settings-empty rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                  Select or create a project to edit its memory.
                </div>
              )}
            </section>

            <section className="settings-section rounded-md border p-4">
              <div className="mb-3 flex items-center gap-2">
                <Database className="h-4 w-4 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold">Knowledge base</h3>
                  <p className="text-xs text-muted-foreground">
                    Local corpus status and maintenance actions.
                  </p>
                </div>
              </div>

              <div className="settings-kb-total rounded-md border p-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Total indexed
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  {isLoading || !hasStats ? (
                    <Skeleton className="h-8 w-16" />
                  ) : (
                    <span className="text-3xl font-semibold tabular-nums">
                      {total}
                    </span>
                  )}
                  <span className="text-sm text-muted-foreground">
                    {total === 1 ? "item" : "items"}
                  </span>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                {isLoading || !hasStats
                  ? Array.from({ length: 4 }).map((_, index) => (
                      <Skeleton key={index} className="h-9" />
                    ))
                  : MODALITIES.map((modality) => {
                      const count = stats?.by_modality?.[modality] ?? 0;
                      return (
                        <div
                          key={modality}
                          className="settings-modality-row flex items-center justify-between rounded-md border px-2.5 py-2"
                        >
                          <ModalityBadge modality={modality} />
                          <span className="text-xs font-medium tabular-nums text-muted-foreground">
                            {count}
                          </span>
                        </div>
                      );
                    })}
              </div>

              <div className="mt-4 space-y-2">
                <Button
                  onClick={onPickFiles}
                  disabled={ingest.isPending}
                  className="w-full justify-start"
                >
                  {ingest.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  {ingest.isPending ? "Uploading..." : "Upload files"}
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  onChange={onFilesChosen}
                  accept="image/*,.pdf,video/*,.txt,.md,.markdown,.json,.csv,.html,.htm"
                />

                <Button
                  variant="ghost"
                  onClick={onClear}
                  disabled={clear.isPending || !canClear}
                  className="w-full justify-start text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  {clear.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Clear all
                </Button>
              </div>
            </section>
          </div>
        </DialogContent>
      </Dialog>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize navigation sidebar"
        className="app-resize-handle app-resize-handle-left hidden md:block"
        onPointerDown={onResizeStart}
      />
    </aside>
  );
}
