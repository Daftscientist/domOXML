import { useEffect, useRef, useState } from "react";
import { engine } from "./engine";
import { previewClient } from "./previewClient";

// Previews are painted from Takumi's paint tree by our own canvas painter
// in a dedicated worker (see lib/treePainter): no PNG round trip, no
// waiting on the Python engine. Slides the painter cannot reproduce
// faithfully fall back to the engine's takumi-js raster for that slide.
//
// Renders run one at a time in priority order (stage first, then visible
// thumbnails) and are cached by content hash, shared between surfaces
// asking for the same content at the same resolution bucket.

export type PreviewResult = { bitmap: ImageBitmap } | { url: string };

const cache = new Map<string, PreviewResult>();
const MAX_CACHE = 60;

interface Job {
  key: string;
  html: string;
  width: number;
  height: number;
  css: string;
  targetWidth: number;
  priority: number;
  seq: number;
  waiters: { resolve: (r: PreviewResult) => void; reject: (error: Error) => void }[];
}

const queued = new Map<string, Job>();
let runningJob: Job | null = null;
let seq = 0;

function bucketOf(targetWidth: number): number {
  for (const bucket of [384, 768, 1280, 1920, 2560]) {
    if (targetWidth <= bucket) return bucket;
  }
  return 3200;
}

async function execute(job: Job): Promise<PreviewResult> {
  try {
    const { bitmap, stats } = await previewClient.render(job.html, {
      width: job.width,
      height: job.height,
      css: job.css,
      targetWidth: job.targetWidth,
    });
    if (typeof localStorage !== "undefined" && localStorage.getItem("domoxml-debug-paint")) {
      console.debug(`[paint] ${stats.ms}ms repainted=${stats.repainted} reused=${stats.reused}`);
    }
    return { bitmap };
  } catch (error) {
    // Any canvas-painter failure (unsupported paint, a decode quirk, a
    // worker problem) falls back to the engine's takumi-js raster for
    // this slide; the painter is an optimisation, never a hard dependency.
    if (typeof localStorage !== "undefined" && localStorage.getItem("domoxml-debug-paint")) {
      console.debug(`[paint] canvas path failed, using engine raster: ${(error as Error).message}`);
    }
    try {
      const png = await engine.preview(job.html, {
        width: job.width, height: job.height, css: job.css,
      });
      return { url: URL.createObjectURL(new Blob([png as BlobPart], { type: "image/png" })) };
    } catch {
      throw error;
    }
  }
}

function pump() {
  if (runningJob) return;
  let next: Job | undefined;
  for (const job of queued.values()) {
    if (!next || job.priority > next.priority || (job.priority === next.priority && job.seq < next.seq)) {
      next = job;
    }
  }
  if (!next) return;
  queued.delete(next.key);
  runningJob = next;
  const job = next;
  execute(job)
    .then((result) => {
      if (cache.size >= MAX_CACHE) {
        const oldest = cache.keys().next().value;
        if (oldest) {
          const old = cache.get(oldest)!;
          if ("url" in old) URL.revokeObjectURL(old.url);
          else old.bitmap.close();
          cache.delete(oldest);
        }
      }
      cache.set(job.key, result);
      for (const w of job.waiters) w.resolve(result);
    })
    .catch((error: Error) => {
      for (const w of job.waiters) w.reject(error);
    })
    .finally(() => {
      runningJob = null;
      pump();
    });
}

/** Queue a render (or join the identical one already queued/running). */
function renderQueued(
  key: string,
  html: string,
  opts: { width: number; height: number; css: string; targetWidth: number },
  priority: number,
): Promise<PreviewResult> {
  const cached = cache.get(key);
  if (cached) return Promise.resolve(cached);
  return new Promise((resolve, reject) => {
    if (runningJob && runningJob.key === key) {
      runningJob.waiters.push({ resolve, reject });
      return;
    }
    const existing = queued.get(key);
    if (existing) {
      existing.waiters.push({ resolve, reject });
      existing.priority = Math.max(existing.priority, priority);
      return;
    }
    queued.set(key, {
      key, html, width: opts.width, height: opts.height, css: opts.css,
      targetWidth: opts.targetWidth,
      priority, seq: seq++, waiters: [{ resolve, reject }],
    });
    pump();
  });
}

function hashOf(html: string, width: number, height: number, css: string, bucket: number): string {
  let h = 5381;
  const s = `${width}x${height}@${bucket}|${css}|${html}`;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return `${h >>> 0}`;
}

export interface PreviewState {
  bitmap: ImageBitmap | null;
  url: string | null;
  loading: boolean;
  error: string | null;
}

export interface PreviewOptions {
  width: number;
  height: number;
  css: string;
  /** Higher renders sooner. Stage and present mode: 10. Thumbnails: 1. */
  priority?: number;
  /** When false, do not queue a render (off-screen thumbnail). */
  enabled?: boolean;
  /** Changes when the owning deck is replaced; drops the previous deck's
   *  image immediately instead of showing it while the new one renders. */
  sessionKey?: string;
  /** Intended on-screen width in device pixels; picks the render scale. */
  targetWidth?: number;
}

const EMPTY: PreviewState = { bitmap: null, url: null, loading: true, error: null };

export function usePreview(html: string, opts: PreviewOptions): PreviewState {
  const bucket = bucketOf(opts.targetWidth ?? opts.width);
  const key = hashOf(html, opts.width, opts.height, opts.css, bucket);
  const priority = opts.priority ?? 0;
  const enabled = opts.enabled ?? true;
  const [state, setState] = useState<PreviewState>(() => {
    const cached = cache.get(key);
    return cached
      ? { bitmap: "bitmap" in cached ? cached.bitmap : null, url: "url" in cached ? cached.url : null, loading: false, error: null }
      : EMPTY;
  });
  const generation = useRef(0);
  const session = useRef(opts.sessionKey);
  const shown = useRef<PreviewResult | null>(cache.get(key) ?? null);

  useEffect(() => {
    // A different deck owns this surface now: never show its predecessor's
    // slides while the new render is queued.
    if (session.current !== opts.sessionKey) {
      session.current = opts.sessionKey;
      shown.current = null;
      setState(EMPTY);
    }
    const cached = cache.get(key);
    if (cached) {
      shown.current = cached;
      setState({
        bitmap: "bitmap" in cached ? cached.bitmap : null,
        url: "url" in cached ? cached.url : null,
        loading: false, error: null,
      });
      return;
    }
    if (!enabled) {
      setState((s) => ({ ...s, loading: false, error: null }));
      return;
    }
    setState((s) => ({ ...s, loading: true, error: null }));
    const gen = ++generation.current;
    // Debounce only when something is already on screen (typing); a fresh
    // slide renders immediately so decks fill in as fast as the queue runs.
    const delay = shown.current ? 120 : 0;
    const timer = setTimeout(() => {
      renderQueued(key, html, {
        width: opts.width, height: opts.height, css: opts.css, targetWidth: bucket,
      }, priority)
        .then((result) => {
          if (generation.current !== gen) return;
          shown.current = result;
          setState({
            bitmap: "bitmap" in result ? result.bitmap : null,
            url: "url" in result ? result.url : null,
            loading: false, error: null,
          });
        })
        .catch((error: Error) => {
          if (generation.current !== gen) return;
          setState((s) => ({ ...s, loading: false, error: error.message }));
        });
    }, delay);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, opts.sessionKey]);

  return state;
}
