import {
  forwardRef,
  useImperativeHandle,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ImagePlus, Search, SearchX, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { ModalityFilter } from "@/components/ModalityFilter";
import {
  SearchResultCard,
  SearchResultSkeleton,
} from "@/components/SearchResultCard";
import {
  PreviewDialog,
  type PreviewDialogItem,
} from "@/components/PreviewDialog";
import { useSearch } from "@/hooks/useSearch";
import { useImageSearch } from "@/hooks/useImageSearch";
import type { SearchResult } from "@/lib/api";

export interface SearchPanelHandle {
  focus(): void;
}

export const SearchPanel = forwardRef<SearchPanelHandle>(
  function SearchPanel(_props, ref) {
    const [draft, setDraft] = useState("");
    const [submitted, setSubmitted] = useState("");
    const [modalityFilter, setModalityFilter] = useState<string[]>([]);
    const [topK, setTopK] = useState(8);
    const [imagePreview, setImagePreview] = useState<string | null>(null);
    const [imageResults, setImageResults] = useState<SearchResult[] | null>(
      null,
    );
    const [previewItem, setPreviewItem] = useState<PreviewDialogItem | null>(
      null,
    );

    const inputRef = useRef<HTMLInputElement>(null);
    const imageInput = useRef<HTMLInputElement>(null);

    useImperativeHandle(ref, () => ({
      focus: () => inputRef.current?.focus(),
    }));

    const textSearch = useSearch({
      query: submitted,
      topK,
      modalityFilter: modalityFilter.length ? modalityFilter : null,
    });
    const imageSearch = useImageSearch();

    const onSubmit = (e: FormEvent) => {
      e.preventDefault();
      setSubmitted(draft.trim());
      setImageResults(null);
      setImagePreview(null);
    };

    const onPickImage = () => imageInput.current?.click();
    const onImageChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setSubmitted("");
      setDraft("");
      const url = URL.createObjectURL(file);
      setImagePreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      try {
        const res = await imageSearch.mutateAsync({
          file,
          topK,
          modalityFilter: modalityFilter.length ? modalityFilter : null,
        });
        setImageResults(res.results);
      } catch {
        // toast handled in hook (none yet); fall through, error state shown below
        setImageResults(null);
      }
    };

    const clearImage = () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      setImagePreview(null);
      setImageResults(null);
    };

    const usingImageMode = imagePreview !== null;
    const isLoading = usingImageMode
      ? imageSearch.isPending
      : textSearch.isFetching;
    const results: SearchResult[] = usingImageMode
      ? (imageResults ?? [])
      : (textSearch.data?.results ?? []);
    const hasQuery = usingImageMode || submitted.trim().length > 0;

    return (
      <section className="flex h-full min-w-0 flex-col gap-4">
        <header className="min-w-0">
          <h2 className="text-lg font-semibold">Search</h2>
          <p className="max-w-full break-words text-sm text-muted-foreground">
            Cross-modal: a text query hits images, PDFs, videos, and notes
            alike.
          </p>
        </header>

        <div className="slack-panel comfortable-scrollbar flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          <form onSubmit={onSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  ref={inputRef}
                  type="search"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder='Try "engineering retrospective" or "Q3 revenue"…'
                  className="slack-panel-input pl-9"
                  autoComplete="off"
                />
              </div>
              <Button
                type="submit"
                disabled={draft.trim().length === 0}
                className="w-full sm:w-auto"
              >
                Search
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onPickImage}
                title="Search by image"
                aria-label="Search by image"
                className="w-full sm:w-auto"
              >
                <ImagePlus className="h-4 w-4" />
                Image
              </Button>
              <input
                ref={imageInput}
                type="file"
                accept="image/*"
                hidden
                onChange={onImageChosen}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <ModalityFilter
                value={modalityFilter}
                onChange={setModalityFilter}
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                Top
                <input
                  type="number"
                  min={1}
                  max={25}
                  value={topK}
                  onChange={(e) =>
                    setTopK(
                      Math.max(1, Math.min(25, Number(e.target.value) || 1)),
                    )
                  }
                  className="slack-panel-input h-7 w-14 rounded-md border border-input bg-background px-2 text-center text-xs"
                />
              </label>
            </div>
          </form>

          {usingImageMode && imagePreview && (
            <div className="surface-card flex items-center gap-3 rounded-lg border bg-muted/30 p-3">
              <img
                src={imagePreview}
                alt="query"
                className="media-frame h-16 w-16 rounded-md border border-border/50 object-cover"
              />
              <div className="flex-1 text-sm">
                <div className="font-medium">Searching by image</div>
                <div className="text-xs text-muted-foreground">
                  Showing items visually similar to your query image.
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={clearImage}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          )}

          {isLoading ? (
            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <SearchResultSkeleton key={i} />
              ))}
            </div>
          ) : !hasQuery ? (
            <EmptyState
              icon={Search}
              title="Search across everything you've uploaded"
              description="Text, images, PDFs and videos all share one embedding space — a single query hits them all."
            />
          ) : results.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No matches"
              description="Try a different query or different modality filters."
            />
          ) : (
            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
              {results.map((r) => (
                <SearchResultCard
                  key={r.node_id}
                  result={r}
                  onClick={() =>
                    setPreviewItem({
                      display_name: r.display_name,
                      modality: r.modality,
                      preview_url: r.preview_url,
                      snippet: r.snippet,
                      score: r.score,
                      metadata: r.metadata,
                    })
                  }
                />
              ))}
            </div>
          )}

          {imageSearch.isError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              Image search failed: {imageSearch.error?.message}
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
  },
);
