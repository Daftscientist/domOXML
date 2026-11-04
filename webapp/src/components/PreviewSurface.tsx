import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { composePage } from "@/lib/composePage";

interface Props {
  /** Slide HTML fragment. */
  html: string;
  /** Deck stylesheet. */
  css?: string;
  /** Deck slide size in px; the iframe's internal viewport is exactly this. */
  width: number;
  height: number;
  alt: string;
  className?: string;
  style?: CSSProperties;
}

/**
 * Live slide preview: the composed slide document rendered by the browser
 * itself in a sandboxed iframe (scripts disabled, same-origin so geometry
 * stays readable later). The iframe is laid out at the deck's true pixel
 * size and CSS-scaled to fit its box, so the slide's internal layout,
 * viewport units and proportions are exactly the deck settings, and any
 * CSS the browser supports just works.
 */
export function PreviewSurface(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [srcdoc, setSrcdoc] = useState(() =>
    composePage(p.html, { width: p.width, height: p.height, css: p.css }),
  );

  // Recompose on content changes, trailing-debounced so typing does not
  // reload the iframe on every keystroke. Slide switches remount this
  // component at the call sites, so they render immediately.
  useEffect(() => {
    const next = composePage(p.html, { width: p.width, height: p.height, css: p.css });
    if (next === srcdoc) return;
    const t = setTimeout(() => setSrcdoc(next), 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.html, p.css, p.width, p.height]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const compute = () => {
      const r = el.getBoundingClientRect();
      setBox({ w: r.width, h: r.height });
    };
    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const scale = box.w > 0 && box.h > 0
    ? Math.min(box.w / p.width, box.h / p.height)
    : 0;

  return (
    <div
      ref={wrap}
      className={p.className}
      style={{ ...p.style, position: "relative", overflow: "hidden" }}
      role="img"
      aria-label={p.alt}
    >
      {scale > 0 && (
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            width: p.width * scale,
            height: p.height * scale,
            transform: "translate(-50%, -50%)",
          }}
        >
          <iframe
            title={p.alt}
            srcDoc={srcdoc}
            sandbox="allow-same-origin"
            scrolling="no"
            tabIndex={-1}
            style={{
              width: p.width,
              height: p.height,
              border: 0,
              transform: `scale(${scale})`,
              transformOrigin: "0 0",
              pointerEvents: "none",
              background: "#fff",
            }}
          />
        </div>
      )}
    </div>
  );
}
