// Private JSON-over-stdio bridge. Never write diagnostic output to stdout.
// Takumi's public paint API is currently provided as a WASM-backed JS package.
import { readFileSync } from "node:fs";

const reply = (value) => process.stdout.write(JSON.stringify(value) + "\n");
let stage = "input";
try {
  const request = JSON.parse(readFileSync(0, "utf8"));
  const { html, width, height } = request;
  if (typeof html !== "string" || !Number.isInteger(width) || !Number.isInteger(height) ||
      width <= 0 || height <= 0) {
    throw new TypeError("Expected HTML string and positive integer canvas dimensions");
  }

  // Prevent network image/font requests. Takumi does not execute page JavaScript.
  // Keep the resolver offline until a controlled asset loader is provided.
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (input, options) => {
    const url = typeof input === "string" ? input : input?.url;
    if (typeof url !== "string" || !url.startsWith("data:")) {
      throw new Error("Takumi external resource blocked: " + String(url));
    }
    return originalFetch(input, options);
  };

  stage = "setup";
  const [{ paint }, { render }] = await Promise.all([
    import("takumi-paint"), import("takumi-js")
  ]);
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
      box.x + box.width >= width - 0.01 &&
      box.y + box.height >= height - 0.01;
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
  stage = "raster";
  const png = await render(html, { width, height, format: "png" });
  reply({ ok: true, png: Buffer.from(png).toString("base64"), steps });
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  reply({ ok: false, stage, message });
  process.exitCode = 1;
}
