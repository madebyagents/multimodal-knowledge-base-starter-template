import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ModalityBadge } from "@/components/ModalityBadge";
import { PreviewThumb } from "@/components/PreviewThumb";
import { formatSourceLocation } from "@/lib/utils";

export interface PreviewDialogItem {
  display_name: string;
  modality: string;
  preview_url: string | null;
  snippet?: string;
  score?: number;
  metadata?: Record<string, unknown>;
}

interface PreviewDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  item: PreviewDialogItem | null;
}

export function PreviewDialog({
  open,
  onOpenChange,
  item,
}: PreviewDialogProps) {
  const [showMeta, setShowMeta] = useState(false);
  if (!item) return null;
  const meta = item.metadata ?? {};
  const location = formatSourceLocation(item.modality, meta);
  const descriptionParts = [
    location,
    typeof item.score === "number"
      ? `Relevance score: ${(item.score * 100).toFixed(1)}%`
      : null,
  ].filter(Boolean);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="preview-dialog-panel max-w-3xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <ModalityBadge modality={item.modality} />
            <DialogTitle className="truncate text-base">
              {item.display_name}
            </DialogTitle>
          </div>
          {descriptionParts.length > 0 && (
            <DialogDescription>
              {descriptionParts.join(" · ")}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="media-frame mt-4 overflow-hidden rounded-lg border border-border/70">
          <div className="flex max-h-[55vh] items-center justify-center">
            <PreviewThumb
              url={item.preview_url}
              modality={item.modality}
              alt={item.display_name}
              className="max-h-[55vh] w-full object-contain"
            />
          </div>
        </div>

        {item.snippet && (
          <div className="comfortable-scrollbar mt-4 max-h-40 overflow-y-auto rounded-md border bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
            {item.snippet}
          </div>
        )}

        <div className="mt-4 text-xs">
          <button
            type="button"
            onClick={() => setShowMeta((v) => !v)}
            className="text-muted-foreground hover:text-foreground"
          >
            {showMeta ? "Hide" : "Show"} metadata
          </button>
          {showMeta && (
            <pre className="comfortable-scrollbar mt-2 max-h-48 overflow-auto rounded-md border bg-muted/40 p-3 text-[11px] text-muted-foreground">
              {JSON.stringify(meta, null, 2)}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
