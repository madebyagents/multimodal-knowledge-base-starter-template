import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { SearchResult } from "@/lib/api";
import { parseSSE } from "@/lib/sse";

export const CHAT_MODELS = [
  {
    id: "deepseek-v4-pro",
    label: "deepseek - deepseek-v4-pro",
  },
  {
    id: "codex-gpt-5.5-oauth",
    label: "openai/codex - gpt-5.5 OAuth",
  },
  {
    id: "claude-sonnet-4-6-oauth",
    label: "claude - sonnet-4.6 OAuth",
  },
  {
    id: "claude-opus-4-8-oauth",
    label: "claude - opus-4.8 OAuth Premium",
  },
] as const;

export type ChatModelId = (typeof CHAT_MODELS)[number]["id"];

export interface ChatUserMessage {
  id?: string;
  role: "user";
  content: string;
}

export interface ChatAssistantMessage {
  id?: string;
  role: "assistant";
  content: string;
  sources?: SearchResult[];
  visualAttachments?: number;
  streaming?: boolean;
  error?: string;
}

export type ChatMessage = ChatUserMessage | ChatAssistantMessage;

interface ChatOptions {
  topK?: number;
  modalityFilter?: string[] | null;
  maxImages?: number;
  model?: ChatModelId;
  projectId?: string | null;
  threadId?: string | null;
}

interface UseChatOptions {
  initialMessages?: ChatMessage[];
  projectId?: string | null;
  threadId?: string | null;
  onCompleted?: () => void;
}

interface SourcesPayload {
  sources: SearchResult[];
  visual_attachments: number;
  citation_validation?: {
    ok: boolean;
    source_count: number;
    cited_source_numbers: number[];
    invalid_source_numbers: number[];
    missing_citations: boolean;
  };
}

export function useChat(options: UseChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const onCompletedRef = useRef(options.onCompleted);

  useEffect(() => {
    onCompletedRef.current = options.onCompleted;
  }, [options.onCompleted]);

  useEffect(() => {
    if (!options.initialMessages || isStreaming) return;
    setMessages(options.initialMessages);
  }, [options.initialMessages, isStreaming]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setIsStreaming(false);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        const next = prev.slice(0, -1);
        next.push({ ...last, streaming: false });
        return next;
      }
      return prev;
    });
  }, []);

  const send = useCallback(async (question: string, opts: ChatOptions = {}) => {
    const q = question.trim();
    // Use the live AbortController ref — not the closed-over `isStreaming`
    // state — so a rapid double-call within one render can't slip past.
    if (!q || abortRef.current) return;

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let completed = false;
    let hasStreamError = false;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", streaming: true },
    ]);
    setIsStreaming(true);

    const updateAssistant = (
      patch: (m: ChatAssistantMessage) => ChatAssistantMessage,
    ) => {
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (!last || last.role !== "assistant") return prev;
        const next = prev.slice(0, -1);
        next.push(patch(last));
        return next;
      });
    };

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          top_k: opts.topK ?? 5,
          modality_filter: opts.modalityFilter ?? null,
          max_images: opts.maxImages ?? 6,
          chat_model: opts.model ?? "deepseek-v4-pro",
          project_id: opts.projectId ?? options.projectId ?? null,
          thread_id: opts.threadId ?? options.threadId ?? null,
        }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => res.statusText);
        throw new Error(detail || `HTTP ${res.status}`);
      }

      for await (const frame of parseSSE(res.body, ctrl.signal)) {
        if (frame.event === "message") {
          const token = safeJsonParse<string>(frame.data, "");
          if (token)
            updateAssistant((m) => ({ ...m, content: m.content + token }));
        } else if (frame.event === "sources") {
          const payload = safeJsonParse<SourcesPayload>(frame.data, {
            sources: [],
            visual_attachments: 0,
          });
          updateAssistant((m) => ({
            ...m,
            sources: payload.sources,
            visualAttachments: payload.visual_attachments,
          }));
        } else if (frame.event === "done") {
          completed = true;
          updateAssistant((m) => ({ ...m, streaming: false }));
        } else if (frame.event === "error") {
          hasStreamError = true;
          const payload = safeJsonParse<{ message?: string }>(frame.data, {});
          const msg = payload.message ?? "Stream error";
          updateAssistant((m) => ({
            ...m,
            streaming: false,
            error: msg,
          }));
          toast.error(`Chat error: ${msg}`);
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        updateAssistant((m) => ({ ...m, streaming: false }));
      } else {
        const msg = (err as Error).message;
        updateAssistant((m) => ({
          ...m,
          streaming: false,
          error: msg,
        }));
        toast.error(`Chat failed: ${msg}`);
      }
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      setIsStreaming(false);
      if (completed && !hasStreamError) onCompletedRef.current?.();
    }
  }, [options.projectId, options.threadId]);

  return { messages, isStreaming, send, reset, stop };
}

function safeJsonParse<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}
