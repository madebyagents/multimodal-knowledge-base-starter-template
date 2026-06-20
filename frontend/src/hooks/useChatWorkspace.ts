import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  api,
  apiErrorMessage,
  type ChatThread,
  type Project,
  type ThreadDetail,
} from "@/lib/api";

const SELECTED_PROJECT_KEY = "dante-dashboard-selected-project-id";
const SELECTED_THREAD_KEY = "dante-dashboard-selected-thread-id";
const INCLUDE_ARCHIVED_THREADS_KEY =
  "dante-dashboard-include-archived-threads";

function readStoredId(key: string) {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(key);
  return value && value.trim() ? value : null;
}

function writeStoredId(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  if (value) window.localStorage.setItem(key, value);
  else window.localStorage.removeItem(key);
}

function readStoredBoolean(key: string, fallback: boolean) {
  if (typeof window === "undefined") return fallback;
  const value = window.localStorage.getItem(key);
  if (value === "true") return true;
  if (value === "false") return false;
  return fallback;
}

function writeStoredBoolean(key: string, value: boolean) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, String(value));
}

export function useChatWorkspace() {
  const qc = useQueryClient();
  const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(
    () => readStoredId(SELECTED_PROJECT_KEY),
  );
  const [selectedThreadId, setSelectedThreadIdState] = useState<string | null>(
    () => readStoredId(SELECTED_THREAD_KEY),
  );
  const [includeArchivedThreads, setIncludeArchivedThreadsState] = useState(() =>
    readStoredBoolean(INCLUDE_ARCHIVED_THREADS_KEY, false),
  );

  const bootstrap = useQuery({
    queryKey: ["chat-workspace", "bootstrap"],
    queryFn: api.bootstrapWorkspace,
  });

  const projectsQuery = useQuery({
    queryKey: ["chat-projects"],
    queryFn: api.projects,
  });

  const threadsQuery = useQuery({
    queryKey: ["chat-threads", selectedProjectId, includeArchivedThreads],
    queryFn: () =>
      api.threads(selectedProjectId as string, {
        include_archived: includeArchivedThreads,
      }),
    enabled: selectedProjectId != null,
  });

  const threadDetailQuery = useQuery<ThreadDetail>({
    queryKey: ["chat-thread", selectedThreadId],
    queryFn: () => api.thread(selectedThreadId as string),
    enabled: selectedThreadId != null,
  });

  const setSelectedProjectId = (projectId: string | null) => {
    setSelectedProjectIdState(projectId);
    writeStoredId(SELECTED_PROJECT_KEY, projectId);
  };

  const setSelectedThreadId = (threadId: string | null) => {
    setSelectedThreadIdState(threadId);
    writeStoredId(SELECTED_THREAD_KEY, threadId);
  };

  const setIncludeArchivedThreads = (includeArchived: boolean) => {
    setIncludeArchivedThreadsState(includeArchived);
    writeStoredBoolean(INCLUDE_ARCHIVED_THREADS_KEY, includeArchived);
  };

  useEffect(() => {
    if (!bootstrap.data) return;
    if (!selectedProjectId) setSelectedProjectId(bootstrap.data.project.id);
    if (!selectedThreadId) setSelectedThreadId(bootstrap.data.thread.id);
  }, [bootstrap.data, selectedProjectId, selectedThreadId]);

  useEffect(() => {
    const projects = projectsQuery.data?.projects;
    if (!projects?.length) return;
    if (!selectedProjectId || !projects.some((p) => p.id === selectedProjectId)) {
      setSelectedProjectId(projects[0].id);
      setSelectedThreadId(null);
    }
  }, [projectsQuery.data, selectedProjectId]);

  useEffect(() => {
    const threads = threadsQuery.data?.threads;
    if (!threads) return;
    if (threads.length === 0) {
      if (selectedThreadId) setSelectedThreadId(null);
      return;
    }
    if (!selectedThreadId || !threads.some((t) => t.id === selectedThreadId)) {
      setSelectedThreadId(threads[0].id);
    }
  }, [threadsQuery.data, selectedThreadId]);

  const createProject = useMutation({
    mutationFn: async (name: string) => {
      const project = await api.createProject({ name });
      const thread = await api.createThread({ project_id: project.id });
      return { project, thread };
    },
    onSuccess: ({ project, thread }) => {
      setSelectedProjectId(project.id);
      setSelectedThreadId(thread.id);
      qc.invalidateQueries({ queryKey: ["chat-projects"] });
      qc.invalidateQueries({ queryKey: ["chat-threads"] });
    },
    onError: (err) => toast.error(`Project failed: ${apiErrorMessage(err)}`),
  });

  const createThread = useMutation({
    mutationFn: (args: { projectId: string; chatModel?: string; topK?: number }) =>
      api.createThread({
        project_id: args.projectId,
        chat_model: args.chatModel,
        top_k: args.topK,
      }),
    onSuccess: (thread) => {
      setSelectedThreadId(thread.id);
      qc.invalidateQueries({ queryKey: ["chat-projects"] });
      qc.invalidateQueries({ queryKey: ["chat-threads", thread.project_id] });
    },
    onError: (err) => toast.error(`Thread failed: ${apiErrorMessage(err)}`),
  });

  const updateProject = useMutation({
    mutationFn: (args: {
      projectId: string;
      name?: string;
      memory?: string;
      instructions?: string;
    }) =>
      api.updateProject(args.projectId, {
        name: args.name,
        memory: args.memory,
        instructions: args.instructions,
      }),
    onSuccess: (project) => {
      qc.setQueryData(["chat-project", project.id], project);
      qc.invalidateQueries({ queryKey: ["chat-projects"] });
      qc.invalidateQueries({ queryKey: ["chat-thread", selectedThreadId] });
    },
    onError: (err) => toast.error(`Project update failed: ${apiErrorMessage(err)}`),
  });

  const updateThread = useMutation({
    mutationFn: (args: {
      threadId: string;
      title?: string;
      archived?: boolean;
      pinned?: boolean;
      chatModel?: string | null;
      topK?: number | null;
    }) =>
      api.updateThread(args.threadId, {
        title: args.title,
        archived: args.archived,
        pinned: args.pinned,
        chat_model: args.chatModel,
        top_k: args.topK,
      }),
    onSuccess: (thread) => {
      qc.invalidateQueries({ queryKey: ["chat-projects"] });
      qc.invalidateQueries({ queryKey: ["chat-threads", thread.project_id] });
      qc.invalidateQueries({ queryKey: ["chat-thread", thread.id] });
      if (thread.archived && selectedThreadId === thread.id) {
        setSelectedThreadId(null);
      }
    },
    onError: (err) => toast.error(`Thread update failed: ${apiErrorMessage(err)}`),
  });

  const projects = projectsQuery.data?.projects ?? [];
  const threads = threadsQuery.data?.threads ?? [];
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const selectedThread = useMemo(
    () => threads.find((thread) => thread.id === selectedThreadId) ?? null,
    [threads, selectedThreadId],
  );

  return {
    projects,
    threads,
    selectedProject,
    selectedThread,
    selectedProjectId,
    selectedThreadId,
    includeArchivedThreads,
    threadDetail: threadDetailQuery.data ?? null,
    isLoading:
      bootstrap.isLoading ||
      projectsQuery.isLoading ||
      threadsQuery.isLoading ||
      threadDetailQuery.isLoading,
    isCreatingProject: createProject.isPending,
    isCreatingThread: createThread.isPending,
    isUpdatingProject: updateProject.isPending,
    isUpdatingThread: updateThread.isPending,
    selectProject: (project: Project) => {
      setSelectedProjectId(project.id);
      setSelectedThreadId(null);
    },
    selectThread: (thread: ChatThread) => setSelectedThreadId(thread.id),
    setIncludeArchivedThreads,
    createProject: (name: string, options?: { onSuccess?: () => void }) =>
      createProject.mutate(name, { onSuccess: options?.onSuccess }),
    createThread: (chatModel?: string, topK?: number) => {
      const projectId = selectedProjectId;
      if (!projectId) return;
      createThread.mutate({ projectId, chatModel, topK });
    },
    updateProjectMemory: (memory: string, instructions?: string) => {
      const projectId = selectedProjectId;
      if (!projectId) return;
      updateProject.mutate({ projectId, memory, instructions });
    },
    renameProject: (name: string, options?: { onSuccess?: () => void }) => {
      const projectId = selectedProjectId;
      if (!projectId) return;
      updateProject.mutate({ projectId, name }, { onSuccess: options?.onSuccess });
    },
    renameThread: (
      threadId: string,
      title: string,
      options?: { onSuccess?: () => void },
    ) => updateThread.mutate({ threadId, title }, { onSuccess: options?.onSuccess }),
    pinThread: (threadId: string, pinned: boolean) =>
      updateThread.mutate({ threadId, pinned }),
    archiveThread: (threadId: string, archived = true) =>
      updateThread.mutate({ threadId, archived }),
    refreshThread: () => {
      if (selectedThreadId) {
        qc.invalidateQueries({ queryKey: ["chat-thread", selectedThreadId] });
      }
      if (selectedProjectId) {
        qc.invalidateQueries({ queryKey: ["chat-threads", selectedProjectId] });
      }
      qc.invalidateQueries({ queryKey: ["chat-projects"] });
    },
  };
}

export type ChatWorkspace = ReturnType<typeof useChatWorkspace>;
