import { Card } from "@/components/ui/card";
import { ModalityBadge } from "@/components/ModalityBadge";
import { PreviewThumb } from "@/components/PreviewThumb";
import type { SearchResult } from "@/lib/api";
import { formatSourceLocation } from "@/lib/utils";

interface SearchResultCardProps {
  result: SearchResult;
  onClick: () => void;
}

export function SearchResultCard({ result, onClick }: SearchResultCardProps) {
  const location = formatSourceLocation(result.modality, result.metadata);
  return (
    <Card className="overflow-hidden transition-all hover:-translate-y-0.5 hover:border-primary/35">
      <button
        type="button"
        onClick={onClick}
        className="flex w-full gap-3 p-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="media-frame h-20 w-20 shrink-0 overflow-hidden rounded-md border border-border/50">
          <PreviewThumb
            url={result.preview_url}
            modality={result.modality}
            alt={result.display_name}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium">
              {result.display_name}
            </span>
            <span className="shrink-0 rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-foreground">
              {(result.score * 100).toFixed(0)}%
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <ModalityBadge modality={result.modality} />
            {location && (
              <span className="text-[11px] font-medium text-foreground/80">
                {location}
              </span>
            )}
          </div>
          {result.snippet && (
            <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {result.snippet}
            </p>
          )}
        </div>
      </button>
    </Card>
  );
}

export function SearchResultSkeleton() {
  return (
    <Card className="overflow-hidden">
      <div className="flex gap-3 p-3">
        <div className="media-frame h-20 w-20 shrink-0 animate-pulse rounded-md" />
        <div className="flex-1 space-y-2">
          <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
          <div className="h-3 w-1/2 animate-pulse rounded bg-muted" />
          <div className="h-3 w-full animate-pulse rounded bg-muted" />
        </div>
      </div>
    </Card>
  );
}
