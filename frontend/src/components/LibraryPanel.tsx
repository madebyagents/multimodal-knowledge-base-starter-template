import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { FolderOpen, Trash2, Upload, Loader2 } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { ModalityBadge } from "@/components/ModalityBadge";
import { PreviewThumb } from "@/components/PreviewThumb";
import {
  PreviewDialog,
  type PreviewDialogItem,
} from "@/components/PreviewDialog";
import { useItems } from "@/hooks/useItems";
import { useDeleteItem } from "@/hooks/useDeleteItem";
import { useIngest } from "@/hooks/useIngest";
import { formatRelativeTime } from "@/lib/utils";
import type { Item } from "@/lib/api";

function LibraryCardSkeleton() {
  return (
    <Card className="overflow-hidden">
      <Skeleton className="aspect-[4/3] w-full rounded-none" />
      <div className="space-y-2 p-3">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </Card>
  );
}

function LibraryCard({
  item,
  onPreview,
  onDelete,
  deleting,
}: {
  item: Item;
  onPreview: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <Card className="group relative overflow-hidden transition-all hover:-translate-y-0.5 hover:border-primary/35">
      <button
        type="button"
        onClick={onPreview}
        className="block w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="media-frame aspect-[4/3] w-full overflow-hidden">
          <PreviewThumb
            url={item.preview_url}
            modality={item.modality}
            alt={item.original_name}
            className="h-full w-full transition-transform group-hover:scale-105"
          />
        </div>
        <div className="space-y-1 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium">
              {item.original_name}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <ModalityBadge modality={item.modality} />
            <span>{formatRelativeTime(item.upload_time)}</span>
          </div>
        </div>
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        disabled={deleting}
        aria-label={`Delete ${item.original_name}`}
        className="absolute right-2 top-2 rounded-md border bg-background/90 p-1.5 text-muted-foreground opacity-0 shadow-sm backdrop-blur transition-opacity hover:text-destructive group-hover:opacity-100 focus:opacity-100"
      >
        {deleting ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Trash2 className="h-3.5 w-3.5" />
        )}
      </button>
    </Card>
  );
}

export function LibraryPanel() {
  const items = useItems();
  const del = useDeleteItem();
  const ingest = useIngest();
  const [preview, setPreview] = useState<PreviewDialogItem | null>(null);

  const onDrop = (files: File[]) => {
    if (files.length > 0) ingest.mutate({ files });
  };
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    noClick: true,
    noKeyboard: true,
  });

  const list = items.data?.items ?? [];
  const total = items.data?.total ?? list.length;

  return (
    <section
      {...getRootProps()}
      className="relative flex h-full min-w-0 flex-col gap-4"
    >
      <input {...getInputProps()} />
      {isDragActive && (
        <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-primary/10 backdrop-blur-sm">
          <div className="surface-card rounded-lg border-2 border-dashed border-primary bg-background/95 px-8 py-6 text-center">
            <Upload className="mx-auto h-8 w-8 text-primary" />
            <p className="mt-2 text-sm font-medium">Drop files to ingest</p>
          </div>
        </div>
      )}

      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Library</h2>
          <p className="text-sm text-muted-foreground">
            {items.isLoading
              ? "Loading…"
              : `${total} item${total === 1 ? "" : "s"}`}
            {" · "}drag and drop to upload
          </p>
        </div>
      </header>

      <div className="slack-panel comfortable-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        {items.isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <LibraryCardSkeleton key={i} />
            ))}
          </div>
        ) : list.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="Your knowledge base is empty"
            description="Drag and drop files anywhere on this panel, or use Upload files in Settings."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {list.map((it) => (
              <LibraryCard
                key={it.file_id}
                item={it}
                deleting={del.isPending && del.variables === it.file_id}
                onPreview={() =>
                  setPreview({
                    display_name: it.original_name,
                    modality: it.modality,
                    preview_url: it.preview_url,
                  })
                }
                onDelete={() => del.mutate(it.file_id)}
              />
            ))}
          </div>
        )}
      </div>

      <PreviewDialog
        open={preview !== null}
        onOpenChange={(v) => !v && setPreview(null)}
        item={preview}
      />
    </section>
  );
}
