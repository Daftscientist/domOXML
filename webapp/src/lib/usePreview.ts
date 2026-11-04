import { useEffect, useRef, useState } from "react";
import { engine } from "./engine";

// Preview renders are expensive enough (a Takumi layout + raster) that we
// debounce edits, cache by content hash, share one in-flight render between
// every surface asking for the same content (stage + rail thumbnail), and
// never let an older render overwrite a newer one.
const cache = new Map<string, string>();
const inFlight = new Map<string, Promise<string>>();
const MAX_CACHE = 60;

function renderOnce(key: string, html: string, opts: { width: number; height: number; css: string }): Promise<string> {
  const existing = inFlight.get(key);
  if (existing) return existing;
  const promise = engine
    .preview(html, opts)
    .then((png) => {
      const url = URL.createObjectURL(new Blob([png as BlobPart], { type: "image/png" }));
      if (cache.size >= MAX_CACHE) {
        const oldest = cache.keys().next().value;
        if (oldest) {
          URL.revokeObjectURL(cache.get(oldest)!);
          cache.delete(oldest);
        }
      }
      cache.set(key, url);
      return url;
    })
    .finally(() => inFlight.delete(key));
  inFlight.set(key, promise);
  return promise;
}

function hashOf(html: string, width: number, height: number, css: string): string {
  let h = 5381;
  const s = `${width}x${height}|${css}|${html}`;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return `${h >>> 0}`;
}

export interface PreviewState {
  url: string | null;
  loading: boolean;
  error: string | null;
}

export function usePreview(
  html: string,
  opts: { width: number; height: number; css: string },
): PreviewState {
  const key = hashOf(html, opts.width, opts.height, opts.css);
  const [state, setState] = useState<PreviewState>(() => ({
    url: cache.get(key) ?? null,
    loading: !cache.has(key),
    error: null,
  }));
  const generation = useRef(0);

  useEffect(() => {
    const cached = cache.get(key);
    if (cached) {
      setState({ url: cached, loading: false, error: null });
      return;
    }
    setState((s) => ({ url: s.url, loading: true, error: null }));
    const gen = ++generation.current;
    const timer = setTimeout(() => {
      renderOnce(key, html, { width: opts.width, height: opts.height, css: opts.css })
        .then((url) => {
          if (generation.current !== gen) return;
          setState({ url, loading: false, error: null });
        })
        .catch((error: Error) => {
          if (generation.current !== gen) return;
          setState((s) => ({ url: s.url, loading: false, error: error.message }));
        });
    }, 450);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
