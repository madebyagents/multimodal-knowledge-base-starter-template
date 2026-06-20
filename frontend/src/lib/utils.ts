import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import {
  type LucideIcon,
  Image as ImageIcon,
  FileText,
  Video,
  FileType,
  HelpCircle,
} from "lucide-react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type Modality = "image" | "pdf" | "video" | "text";

export const MODALITY: Record<
  Modality | "unknown",
  { color: string; icon: LucideIcon; label: string }
> = {
  image: {
    color:
      "border-[#BD8EF1]/40 bg-[#BD8EF1]/15 text-[#543771] dark:text-[#E3CDFF]",
    icon: ImageIcon,
    label: "Image",
  },
  pdf: {
    color:
      "border-[#C9A93F]/40 bg-[#C9A93F]/15 text-[#534610] dark:text-[#F3ECD0]",
    icon: FileText,
    label: "PDF",
  },
  video: {
    color:
      "border-[#85DA7C]/40 bg-[#85DA7C]/15 text-[#13560E] dark:text-[#D4F7D0]",
    icon: Video,
    label: "Video",
  },
  text: {
    color:
      "border-[#B6FFBA]/40 bg-[#B6FFBA]/15 text-[#1F3507] dark:text-[#EAFCE7]",
    icon: FileType,
    label: "Text",
  },
  unknown: {
    color:
      "border-[#A3A58C]/35 bg-[#A3A58C]/15 text-[#4C473B] dark:text-[#C7D2B0]",
    icon: HelpCircle,
    label: "Unknown",
  },
};

/**
 * Build a short human-readable location string from a source's metadata —
 * "Page 4 of 12" for PDFs, "@ 12.3s" for video frames, otherwise null.
 * Tolerates the legacy multi-page chunk format (page_start < page_end).
 */
export function formatSourceLocation(
  modality: string,
  metadata: Record<string, unknown> | undefined,
): string | null {
  if (!metadata) return null;
  if (modality === "pdf") {
    const start = numberOrNull(metadata.page ?? metadata.page_start);
    if (start == null) return null;
    const end = numberOrNull(metadata.page_end) ?? start;
    const total = numberOrNull(metadata.total_pages);
    const range = start === end ? `Page ${start}` : `Pages ${start}–${end}`;
    return total ? `${range} of ${total}` : range;
  }
  if (modality === "video") {
    const ts = numberOrNull(metadata.timestamp_seconds);
    if (ts == null) return null;
    return `@ ${ts.toFixed(1)}s`;
  }
  return null;
}

function numberOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) {
    return Number(v);
  }
  return null;
}

export function formatRelativeTime(iso: string | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (isNaN(then)) return iso;
  const diff = Date.now() - then;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}
