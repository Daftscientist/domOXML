import { useRef, useState, useEffect } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PreviewSurface } from "./PreviewSurface";
import { StageEditor } from "./StageEditor";
import type { SlideMutation } from "@/lib/fragmentEdit";
import type { Deck } from "@/lib/types";

interface Props {
  deck: Deck;
  selected: number;
  onSelect: (index: number) => void;
  focusPath: number[] | null;
  onFocusPath: (path: number[] | null) => void;
  onMutate: (path: number[], mutation: SlideMutation) => void;
}

export function Stage(p: Props) {
  const slide = p.deck.slides[p.selected];
  const frame = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [iframe, setIframe] = useState<HTMLIFrameElement | null>(null);

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
          <PreviewSurface
            key={slide.id}
            html={slide.html}
            css={p.deck.css}
            width={p.deck.width}
            height={p.deck.height}
            alt={`Slide ${p.selected + 1} preview`}
            className="h-full w-full"
            iframeRef={setIframe}
          />
          <StageEditor
            iframe={iframe}
            width={p.deck.width}
            height={p.deck.height}
            html={slide.html}
            focusPath={p.focusPath}
            onFocusPath={p.onFocusPath}
            onMutate={p.onMutate}
          />
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
          Rendered live by your browser
        </span>
      </div>
    </div>
  );
}
