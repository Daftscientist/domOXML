// Client for the preview worker (takumi-paint + our canvas tree painter).
// Separate from the Python engine worker: previews never wait for Pyodide
// to boot and never block behind exports or deck reads.

export class PreviewUnsupported extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = "PreviewUnsupported";
  }
}

export interface PreviewStats {
  repainted: number;
  reused: number;
  ms: number;
}

type Pending = {
  resolve: (v: { bitmap: ImageBitmap; stats: PreviewStats }) => void;
  reject: (e: Error) => void;
};

class PreviewClient {
  private worker: Worker;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private readyPromise: Promise<void>;
  private readyResolve!: () => void;
  private failed = false;

  constructor() {
    this.readyPromise = new Promise((resolve) => {
      this.readyResolve = resolve;
    });
    this.worker = new Worker(new URL("../worker/preview.worker.ts", import.meta.url), {
      type: "module",
    });
    let greeted = false;
    this.worker.onmessage = (event: MessageEvent) => {
      const msg = event.data;
      if (msg.type === "svg-request") {
        void this.decodeSvg(msg);
        return;
      }
      if (msg.type === "hello") {
        greeted = true;
        this.readyResolve();
        return;
      }
      const pending = this.pending.get(msg.id);
      if (!pending) return;
      this.pending.delete(msg.id);
      if (msg.type === "rendered") {
        pending.resolve({ bitmap: msg.bitmap as ImageBitmap, stats: msg.stats as PreviewStats });
      } else if (msg.unsupported) {
        pending.reject(new PreviewUnsupported(msg.message || "unsupported paint"));
      } else {
        pending.reject(new Error(msg.message || "Preview failed"));
      }
    };
    this.worker.onerror = () => {
      this.failed = true;
      for (const pending of this.pending.values()) {
        pending.reject(new PreviewUnsupported("preview worker failed"));
      }
      this.pending.clear();
    };
    // If the worker cannot even evaluate, treat every render as
    // unsupported so callers fall back to the engine raster.
    setTimeout(() => {
      if (!greeted) {
        this.failed = true;
        this.readyResolve();
      }
    }, 10000);
  }

  /** Rasterise an SVG for the preview worker, which cannot decode them. */
  private async decodeSvg(msg: { id: number; src: string; width: number; height: number }) {
    try {
      if (!msg.src.startsWith("data:image/svg")) throw new Error("not an SVG data URI");
      const img = new Image();
      img.src = msg.src;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(msg.width));
      canvas.height = Math.max(1, Math.round(msg.height));
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("no 2d context");
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const bitmap = await createImageBitmap(canvas);
      this.worker.postMessage({ type: "svg-result", id: msg.id, bitmap }, [bitmap]);
    } catch (error) {
      this.worker.postMessage({
        type: "svg-error",
        id: msg.id,
        message: (error as Error).message || "SVG decode failed",
      });
    }
  }

  async render(
    html: string,
    opts: { width: number; height: number; css?: string; targetWidth: number },
  ): Promise<{ bitmap: ImageBitmap; stats: PreviewStats }> {
    if (this.failed) throw new PreviewUnsupported("preview worker unavailable");
    await this.readyPromise;
    if (this.failed) throw new PreviewUnsupported("preview worker unavailable");
    const id = ++this.seq;
    const promise = new Promise<{ bitmap: ImageBitmap; stats: PreviewStats }>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    // A wedged worker (WASM abort, OOM on a huge deck) must not block the
    // preview queue forever: time the request out and let the caller fall
    // back to the engine raster.
    setTimeout(() => {
      const pending = this.pending.get(id);
      if (pending) {
        this.pending.delete(id);
        pending.reject(new PreviewUnsupported("preview timed out"));
      }
    }, 30000);
    this.worker.postMessage({ type: "render", id, html, ...opts });
    return promise;
  }
}

export const previewClient = new PreviewClient();
