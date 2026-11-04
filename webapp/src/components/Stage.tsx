import { useRef, useState, useEffect } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePreview } from "@/lib/usePreview";
import type { Deck } from "@/lib/types";

interface Props {
  deck: Deck;
  selected: number;
  onSelect: (index: number) => void;
}

export function Stage(p: Props) {
  const slide = p.deck.slides[p.selected];
  const preview = usePreview(slide?.html ?? "", {
    width: p.deck.width, height: p.deck.height, css: p.deck.css,
  });
  const frame = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  // Size the slide box explicitly from the measured frame: the largest
  // deck-aspect rectangle that fits, so the slide is never distorted.
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const compute = () => {
      const rect = el.getBoundingClientRect();
      const pad = window.innerWidth < 640 ? 24 : 56;
      const availW = Math.max(0, rect.width - pad);
      const availH = Math.max(0, rect.height - pad);
      const ratio = p.deck.width / p.deck.height;
      const w = Math.floor(Math.min(availW, availH * ratio));
      setBox({ w, h: Math.floor(w / ratio) });
    };
    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(el);
    return () => observer.disconnect();
  }, [p.deck.width, p.deck.height]);

  if (!slide) {
    return (
      <div className="stage-backdrop flex h-full items-center justify-center bg-muted/40">
        <p className="text-sm text-muted-foreground">Add a slide to get started.</p>
      </div>
    );
  }
  const fit = box.w ? Math.max(1, Math.round((box.w / p.deck.width) * 100)) : 100;

  return (
    <div className="flex h-full min-h-0 flex-col bg-muted/40">
      <div ref={frame} className="stage-backdrop relative flex min-h-0 flex-1 items-center justify-center overflow-hidden">
        <div
          className="slide-shadow relative shrink-0 overflow-hidden rounded-[2px] bg-white"
          style={{ width: box.w || undefined, height: box.h || undefined }}
        >
          {preview.url ? (
            <img
              key={preview.url}
              src={preview.url}
              alt={`Slide ${p.selected + 1} preview`}
              className="h-full w-full"
              draggable={false}
            />
          ) : preview.error ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-6 text-center">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              <p className="text-sm font-medium">This slide could not be rendered</p>
              <p className="max-w-md text-xs leading-relaxed text-muted-foreground">{preview.error}</p>
            </div>
          ) : (
            <Skeleton className="h-full w-full rounded-none" />
          )}
          {preview.loading && preview.url && (
            <div className="absolute right-2.5 top-2.5 flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-medium text-white">
              <Loader2 className="h-3 w-3 animate-spin" /> Rendering
            </div>
          )}
        </div>
      </div>
      <div className="flex h-11 shrink-0 items-center justify-center gap-2 border-t bg-background px-3">
        <Button
          variant="ghost" size="icon" className="h-7 w-7"
          disabled={p.selected === 0}
          onClick={() => p.onSelect(p.selected - 1)}
          aria-label="Previous slide"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-16 text-center text-xs tabular-nums text-muted-foreground">
          {p.selected + 1} / {p.deck.slides.length}
        </span>
        <Button
          variant="ghost" size="icon" className="h-7 w-7"
          disabled={p.selected >= p.deck.slides.length - 1}
          onClick={() => p.onSelect(p.selected + 1)}
          aria-label="Next slide"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <span className="ml-3 hidden text-xs tabular-nums text-muted-foreground sm:inline">
          {p.deck.width} × {p.deck.height} · {fit}%
        </span>
        <span className="ml-1 hidden text-xs text-muted-foreground md:inline">
          Rendered by Takumi
        </span>
      </div>
    </div>
  );
}
