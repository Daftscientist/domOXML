import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Idiomorph } from "idiomorph";
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
 * stays readable later), laid out at the deck's true pixel size and
 * CSS-scaled to fit its box.
 *
 * The iframe is persistent: after the initial srcdoc load, edits are
 * applied by morphing the live document (idiomorph) instead of reloading
 * it, so unchanged subtrees (images, glass layers, text runs) are never
 * torn down and there is no reload flicker. Only what actually changed
 * in the DOM is mutated.
 */
export function PreviewSurface(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const appliedRef = useRef<string>("");
  const latestRef = useRef<string>("");
  const [box, setBox] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  // The initial document; only ever replaced as a fallback if morphing
  // itself fails, never on ordinary edits.
  const [initialDoc] = useState(() =>
    composePage(p.html, { width: p.width, height: p.height, css: p.css }),
  );
  const [fallbackDoc, setFallbackDoc] = useState<string | null>(null);

  const applyMorph = (next: string) => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc || !readyRef.current) return;
    try {
      const parsed = new DOMParser().parseFromString(next, "text/html");
      // Head: the composed document carries at most two <style> elements
      // (framework, then the deck stylesheet). Sync them by index —
      // text-only changes, no node churn.
      const liveStyles = doc.head.querySelectorAll("style");
      const newStyles = parsed.head.querySelectorAll("style");
      if (liveStyles.length === newStyles.length) {
        newStyles.forEach((s, i) => {
          if (liveStyles[i].textContent !== s.textContent) {
            liveStyles[i].textContent = s.textContent;
          }
        });
      } else {
        doc.head.innerHTML = parsed.head.innerHTML;
      }
      // Body: morph the live DOM to the new DOM, preserving every
      // subtree that did not change.
      Idiomorph.morph(doc.body, parsed.body, { morphStyle: "innerHTML" });
      appliedRef.current = next;
    } catch {
      // Morphing is an optimisation; a full reload is always correct.
      readyRef.current = false;
      appliedRef.current = next;
      setFallbackDoc(next);
    }
  };
  const applyRef = useRef(applyMorph);
  applyRef.current = applyMorph;

  useEffect(() => {
    const next = composePage(p.html, { width: p.width, height: p.height, css: p.css });
    latestRef.current = next;
    if (next === appliedRef.current) return;
    const t = setTimeout(() => applyRef.current(next), 60);
    return () => clearTimeout(t);
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
            ref={iframeRef}
            title={p.alt}
            srcDoc={fallbackDoc ?? initialDoc}
            sandbox="allow-same-origin"
            scrolling="no"
            tabIndex={-1}
            onLoad={() => {
              readyRef.current = true;
              if (!appliedRef.current) {
                appliedRef.current = fallbackDoc ?? initialDoc;
              }
              // Edits that arrived while this document was loading were
              // recorded in latestRef; apply them now.
              if (latestRef.current && latestRef.current !== appliedRef.current) {
                applyRef.current(latestRef.current);
              }
            }}
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
