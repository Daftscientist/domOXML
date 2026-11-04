// Takumi bridge for the browser / Pyodide host.
//
// Same contract as domoxml/core/render/takumi/worker.mjs (the desktop Node
// bridge), but as a function instead of stdio: takes a JSON string
// {html, width, height} and resolves to a JSON string
// {ok, png (base64), steps} or {ok: false, stage, message}.
//
// takumi-paint produces the paint tree (bounds, text runs, fills) that
// domOXML converts into editable native objects; takumi-js renders the
// authoritative PNG used for previews and for the fail-closed full-slide
// raster when a paint operation has no OOXML mapping yet.
import { paint } from "takumi-paint";
import { render } from "takumi-js";

function toBase64(bytes) {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export async function takumiBridge(requestJson) {
  let stage = "input";
  try {
    const request = JSON.parse(requestJson);
    const { html, width, height } = request;
    if (typeof html !== "string" || !Number.isInteger(width) || !Number.isInteger(height) ||
        width <= 0 || height <= 0) {
      throw new TypeError("Expected HTML string and positive integer canvas dimensions");
    }

    // Prevent network image/font requests. Takumi does not execute page
    // JavaScript. Only data: URLs may load (domOXML inlines assets as data
    // URIs on the read path), everything else is blocked like the desktop
    // bridge does.
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (input, options) => {
      const url = typeof input === "string" ? input : input?.url;
      if (typeof url !== "string" || !url.startsWith("data:")) {
        throw new Error("Takumi external resource blocked: " + String(url));
      }
      return originalFetch(input, options);
    };

    try {
      stage = "paint";
      const tree = await paint(html, { width, height });
      const steps = [];
      const isTranslation = (matrix) =>
        Array.isArray(matrix) && matrix.length === 6 &&
        matrix.every(Number.isFinite) &&
        Math.abs(matrix[0] - 1) < 0.000001 &&
        Math.abs(matrix[1]) < 0.000001 &&
        Math.abs(matrix[2]) < 0.000001 &&
        Math.abs(matrix[3] - 1) < 0.000001;
      const colorOf = (paintValue) => {
        if (paintValue?.type !== "color") return null;
        const rgba = paintValue.color;
        return Array.isArray(rgba) && rgba.length === 4 &&
          rgba.every((n) => Number.isInteger(n) && n >= 0 && n <= 255) ? rgba : null;
      };
      const fullCanvasClips = new Set();
      const isCanvasClip = (step) => {
        if (step.clip?.type !== "rect") return false;
        const box = step.node.bounds;
        return box.x <= 0.01 && box.y <= 0.01 &&
          box.x + box.width >= width - 0.01 && box.y + box.height >= height - 0.01;
      };
      for (const step of tree.steps) {
        if (step.type === "begin-clip" && isCanvasClip(step)) {
          fullCanvasClips.add(step.node);
          continue;
        }
        if (step.type === "end-clip" && fullCanvasClips.has(step.node)) {
          fullCanvasClips.delete(step.node);
          continue;
        }
        if (step.type !== "draw") {
          steps.push({
            type: "unsupported",
            reason: step.type + " compositing on " +
              (step.node?.element?.tagName || "unnamed") + " " +
              JSON.stringify(step.node?.bounds || {})
          });
          continue;
        }
        const node = step.node;
        if (!isTranslation(node.transform)) {
          steps.push({ type: "unsupported", reason: "non-translation paint transform" });
          continue;
        }
        for (const drawable of step.drawables) {
          if (drawable.type === "fill" && drawable.role === "background" &&
              drawable.shape?.type === "rect" && colorOf(drawable.paint)) {
            steps.push({ type: "fill", bounds: node.bounds, color: colorOf(drawable.paint) });
          } else if (drawable.type === "image" && drawable.image?.src) {
            // An <img> (or replaced element) at its painted box. The source
            // is resolved to bytes after the loop; Python maps it to a
            // native PowerPoint picture instead of rasterising the slide.
            const rect = drawable.rect;
            steps.push({
              type: "image",
              bounds: {
                x: node.bounds.x + rect.x, y: node.bounds.y + rect.y,
                width: rect.width, height: rect.height
              },
              src: drawable.image.src
            });
          } else if (drawable.type === "fill" && drawable.role === "background" &&
                     drawable.paint?.type === "image" && drawable.paint.image?.src &&
                     drawable.shape?.type === "rect") {
            // A CSS background image on a rectangular box: same mapping,
            // at the box's bounds.
            steps.push({ type: "image", bounds: node.bounds, src: drawable.paint.image.src });
          } else if (drawable.type === "glyphs" && drawable.role === "text" &&
                     node.type === "text" && colorOf(drawable.paint) && drawable.run) {
            const run = drawable.run;
            steps.push({
              type: "text",
              text: run.text,
              x: node.bounds.x + run.x,
              y: node.bounds.y + run.y - run.ascent,
              width: run.width,
              height: run.ascent + run.descent,
              fontSize: run.fontSize,
              fontFamily: run.font.family || "Geist",
              fontWeight: run.font.weight,
              fontStyle: run.font.style,
              color: colorOf(drawable.paint)
            });
          } else {
            steps.push({
              type: "unsupported",
              reason: (drawable.role || "paint") + ": " + drawable.type
            });
          }
        }
      }
      // Resolve image steps to bytes so Python can embed them as native
      // pictures. data: URIs carry the bytes already; http(s) sources are
      // fetched with the unpatched fetch. Anything unresolvable degrades
      // to an unsupported step, which fails the slide closed to a raster
      // exactly like any other unmapped paint.
      const IMAGE_EXTS = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/bmp": "bmp", "image/x-ms-bmp": "bmp" };
      for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        if (step.type !== "image") continue;
        const fail = (reason) => { steps[i] = { type: "unsupported", reason }; };
        const src = step.src;
        delete step.src;
        if (src.startsWith("data:")) {
          const match = /^data:([^;,]+);base64,([A-Za-z0-9+/=\s]+)$/.exec(src);
          const ext = match ? IMAGE_EXTS[(match[1] || "").toLowerCase()] : undefined;
          if (!match || !ext) { fail("image: unsupported data URI"); continue; }
          step.ext = ext;
          step.data = match[2].replace(/\s+/g, "");
        } else if (/^https?:\/\//i.test(src)) {
          try {
            const response = await originalFetch(src);
            if (!response.ok) throw new Error("HTTP " + response.status);
            const bytes = new Uint8Array(await response.arrayBuffer());
            if (bytes.length === 0 || bytes.length > 16 * 1024 * 1024) {
              throw new Error("image size out of range");
            }
            const ext = IMAGE_EXTS[(response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase()];
            if (!ext) throw new Error("unsupported content type");
            step.ext = ext;
            step.data = toBase64(bytes);
          } catch {
            fail("image: could not fetch " + (() => { try { return new URL(src).host; } catch { return "external image"; } })());
          }
        } else {
          fail("image: unsupported source");
        }
      }
      stage = "raster";
      const png = await render(html, { width, height, format: "png" });
      return JSON.stringify({ ok: true, png: toBase64(png), steps });
    } finally {
      globalThis.fetch = originalFetch;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return JSON.stringify({ ok: false, stage, message });
  }
}

// Install as the global the Python side looks up (domoxml.core.render.
// takumi_backend._js_bridge reads js.domoxmlTakumiBridge under Pyodide).
export function installTakumiBridge(target = globalThis) {
  target.domoxmlTakumiBridge = takumiBridge;
  return takumiBridge;
}
