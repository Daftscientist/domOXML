import { useEffect, useRef, useState } from "react";
import { pathOf, resolvePath, type SlideMutation } from "@/lib/fragmentEdit";

interface Props {
  /** The stage preview's iframe; its document is the live slide. */
  iframe: HTMLIFrameElement | null;
  /** Deck slide size in px (the iframe's internal viewport). */
  width: number;
  height: number;
  /** Current slide HTML: changes when the document morphs. */
  html: string;
  focusPath: number[] | null;
  onFocusPath: (path: number[] | null) => void;
  onMutate: (path: number[], mutation: SlideMutation) => void;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface DragState {
  el: HTMLElement;
  path: number[];
  mode: "move" | "resize";
  handle: string;
  startX: number;
  startY: number;
  startBox: Box;
  /** CSS left/top the drag started from, in value space. */
  startLeft: number;
  startTop: number;
  position: string;
  lift: boolean;
  moved: boolean;
  originalStyle: string;
}

interface TextEdit {
  path: number[];
  box: Box;
  value: string;
  fontPx: number;
  fontFamily: string;
  color: string;
  textAlign: string;
}

const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const;
const HANDLE_CURSOR: Record<string, string> = {
  nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize",
  n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
};
const INLINE_TAGS = new Set([
  "SPAN", "B", "I", "EM", "STRONG", "A", "SMALL", "SUP", "SUB", "BR", "U", "S", "CODE", "ABBR", "MARK",
]);

/**
 * The visual editor over the stage: click to select the element under
 * the pointer (hit-tested in the live preview document), drag to move,
 * drag handles to resize, double-click a text element to edit its text,
 * arrows nudge, Delete removes. Every gesture commits back into the
 * slide's HTML via onMutate, so the HTML stays the document model and
 * everything downstream (preview morph, autosave, IR, export) follows.
 */
export function StageEditor(p: Props) {
  const overlay = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<{ path: number[]; box: Box } | null>(null);
  const [textEdit, setTextEdit] = useState<TextEdit | null>(null);
  const drag = useRef<DragState | null>(null);

  const doc = () => p.iframe?.contentDocument ?? null;

  const rectOf = (el: Element): Box => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  };

  /** The element a DOM path names in the live document, if it exists. */
  const live = (path: number[]): HTMLElement | null => {
    const d = doc();
    if (!d?.body) return null;
    return resolvePath(d.body, path) as HTMLElement | null;
  };

  // Keep the selection box glued to the focused element: resolve the
  // path again whenever focus changes or the document morphs.
  useEffect(() => {
    const path = p.focusPath;
    if (!path) {
      setSel(null);
      return;
    }
    let raf = 0;
    let tries = 0;
    const measure = () => {
      const el = live(path);
      if (el) {
        setSel({ path, box: rectOf(el) });
      } else if (tries++ < 20) {
        raf = requestAnimationFrame(measure);
      } else {
        setSel(null);
      }
    };
    measure();
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.focusPath, p.html, p.iframe]);

  const toSlide = (e: { clientX: number; clientY: number }): { x: number; y: number } => {
    const rect = overlay.current!.getBoundingClientRect();
    const scale = rect.width / p.width;
    return { x: (e.clientX - rect.left) / scale, y: (e.clientY - rect.top) / scale };
  };

  /** Hit-test the live document; returns the selectable element there. */
  const hit = (x: number, y: number): HTMLElement | null => {
    const d = doc();
    if (!d?.body) return null;
    const el = d.elementFromPoint(x, y) as HTMLElement | null;
    if (!el || el === (d as Document).documentElement || el === d.body) return null;
    // The slide root (a top-level element covering the whole slide) is
    // the canvas, not an object on it.
    if (el.parentElement === d.body) {
      const r = rectOf(el);
      if (r.w >= p.width * 0.99 && r.h >= p.height * 0.99) return null;
    }
    return el;
  };

  /** CSS left/top starting values for a drag, in value space. */
  const valueOrigin = (el: HTMLElement): { left: number; top: number; position: string } => {
    const view = doc()?.defaultView;
    const cs = view ? view.getComputedStyle(el) : null;
    const position = cs?.position ?? "static";
    if (position === "relative") {
      return {
        left: parseFloat(cs?.left ?? "") || 0,
        top: parseFloat(cs?.top ?? "") || 0,
        position,
      };
    }
    // Absolute, fixed, or a static element about to be lifted: CSS
    // left positions the margin box, offsetLeft measures the border
    // box from the offset parent's padding edge.
    const ml = parseFloat(cs?.marginLeft ?? "") || 0;
    const mt = parseFloat(cs?.marginTop ?? "") || 0;
    return { left: el.offsetLeft - ml, top: el.offsetTop - mt, position };
  };

  const beginDrag = (
    e: React.PointerEvent,
    el: HTMLElement,
    path: number[],
    mode: "move" | "resize",
    handle: string,
  ) => {
    const start = toSlide(e);
    const origin = valueOrigin(el);
    drag.current = {
      el,
      path,
      mode,
      handle,
      startX: start.x,
      startY: start.y,
      startBox: rectOf(el),
      startLeft: origin.left,
      startTop: origin.top,
      position: origin.position,
      lift: false,
      moved: false,
      originalStyle: el.getAttribute("style") ?? "",
    };
    const onMove = (ev: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      const now = toSlide(ev);
      const dx = now.x - d.startX;
      const dy = now.y - d.startY;
      if (!d.moved && Math.hypot(dx, dy) < 1.5) return;
      if (!d.moved && d.mode === "move" && d.position === "static") {
        d.lift = true;
        d.el.style.position = "absolute";
      }
      d.moved = true;
      const s = d.el.style;
      const b = d.startBox;
      if (d.mode === "move") {
        s.left = `${d.startLeft + dx}px`;
        s.top = `${d.startTop + dy}px`;
        setSel({ path: d.path, box: { ...b, x: b.x + dx, y: b.y + dy } });
      } else {
        const h = d.handle;
        let { x, y, w, hh } = { x: b.x, y: b.y, w: b.w, hh: b.h };
        if (h.includes("e")) w = Math.max(4, b.w + dx);
        if (h.includes("s")) hh = Math.max(4, b.h + dy);
        if (h.includes("w")) { w = Math.max(4, b.w - dx); x = b.x + (b.w - w); }
        if (h.includes("n")) { hh = Math.max(4, b.h - dy); y = b.y + (b.h - hh); }
        s.width = `${w}px`;
        s.height = `${hh}px`;
        if (d.position !== "static") {
          if (h.includes("w")) s.left = `${d.startLeft + (x - b.x)}px`;
          if (h.includes("n")) s.top = `${d.startTop + (y - b.y)}px`;
        }
        setSel({ path: d.path, box: { x, y, w, h: hh } });
      }
    };
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      const d = drag.current;
      drag.current = null;
      if (!d) return;
      if (!d.moved) return;
      const now = toSlide(ev);
      const dx = now.x - d.startX;
      const dy = now.y - d.startY;
      const b = d.startBox;
      if (d.mode === "move") {
        p.onMutate(d.path, {
          type: "box",
          left: d.startLeft + dx,
          top: d.startTop + dy,
          lift: d.lift || undefined,
        });
      } else {
        const h = d.handle;
        let w = b.w;
        let hh = b.h;
        if (h.includes("e")) w = Math.max(4, b.w + dx);
        if (h.includes("s")) hh = Math.max(4, b.h + dy);
        if (h.includes("w")) w = Math.max(4, b.w - dx);
        if (h.includes("n")) hh = Math.max(4, b.h - dy);
        const mutation: SlideMutation = { type: "box", width: w, height: hh };
        if (d.position !== "static") {
          if (h.includes("w")) mutation.left = d.startLeft - (w - b.w);
          if (h.includes("n")) mutation.top = d.startTop - (hh - b.h);
        }
        p.onMutate(d.path, mutation);
      }
      // The morph re-renders from the committed fragment; the selection
      // effect re-measures the box from the fresh document.
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    overlay.current?.focus();
    if (textEdit) setTextEdit(null);
    const target = e.target as HTMLElement;
    const handle = target.dataset.handle;
    const { x, y } = toSlide(e);
    if (handle && sel) {
      const el = live(sel.path);
      if (el) {
        e.preventDefault();
        beginDrag(e, el, sel.path, "resize", handle);
        return;
      }
    }
    const el = hit(x, y);
    if (!el) {
      p.onFocusPath(null);
      return;
    }
    const path = pathOf(el);
    if (!path) return;
    e.preventDefault();
    p.onFocusPath(path);
    beginDrag(e, el, path, "move", "");
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    const { x, y } = toSlide(e);
    const el = hit(x, y);
    if (!el) return;
    const children = Array.from(el.children);
    const editable =
      (children.length === 0 || children.every((c) => INLINE_TAGS.has(c.tagName))) &&
      (el.textContent ?? "").trim().length > 0;
    if (!editable) return;
    const path = pathOf(el);
    if (!path) return;
    const view = doc()?.defaultView;
    const cs = view ? view.getComputedStyle(el) : null;
    const scale = (overlay.current?.getBoundingClientRect().width ?? p.width) / p.width;
    setTextEdit({
      path,
      box: rectOf(el),
      value: el.textContent ?? "",
      fontPx: (parseFloat(cs?.fontSize ?? "16") || 16) * scale,
      fontFamily: cs?.fontFamily ?? "inherit",
      color: cs?.color ?? "inherit",
      textAlign: cs?.textAlign ?? "left",
    });
    p.onFocusPath(path);
  };

  const commitNudge = (dx: number, dy: number) => {
    if (!sel) return;
    const el = live(sel.path);
    if (!el) return;
    const origin = valueOrigin(el);
    p.onMutate(sel.path, {
      type: "box",
      left: origin.left + dx,
      top: origin.top + dy,
      lift: origin.position === "static" || undefined,
    });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.target !== overlay.current || textEdit) return;
    if (!sel) return;
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      p.onMutate(sel.path, { type: "remove" });
      p.onFocusPath(null);
    } else if (e.key === "Escape") {
      p.onFocusPath(null);
    } else if (e.key === "ArrowLeft") { e.preventDefault(); commitNudge(-step, 0); }
    else if (e.key === "ArrowRight") { e.preventDefault(); commitNudge(step, 0); }
    else if (e.key === "ArrowUp") { e.preventDefault(); commitNudge(0, -step); }
    else if (e.key === "ArrowDown") { e.preventDefault(); commitNudge(0, step); }
  };

  const selPct = sel
    ? {
        left: `${(sel.box.x / p.width) * 100}%`,
        top: `${(sel.box.y / p.height) * 100}%`,
        width: `${(sel.box.w / p.width) * 100}%`,
        height: `${(sel.box.h / p.height) * 100}%`,
      }
    : null;

  const handlePos = (h: string): React.CSSProperties => {
    const xPct = h === "nw" || h === "w" || h === "sw" ? 0 : h === "ne" || h === "e" || h === "se" ? 100 : 50;
    const yPct = h === "nw" || h === "n" || h === "ne" ? 0 : h === "sw" || h === "s" || h === "se" ? 100 : 50;
    return {
      left: `${xPct}%`,
      top: `${yPct}%`,
      transform: "translate(-50%, -50%)",
      cursor: HANDLE_CURSOR[h],
    };
  };
  return (
    <div
      ref={overlay}
      className="absolute inset-0 z-10 outline-none"
      style={{ touchAction: "none" }}
      tabIndex={0}
      role="application"
      aria-label="Slide design surface. Click an element to select it, drag to move, double-click text to edit."
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
    >
      {sel && selPct && (
        <div
          className="pointer-events-none absolute border-2 border-primary"
          style={{ ...selPct, boxShadow: "0 0 0 1px rgba(255,255,255,0.7)" }}
        >
          {HANDLES.map((h) => (
            <div
              key={h}
              data-handle={h}
              className="pointer-events-auto absolute h-2.5 w-2.5 rounded-[2px] border border-primary bg-white"
              style={handlePos(h)}
            />
          ))}
        </div>
      )}
      {textEdit && (
        <textarea
          autoFocus
          value={textEdit.value}
          onChange={(e) => setTextEdit({ ...textEdit, value: e.target.value })}
          onPointerDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              p.onMutate(textEdit.path, { type: "text", text: textEdit.value });
              setTextEdit(null);
            } else if (e.key === "Escape") {
              setTextEdit(null);
            }
          }}
          onBlur={() => {
            p.onMutate(textEdit.path, { type: "text", text: textEdit.value });
            setTextEdit(null);
          }}
          className="absolute z-20 resize-none overflow-hidden rounded-[2px] bg-white/95 p-0 outline-2 outline-primary"
          style={{
            left: `${(textEdit.box.x / p.width) * 100}%`,
            top: `${(textEdit.box.y / p.height) * 100}%`,
            width: `${(textEdit.box.w / p.width) * 100}%`,
            height: `${(textEdit.box.h / p.height) * 100}%`,
            fontSize: textEdit.fontPx,
            fontFamily: textEdit.fontFamily,
            color: textEdit.color,
            textAlign: textEdit.textAlign as React.CSSProperties["textAlign"],
          }}
        />
      )}
    </div>
  );
}
