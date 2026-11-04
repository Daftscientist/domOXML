// Client for the engine worker (Pyodide + domOXML + Takumi, off the UI thread).
//
// The worker boots lazily on first import of this module. Every call waits for
// boot, so the UI can be fully interactive (typing, arranging slides) while
// the engine is still starting; previews simply resolve when it is ready.
import type {
  ConvertResult, EngineStatus, ReadDeckResult, SlideTransition,
} from "./types";

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void };

class EngineClient {
  private worker: Worker;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private status: EngineStatus = { phase: "starting" };
  private listeners = new Set<(s: EngineStatus) => void>();
  private readyPromise: Promise<void>;
  private readyResolve!: () => void;
  private readyReject!: (e: Error) => void;

  constructor() {
    this.readyPromise = new Promise((resolve, reject) => {
      this.readyResolve = resolve;
      this.readyReject = reject;
    });
    this.readyPromise.catch(() => undefined); // errors surface per-call too
    this.worker = new Worker(new URL("../worker/engine.worker.ts", import.meta.url), {
      type: "module",
    });
    // Resolve the app root to an absolute URL: the worker resolves relative
    // fetches against its own script URL (assets/), not the page, so the
    // bundle path must not be relative.
    const base = new URL(import.meta.env.BASE_URL || "./", window.location.href).href;
    const bootMessage = {
      type: "boot",
      pyBase: `${base}py/`,
      // A ?pyodide=<url> override exists so the engine can be pointed at a
      // mirrored runtime (offline development, testing); production uses
      // the version-pinned CDN build.
      pyodideIndexURL:
        new URLSearchParams(window.location.search).get("pyodide") ??
        "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/",
    };
    let bootSent = false;
    let heardFromWorker = false;
    const sendBoot = () => {
      if (bootSent) return;
      bootSent = true;
      this.worker.postMessage(bootMessage);
    };
    this.worker.onmessage = (event: MessageEvent) => {
      const msg = event.data;
      heardFromWorker = true;
      if (msg.type === "hello") {
        // The worker posts hello once its handler is registered; boot goes
        // out in reply. Posting boot at construction time can race module
        // evaluation and be lost, hanging the engine without a trace.
        sendBoot();
        return;
      }
      if (msg.type === "status") {
        this.status = { phase: msg.phase, detail: msg.detail };
        for (const fn of this.listeners) fn(this.status);
        if (msg.phase === "ready") this.readyResolve();
        if (msg.phase === "error") this.readyReject(new Error(msg.detail || "Engine failed to start"));
        return;
      }
      const pending = this.pending.get(msg.id);
      if (!pending) return;
      this.pending.delete(msg.id);
      if (msg.ok) pending.resolve(msg.result);
      else pending.reject(new Error(msg.error || "Engine error"));
    };
    // Fallbacks: if hello never arrives (worker failed to evaluate), still
    // try boot once, and never leave the UI claiming to start forever.
    // Once any message has arrived, the worker's own status reports govern.
    setTimeout(sendBoot, 4000);
    setTimeout(() => {
      if (!heardFromWorker) {
        this.status = { phase: "error", detail: "The engine did not start. Reload to try again." };
        for (const fn of this.listeners) fn(this.status);
        this.readyReject(new Error(this.status.detail));
      }
    }, 45000);
  }

  onStatus(fn: (s: EngineStatus) => void): () => void {
    this.listeners.add(fn);
    fn(this.status);
    return () => this.listeners.delete(fn);
  }

  get currentStatus(): EngineStatus {
    return this.status;
  }

  private async call<T>(type: string, payload: unknown, transfer: Transferable[] = []): Promise<T> {
    await this.readyPromise;
    const id = ++this.seq;
    const promise = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    });
    this.worker.postMessage({ type, id, payload }, transfer);
    return promise;
  }

  async preview(html: string, opts: { width: number; height: number; css?: string }): Promise<Uint8Array> {
    return this.call<Uint8Array>("preview", { ...opts, html });
  }

  async convert(
    fragments: string[],
    opts: { width: number; height: number; css?: string; transitions?: (SlideTransition | null)[] },
  ): Promise<ConvertResult> {
    const raw = await this.call<{ pptx_b64: string; coverage: ConvertResult["coverage"]; warnings: ConvertResult["warnings"] }>(
      "convert",
      { fragments, ...opts },
    );
    const bin = atob(raw.pptx_b64);
    const pptx = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) pptx[i] = bin.charCodeAt(i);
    return { pptx, coverage: raw.coverage, warnings: raw.warnings };
  }

  async readDeck(data: Uint8Array): Promise<ReadDeckResult> {
    const raw = await this.call<{
      width_px: number; height_px: number; css: string;
      slides: { html: string; transition: SlideTransition | null }[];
    }>("readDeck", data, [data.buffer as ArrayBuffer]);
    return {
      width: Math.round(raw.width_px),
      height: Math.round(raw.height_px),
      css: raw.css || "",
      slides: raw.slides,
    };
  }
}

export const engine = new EngineClient();
