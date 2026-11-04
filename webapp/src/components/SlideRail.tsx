import { Copy, Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { usePreview } from "@/lib/usePreview";
import type { Deck } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  deck: Deck;
  selected: number;
  onSelect: (index: number) => void;
  onAdd: () => void;
  onDuplicate: (index: number) => void;
  onDelete: (index: number) => void;
}

function Thumb({ deck, index }: { deck: Deck; index: number }) {
  const slide = deck.slides[index];
  const preview = usePreview(slide.html, { width: deck.width, height: deck.height, css: deck.css });
  return (
    <div
      className="relative w-full overflow-hidden rounded-[4px] bg-white"
      style={{ aspectRatio: `${deck.width} / ${deck.height}` }}
    >
      {preview.url ? (
        <img src={preview.url} alt={`Slide ${index + 1}`} className="h-full w-full object-cover" draggable={false} />
      ) : (
        <Skeleton className="h-full w-full rounded-none" />
      )}
    </div>
  );
}

export function SlideRail(p: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex items-center justify-between px-3 pb-1 pt-3">
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Slides</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={p.onAdd} aria-label="Add slide">
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-1 px-2 pb-2">
          {p.deck.slides.map((slide, index) => (
            <div
              key={slide.id}
              className={cn(
                "group relative flex cursor-pointer gap-2.5 rounded-lg p-2 transition-colors",
                index === p.selected ? "bg-accent" : "hover:bg-accent/60",
              )}
              onClick={() => p.onSelect(index)}
            >
              <span
                className={cn(
                  "w-4 shrink-0 pt-0.5 text-right text-xs tabular-nums",
                  index === p.selected ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className={cn(
                    "overflow-hidden rounded-[4px] ring-1 ring-border",
                    index === p.selected && "ring-2 ring-primary ring-offset-1 ring-offset-background",
                  )}
                >
                  <Thumb deck={p.deck} index={index} />
                </div>
                <div className="mt-1.5 flex h-5 items-center justify-between">
                  {slide.transition ? (
                    <span className="flex items-center gap-1 text-[11px] capitalize text-muted-foreground">
                      <Sparkles className="h-3 w-3" />
                      {slide.transition.type}
                      {slide.transition.duration_ms ? ` · ${slide.transition.duration_ms}ms` : ""}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground/60">No transition</span>
                  )}
                  <span className="flex opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                      aria-label={`Duplicate slide ${index + 1}`}
                      onClick={(e) => { e.stopPropagation(); p.onDuplicate(index); }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    <button
                      className="rounded p-0.5 text-muted-foreground hover:text-destructive"
                      aria-label={`Delete slide ${index + 1}`}
                      onClick={(e) => { e.stopPropagation(); p.onDelete(index); }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </div>
              </div>
            </div>
          ))}
          <Button variant="outline" className="mt-1 border-dashed" onClick={p.onAdd}>
            <Plus className="h-4 w-4" /> Add slide
          </Button>
        </div>
      </ScrollArea>
    </div>
  );
}
