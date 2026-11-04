import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { usePreview } from "@/lib/usePreview";
import type { Deck } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  deck: Deck;
  startAt: number;
  onClose: () => void;
}

const ANIMATION_FOR: Record<string, string> = {
  fade: "present-fade",
  push: "present-push",
  wipe: "present-wipe",
  zoom: "present-zoom",
  cover: "present-push",
  uncover: "present-fade",
  split: "present-wipe",
  dissolve: "present-fade",
  morph: "present-zoom",
  cut: "",
};

export function PresentMode(p: Props) {
  const [index, setIndex] = useState(p.startAt);
  const [enteredAt, setEnteredAt] = useState(0);
  const slide = p.deck.slides[index];
  const preview = usePreview(slide?.html ?? "", {
    width: p.deck.width, height: p.deck.height, css: p.deck.css,
    priority: 10, sessionKey: p.deck.id,
  });

  const go = useCallback(
    (next: number) => {
      const clamped = Math.max(0, Math.min(p.deck.slides.length - 1, next));
      if (clamped !== index) {
        setIndex(clamped);
        setEnteredAt(Date.now());
      }
    },
    [index, p.deck.slides.length],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") p.onClose();
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") { e.preventDefault(); go(index + 1); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(index - 1); }
      if (e.key === "Home") go(0);
      if (e.key === "End") go(p.deck.slides.length - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, index, p]);

  if (!slide) return null;
  const animation = slide.transition ? ANIMATION_FOR[slide.transition.type] ?? "" : "";
  const duration = slide.transition?.duration_ms ?? 400;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black" role="dialog" aria-label="Presentation mode">
      <div
        className="relative flex min-h-0 flex-1 cursor-pointer items-center justify-center"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (e.clientX - rect.left < rect.width * 0.25) go(index - 1);
          else go(index + 1);
        }}
      >
        {preview.url && (
          <img
            key={`${slide.id}-${enteredAt}`}
            src={preview.url}
            alt={`Slide ${index + 1}`}
            className={cn("max-h-full max-w-full object-contain", animation)}
            style={{ "--pt-dur": `${duration}ms` } as React.CSSProperties}
            draggable={false}
          />
        )}
      </div>
      <div className="flex h-12 items-center justify-between px-4 text-neutral-400">
        <span className="text-xs tabular-nums">
          {index + 1} / {p.deck.slides.length}
          {slide.transition && (
            <span className="ml-3 capitalize">{slide.transition.type} · {duration}ms</span>
          )}
        </span>
        <span className="hidden text-xs sm:block">{p.deck.name}</span>
        <button
          onClick={p.onClose}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-neutral-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" /> Esc to exit
        </button>
      </div>
    </div>
  );
}
