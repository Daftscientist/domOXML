// Preview worker: paints slide HTML with takumi-paint and renders the
// paint tree onto a canvas ourselves (see lib/treePainter), returning an
// ImageBitmap. No Pyodide and no PNG round trip: previews stay fast and
// resolution independent, and they work before the Python engine boots.
//
// Slides the canvas painter cannot reproduce faithfully report
// `unsupported`, and the client falls back to the engine's takumi-js
// raster for those slides.

import { paint } from "takumi-paint";
import { composePage } from "../lib/composePage";
import { paintTree, setSvgDecoder, UnsupportedPaint } from "../lib/treePainter";

interface RenderRequest {
  type: "render";
  id: number;
  html: string;
  width: number;
  height: number;
  css?: string;
  targetWidth: number;
}

const scope = self as unknown as {
  postMessage: (message: unknown, transfer?: Transferable[]) => void;
  onmessage: ((event: MessageEvent) => void) | null;
};

// Same resource policy as the export bridge: while Takumi paints, only
// data: URLs may load, so the preview cannot diverge from export by
// fetching live external assets.
const originalFetch = globalThis.fetch;

// SVG sources cannot be decoded in a worker; the client rasterises them
// on the main thread via an <img> and transfers the bitmap back.
const svgPending = new Map<number, { resolve: (b: ImageBitmap) => void; reject: (e: Error) => void }>();
let svgSeq = 0;
setSvgDecoder((src, width, height) => {
  const id = ++svgSeq;
  return new Promise<ImageBitmap>((resolve, reject) => {
    svgPending.set(id, { resolve, reject });
    scope.postMessage({ type: "svg-request", id, src, width, height });
    setTimeout(() => {
      if (svgPending.delete(id)) reject(new Error("SVG decode timed out"));
    }, 15000);
  });
});

async function render(request: RenderRequest) {
  const page = composePage(request.html, {
    width: request.width,
    height: request.height,
    css: request.css,
  });
  globalThis.fetch = ((input: RequestInfo | URL, options?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (typeof url !== "string" || !url.startsWith("data:")) {
      throw new Error("Takumi external resource blocked: " + String(url));
    }
    return originalFetch(input, options);
  }) as typeof fetch;
  let tree;
  try {
    tree = await paint(page, { width: request.width, height: request.height });
  } finally {
    globalThis.fetch = originalFetch;
  }
  const scale = Math.min(2.5, Math.max(0.1, request.targetWidth / request.width));
  const { bitmap, stats } = await paintTree(tree as unknown as Record<string, unknown>, { scale });
  return { bitmap, stats };
}

scope.onmessage = (event: MessageEvent) => {
  const msg = event.data as { type?: string };
  if (msg?.type === "svg-result" || msg?.type === "svg-error") {
    const result = event.data as { id: number; bitmap?: ImageBitmap; message?: string };
    const pending = svgPending.get(result.id);
    if (pending) {
      svgPending.delete(result.id);
      if (result.bitmap) pending.resolve(result.bitmap);
      else pending.reject(new Error(result.message || "SVG decode failed"));
    }
    return;
  }
  const request = event.data as RenderRequest;
  if (!request || request.type !== "render") return;
  render(request)
    .then(({ bitmap, stats }) => {
      scope.postMessage(
        { type: "rendered", id: request.id, bitmap, stats },
        [bitmap as unknown as Transferable],
      );
    })
    .catch((error: Error) => {
      scope.postMessage({
        type: "error",
        id: request.id,
        message: error?.message ?? String(error),
        unsupported: error instanceof UnsupportedPaint,
      });
    });
};

// Signal readiness like the engine worker does, so the client's first
// request cannot race module evaluation.
scope.postMessage({ type: "hello" });
