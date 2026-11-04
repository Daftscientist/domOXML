import { useEffect, useRef, useState } from "react";
import { engine } from "./engine";

// Preview renders go through a single-threaded engine, so they are queued
// and run one at a time in priority order: the slide on stage first, then
// everything else in request order. Renders are cached by content hash and
// shared between every surface asking for the same content (stage + rail
// thumbnail), so opening a large deck fills in progressively, visible
// slides first, instead of flooding the engine with every slide at once.
const cache = new Map<string, string>();
const MAX_CACHE = 80;

interface Job {
  key: string;
  html: string;
  width: number;
  height: number;
  css: string;
  priority: number;
  seq: number;
  waiters: { resolve: (url: string) => void; reject: (error: Error) => void }[];
}

const queued = new Map<string, Job>();
let runningJob: Job | null = null;
let seq = 0;

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
  engine
    .preview(job.html, { width: job.width, height: job.height, css: job.css })
    .then((png) => {
      const url = URL.createObjectURL(new Blob([png as BlobPart], { type: "image/png" }));
      if (cache.size >= MAX_CACHE) {
        const oldest = cache.keys().next().value;
        if (oldest) {
          URL.revokeObjectURL(cache.get(oldest)!);
          cache.delete(oldest);
        }
      }
      cache.set(job.key, url);
      for (const w of job.waiters) w.resolve(url);
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
  opts: { width: number; height: number; css: string },
  priority: number,
): Promise<string> {
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
      priority, seq: seq++, waiters: [{ resolve, reject }],
    });
    pump();
  });
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
}

export function usePreview(html: string, opts: PreviewOptions): PreviewState {
  const key = hashOf(html, opts.width, opts.height, opts.css);
  const priority = opts.priority ?? 0;
  const enabled = opts.enabled ?? true;
  const [state, setState] = useState<PreviewState>(() => ({
    url: cache.get(key) ?? null,
    loading: !cache.has(key),
    error: null,
  }));
  const generation = useRef(0);
  const session = useRef(opts.sessionKey);
  const shownUrl = useRef<string | null>(cache.get(key) ?? null);

  useEffect(() => {
    // A different deck owns this surface now: never show its predecessor's
    // slides while the new render is queued.
    if (session.current !== opts.sessionKey) {
      session.current = opts.sessionKey;
      shownUrl.current = null;
      setState({ url: null, loading: true, error: null });
    }
    const cached = cache.get(key);
    if (cached) {
      shownUrl.current = cached;
      setState({ url: cached, loading: false, error: null });
      return;
    }
    if (!enabled) {
      setState((s) => ({ url: s.url, loading: false, error: null }));
      return;
    }
    setState((s) => ({ url: shownUrl.current, loading: true, error: null }));
    const gen = ++generation.current;
    // Debounce only when something is already on screen (typing); a fresh
    // slide renders immediately so decks fill in as fast as the queue runs.
    const delay = shownUrl.current ? 450 : 0;
    const timer = setTimeout(() => {
      renderQueued(key, html, { width: opts.width, height: opts.height, css: opts.css }, priority)
        .then((url) => {
          if (generation.current !== gen) return;
          shownUrl.current = url;
          setState({ url, loading: false, error: null });
        })
        .catch((error: Error) => {
          if (generation.current !== gen) return;
          setState((s) => ({ url: s.url, loading: false, error: error.message }));
        });
    }, delay);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, opts.sessionKey]);

  return state;
}
