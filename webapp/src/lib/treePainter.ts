// Paints a takumi-paint PaintTree onto an OffscreenCanvas with Canvas 2D,
// instead of taking takumi-js's PNG. Text is drawn from Takumi's own glyph
// outlines, so shapes are exact at any scale; fills, strokes, gradients,
// clips and images map onto the canvas equivalents.
//
// Repaints are deduped at subtree level: the tree's steps are grouped into
// segments by their root-level node, each segment is hashed from its paint
// inputs, and unchanged segments are reused as cached layers. Editing one
// element repaints only the segments that contain it; the rest are
// composited from cache.
//
// Anything the painter cannot reproduce faithfully (masks, filters,
// patterns, bitmap glyphs such as colour emoji) throws UnsupportedPaint,
// and the caller falls back to the authoritative takumi-js raster for that
// slide rather than showing an approximation.
//
// Coordinate discipline: every layer canvas lives in "segment device
// space" (the segment's rectangle at the render scale). A layer context's
// base transform maps slide coordinates into that space, so layers can be
// composited onto each other with an identity transform at (0, 0).

export class UnsupportedPaint extends Error {
  constructor(reason: string) {
    super(`unsupported paint: ${reason}`);
    this.name = "UnsupportedPaint";
  }
}

type AnyRecord = Record<string, unknown>;
type Ctx = OffscreenCanvasRenderingContext2D;

interface Layer {
  canvas: OffscreenCanvas;
  x: number;
  y: number;
}

const layerCache = new Map<string, Layer>();
const LAYER_CACHE_MAX = 56;
const imagePromises = new Map<string, Promise<ImageBitmap>>();
const decodedImages = new Map<string, ImageBitmap>();
const glyphPathCache = new Map<string, Path2D>();
const GLYPH_CACHE_MAX = 400;

function rgba(color: readonly number[]): string {
  const [r, g, b, a] = color;
  return `rgba(${r},${g},${b},${(a / 255).toFixed(4)})`;
}

/** cyrb64: a fast 64-bit string hash, good enough for layer identity. */
function hashString(input: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return `${(h2 >>> 0).toString(16)}${(h1 >>> 0).toString(16)}:${input.length}`;
}

function shapePath(shape: AnyRecord): Path2D {
  if (shape.type === "rect") {
    const r = shape.rect as AnyRecord;
    const path = new Path2D();
    path.rect(r.x as number, r.y as number, r.width as number, r.height as number);
    return path;
  }
  if (shape.type === "rounded-rect") {
    const r = shape.rect as AnyRecord;
    const radii = shape.radii as AnyRecord;
    const corner = (p: AnyRecord) => ({ x: p.x as number, y: p.y as number });
    const path = new Path2D();
    const x = r.x as number, y = r.y as number, w = r.width as number, h = r.height as number;
    const tl = corner(radii.topLeft as AnyRecord), tr = corner(radii.topRight as AnyRecord);
    const br = corner(radii.bottomRight as AnyRecord), bl = corner(radii.bottomLeft as AnyRecord);
    path.moveTo(x + tl.x, y);
    path.lineTo(x + w - tr.x, y);
    path.ellipse(x + w - tr.x, y + tr.y, tr.x, tr.y, 0, -Math.PI / 2, 0);
    path.lineTo(x + w, y + h - br.y);
    path.ellipse(x + w - br.x, y + h - br.y, br.x, br.y, 0, 0, Math.PI / 2);
    path.lineTo(x + bl.x, y + h);
    path.ellipse(x + bl.x, y + h - bl.y, bl.x, bl.y, 0, Math.PI / 2, Math.PI);
    path.lineTo(x, y + tl.y);
    path.ellipse(x + tl.x, y + tl.y, tl.x, tl.y, 0, Math.PI, Math.PI * 1.5);
    path.closePath();
    return path;
  }
  if (shape.type === "path") {
    return new Path2D(shape.d as string);
  }
  throw new UnsupportedPaint(`shape ${String(shape.type)}`);
}

function shapeBounds(shape: AnyRecord): AnyRecord {
  if (shape.type === "rect" || shape.type === "rounded-rect") return shape.rect as AnyRecord;
  return { x: 0, y: 0, width: 0, height: 0 };
}

function gradientStyle(ctx: Ctx, paint: AnyRecord): CanvasGradient {
  const stops = paint.stops as AnyRecord[];
  const addStops = (gradient: CanvasGradient) => {
    for (const stop of stops) {
      gradient.addColorStop(
        Math.min(1, Math.max(0, stop.offset as number)),
        rgba(stop.color as number[]),
      );
    }
  };
  if (paint.type === "linear-gradient") {
    const start = paint.start as AnyRecord, end = paint.end as AnyRecord;
    const gradient = ctx.createLinearGradient(
      start.x as number, start.y as number, end.x as number, end.y as number,
    );
    addStops(gradient);
    return gradient;
  }
  if (paint.type === "conic-gradient") {
    if (typeof ctx.createConicGradient !== "function") {
      throw new UnsupportedPaint("conic gradient");
    }
    const center = paint.center as AnyRecord;
    const gradient = ctx.createConicGradient(
      paint.startAngle as number, center.x as number, center.y as number,
    );
    addStops(gradient);
    return gradient;
  }
  if (paint.type === "radial-gradient") {
    const center = paint.center as AnyRecord;
    const radiusX = paint.radiusX as number;
    const gradient = ctx.createRadialGradient(
      center.x as number, center.y as number, (paint.start as number) * radiusX,
      center.x as number, center.y as number, radiusX,
    );
    addStops(gradient);
    return gradient;
  }
  throw new UnsupportedPaint(`gradient ${String(paint.type)}`);
}

function isEllipticalRadial(paint: AnyRecord): boolean {
  return paint.type === "radial-gradient" && (paint.radiusY as number) !== (paint.radiusX as number);
}

function fillWithPaint(ctx: Ctx, path: Path2D, paint: AnyRecord, bounds: AnyRecord, fillRule?: string) {
  if (paint.type === "color") {
    ctx.fillStyle = rgba(paint.color as number[]);
    ctx.fill(path, fillRule as CanvasFillRule);
    return;
  }
  if (paint.type === "image") {
    // Background image: clip to the shape and stretch the decoded bitmap
    // over the shape's box.
    const bitmap = decodedImages.get((paint.image as AnyRecord).src as string);
    if (!bitmap) throw new UnsupportedPaint("background image not decoded");
    ctx.save();
    ctx.clip(path, fillRule as CanvasFillRule);
    ctx.imageSmoothingEnabled = paint.sampling !== "pixelated";
    ctx.drawImage(bitmap, bounds.x as number, bounds.y as number, bounds.width as number, bounds.height as number);
    ctx.restore();
    return;
  }
  if (paint.type === "pattern") {
    // A repeated background tile: the tree enumerates every tile origin,
    // so painting is a clipped stamp of the tile (image or gradient).
    const area = paint.area as AnyRecord;
    const tile = paint.tile as AnyRecord;
    const tw = paint.tileWidth as number, th = paint.tileHeight as number;
    ctx.save();
    ctx.clip(path, fillRule as CanvasFillRule);
    ctx.beginPath();
    ctx.rect(area.x as number, area.y as number, area.width as number, area.height as number);
    ctx.clip();
    for (const x of paint.x as number[]) {
      for (const y of paint.y as number[]) {
        ctx.save();
        ctx.translate(x, y);
        if (tile.type === "image") {
          const bitmap = decodedImages.get((tile.image as AnyRecord).src as string);
          if (!bitmap) throw new UnsupportedPaint("pattern image not decoded");
          ctx.imageSmoothingEnabled = tile.sampling !== "pixelated";
          ctx.drawImage(bitmap, 0, 0, tw, th);
        } else {
          ctx.fillStyle = gradientStyle(ctx, tile);
          ctx.fillRect(0, 0, tw, th);
        }
        ctx.restore();
      }
    }
    ctx.restore();
    return;
  }
  if (isEllipticalRadial(paint)) {
    const center = paint.center as AnyRecord;
    const scaleY = (paint.radiusY as number) / (paint.radiusX as number);
    ctx.save();
    ctx.translate(center.x as number, center.y as number);
    ctx.scale(1, scaleY);
    ctx.translate(-(center.x as number), -(center.y as number));
    ctx.fillStyle = gradientStyle(ctx, paint);
    ctx.fill(path, fillRule as CanvasFillRule);
    ctx.restore();
    return;
  }
  ctx.fillStyle = gradientStyle(ctx, paint);
  ctx.fill(path, fillRule as CanvasFillRule);
}

function strokeWithPaint(ctx: Ctx, path: Path2D, paint: AnyRecord) {
  if (paint.type === "color") {
    ctx.strokeStyle = rgba(paint.color as number[]);
  } else if (paint.type === "image" || paint.type === "pattern") {
    throw new UnsupportedPaint("stroke image/pattern paint");
  } else {
    ctx.strokeStyle = gradientStyle(ctx, paint);
  }
  ctx.stroke(path);
}

/** SVGs cannot be decoded by createImageBitmap in a worker. The host may
 *  register a decoder that rasterises them elsewhere (the preview client
 *  uses an <img> on the main thread) and hands back a bitmap. */
let svgDecoder: ((src: string, width: number, height: number) => Promise<ImageBitmap>) | null = null;
export function setSvgDecoder(fn: typeof svgDecoder) {
  svgDecoder = fn;
}

async function decodeImage(src: string, intrinsic?: { width: number; height: number }): Promise<void> {
  let pending = imagePromises.get(src);
  if (!pending) {
    pending = (async () => {
      try {
        const response = await fetch(src);
        if (!response.ok) throw new Error(`image fetch ${response.status}`);
        const blob = await response.blob();
        try {
          return await createImageBitmap(blob);
        } catch {
          if (svgDecoder && (blob.type.includes("svg") || src.startsWith("data:image/svg"))) {
            return await svgDecoder(src, intrinsic?.width ?? 512, intrinsic?.height ?? 512);
          }
          throw new Error("not decodable in worker");
        }
      } catch (error) {
        throw new UnsupportedPaint(`image decode failed: ${(error as Error).message}`);
      }
    })();
    imagePromises.set(src, pending);
  }
  decodedImages.set(src, await pending);
}



function collectImageSources(value: unknown, into: Map<string, { width: number; height: number }>) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value) collectImageSources(item, into);
    return;
  }
  const record = value as AnyRecord;
  if (record.type === "image" && record.image && typeof record.image === "object") {
    const image = record.image as AnyRecord;
    if (typeof image.src === "string" && !into.has(image.src)) {
      into.set(image.src, { width: (image.width as number) || 512, height: (image.height as number) || 512 });
    }
  }
  if (record.paint) collectImageSources(record.paint, into);
  for (const key of ["drawables", "mask", "content"]) {
    if (key in record) collectImageSources(record[key], into);
  }
  if (record.tile) collectImageSources(record.tile, into);
}

interface PaintEnv {
  scale: number;
  originX: number;
  originY: number;
  segW: number;
  segH: number;
  /** Transform of the draw step currently being painted, if any. */
  currentMatrix?: number[];
  /** Active clip stack (path + node matrix), for group layer inheritance. */
  clips: { path: Path2D; matrix: number[]; fillRule?: string }[];
}

/** A fresh layer in segment device space, base-transformed to slide coords. */
function makeLayer(env: PaintEnv): { canvas: OffscreenCanvas; ctx: Ctx } {
  const canvas = new OffscreenCanvas(
    Math.max(1, Math.ceil(env.segW * env.scale)),
    Math.max(1, Math.ceil(env.segH * env.scale)),
  );
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.translate(-env.originX * env.scale, -env.originY * env.scale);
  ctx.scale(env.scale, env.scale);
  return { canvas, ctx };
}

/** Composite a segment-space layer onto `ctx` at identity. */
function blitLayer(ctx: Ctx, canvas: OffscreenCanvas) {
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(canvas, 0, 0);
  ctx.restore();
}

function applyMatrix(ctx: Ctx, matrix: readonly number[]) {
  ctx.transform(matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5]);
}

function paintDrawables(ctx: Ctx, drawables: readonly AnyRecord[], node: AnyRecord, env: PaintEnv) {
  for (const drawable of drawables) {
    if (drawable.blendMode && drawable.blendMode !== "normal") {
      ctx.save();
      ctx.globalCompositeOperation = drawable.blendMode as GlobalCompositeOperation;
      paintDrawable(ctx, drawable, node, env);
      ctx.restore();
    } else {
      paintDrawable(ctx, drawable, node, env);
    }
  }
}

function paintDrawable(ctx: Ctx, drawable: AnyRecord, node: AnyRecord, env: PaintEnv) {
  const clips = drawable.clips as AnyRecord[] | undefined;
  if (clips && clips.length > 0) {
    ctx.save();
    for (const clip of clips) {
      ctx.clip(shapePath(clip), (clip.fillRule as CanvasFillRule) || "nonzero");
    }
  }
  try {
    switch (drawable.type) {
      case "fill": {
        const shape = drawable.shape as AnyRecord;
        fillWithPaint(ctx, shapePath(shape), drawable.paint as AnyRecord, shapeBounds(shape), shape.fillRule as string);
        break;
      }
      case "stroke": {
        const stroke = drawable.stroke as AnyRecord;
        ctx.save();
        ctx.lineWidth = stroke.width as number;
        ctx.setLineDash((stroke.dash as number[]) ?? []);
        ctx.lineCap = (stroke.cap as CanvasLineCap) ?? "butt";
        ctx.lineJoin = (stroke.join as CanvasLineJoin) ?? "miter";
        strokeWithPaint(ctx, shapePath(drawable.shape as AnyRecord), drawable.paint as AnyRecord);
        ctx.restore();
        break;
      }
      case "glyphs":
        paintGlyphs(ctx, drawable);
        break;
      case "image": {
        const src = (drawable.image as AnyRecord).src as string;
        const bitmap = decodedImages.get(src);
        if (!bitmap) throw new UnsupportedPaint("image not decoded");
        const rect = drawable.rect as AnyRecord;
        ctx.save();
        if (drawable.clip) {
          const clip = drawable.clip as AnyRecord;
          ctx.clip(shapePath(clip), (clip.fillRule as CanvasFillRule) || "nonzero");
        }
        ctx.imageSmoothingEnabled = drawable.sampling !== "pixelated";
        ctx.drawImage(bitmap, rect.x as number, rect.y as number, rect.width as number, rect.height as number);
        ctx.restore();
        break;
      }
      case "shadow":
        paintShadow(ctx, drawable, env);
        break;
      case "group": {
        const layer = makeLayer(env);
        if (env.currentMatrix) applyMatrix(layer.ctx, env.currentMatrix);
        paintDrawables(layer.ctx, drawable.drawables as AnyRecord[], node, env);
        ctx.save();
        ctx.globalAlpha = (drawable.opacity as number) ?? 1;
        blitLayer(ctx, layer.canvas);
        ctx.restore();
        break;
      }
      case "masked":
        throw new UnsupportedPaint("masked drawable");
      default:
        throw new UnsupportedPaint(`drawable ${String(drawable.type)}`);
    }
  } finally {
    if (clips && clips.length > 0) ctx.restore();
  }
}

function glyphPath(run: AnyRecord): Path2D {
  const font = run.font as AnyRecord;
  const glyphs = run.glyphs as AnyRecord[];
  const key = hashString(
    `${String(font.family)}|${String(font.weight)}|${String(font.style)}|${String(run.fontSize)}|` +
    glyphs.map((g) => `${g.id as number}@${(g.x as number).toFixed(2)},${(g.y as number).toFixed(2)}`).join(";"),
  );
  const cached = glyphPathCache.get(key);
  if (cached) return cached;
  const outlines = (run.outlines as () => (string | null)[])();
  if (outlines.some((o) => o === null)) {
    throw new UnsupportedPaint("bitmap glyph (emoji or colour font)");
  }
  const path = new Path2D(outlines.filter((o): o is string => typeof o === "string" && o.length > 0).join(""));
  if (glyphPathCache.size >= GLYPH_CACHE_MAX) glyphPathCache.clear();
  glyphPathCache.set(key, path);
  return path;
}

function paintGlyphs(ctx: Ctx, drawable: AnyRecord) {
  const run = drawable.run as AnyRecord;
  const path = glyphPath(run);
  const runBounds = {
    x: run.x as number,
    y: (run.y as number) - (run.ascent as number),
    width: run.width as number,
    height: (run.ascent as number) + (run.descent as number),
  };
  ctx.save();
  ctx.translate(run.x as number, run.y as number);
  if (run.transform) applyMatrix(ctx, run.transform as number[]);
  const blur = (drawable.blur as number) ?? 0;
  if (drawable.stroke) {
    const stroke = drawable.stroke as AnyRecord;
    ctx.lineWidth = stroke.width as number;
    strokeWithPaint(ctx, path, drawable.paint as AnyRecord);
  } else if (blur > 0) {
    const offset = drawable.offset as AnyRecord | undefined;
    ctx.save();
    ctx.translate((offset?.x as number) ?? 0, (offset?.y as number) ?? 0);
    if (typeof ctx.filter === "string") ctx.filter = `blur(${blur}px)`;
    fillWithPaint(ctx, path, drawable.paint as AnyRecord, runBounds);
    ctx.restore();
  } else {
    fillWithPaint(ctx, path, drawable.paint as AnyRecord, runBounds);
  }
  ctx.restore();
}

function paintShadow(ctx: Ctx, drawable: AnyRecord, env: PaintEnv) {
  if (typeof ctx.filter !== "string") throw new UnsupportedPaint("shadow (no canvas filter)");
  const layer = makeLayer(env);
  const lctx = layer.ctx;
  if (env.currentMatrix) applyMatrix(lctx, env.currentMatrix);
  const offset = drawable.offset as AnyRecord;
  lctx.save();
  lctx.translate(offset.x as number, offset.y as number);
  lctx.filter = `blur(${drawable.blur as number}px)`;
  const path = shapePath(drawable.shape as AnyRecord);
  if (drawable.stroke) {
    const stroke = drawable.stroke as AnyRecord;
    lctx.lineWidth = stroke.width as number;
    lctx.strokeStyle = rgba(drawable.color as number[]);
    lctx.stroke(path);
  } else {
    lctx.fillStyle = rgba(drawable.color as number[]);
    lctx.fill(path);
  }
  lctx.restore();
  lctx.filter = "none";
  // An outer shadow must not show through the element itself; an inner
  // shadow must not escape it. The `box` shape is that boundary.
  const boxPath = shapePath(drawable.box as AnyRecord);
  if (env.currentMatrix) {
    lctx.save();
    applyMatrix(lctx, env.currentMatrix);
  }
  lctx.globalCompositeOperation = drawable.visible === "outside" ? "destination-out" : "destination-in";
  lctx.fillStyle = "#000";
  lctx.fill(boxPath);
  lctx.globalCompositeOperation = "source-over";
  if (env.currentMatrix) lctx.restore();
  blitLayer(ctx, layer.canvas);
}

interface Segment {
  steps: AnyRecord[];
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  hash: string;
}

function rootAncestor(node: AnyRecord, root: AnyRecord): AnyRecord {
  let current = node;
  while (current !== root) {
    const parent = current.parent as AnyRecord | undefined;
    if (!parent || parent === root) break;
    current = parent;
  }
  return current;
}

function pruneForHash(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => pruneForHash(v));
  const record = value as AnyRecord;
  if (typeof record.outlines === "function" && Array.isArray(record.glyphs)) {
    const font = record.font as AnyRecord;
    return {
      run: [
        record.x, record.y, record.width, record.fontSize, record.letterSpacing,
        font?.family, font?.weight, font?.style, font?.faceIndex,
        (record.glyphs as AnyRecord[]).map((g) => [g.id, g.x, g.y]),
        record.transform ?? null,
      ],
    };
  }
  const out: AnyRecord = {};
  for (const [key, v] of Object.entries(record)) {
    if (key === "parent" || key === "children" || key === "element" || key === "id") continue;
    if (typeof v === "function") continue;
    out[key] = pruneForHash(v);
  }
  return out;
}

function segmentHash(steps: AnyRecord[]): string {
  const parts: unknown[] = steps.map((step) => ({
    type: step.type,
    node: step.node
      ? [(step.node as AnyRecord).transform, (step.node as AnyRecord).bounds]
      : null,
    clip: step.clip ? pruneForHash(step.clip) : null,
    effects: step.effects ? pruneForHash(step.effects) : null,
    drawables: step.drawables ? pruneForHash(step.drawables) : null,
  }));
  return hashString(JSON.stringify(parts));
}

function segmentPad(steps: AnyRecord[]): number {
  let pad = 2;
  const visit = (drawables: readonly AnyRecord[] | undefined) => {
    if (!drawables) return;
    for (const d of drawables) {
      if (d.type === "shadow") {
        const offset = d.offset as AnyRecord;
        pad = Math.max(pad, (d.blur as number) * 2 + Math.max(Math.abs(offset.x as number), Math.abs(offset.y as number)) + 4);
      }
      if (d.type === "stroke") pad = Math.max(pad, (d.stroke as AnyRecord).width as number);
      if (d.drawables) visit(d.drawables as AnyRecord[]);
    }
  };
  for (const step of steps) visit(step.drawables as AnyRecord[] | undefined);
  return pad;
}

export interface PaintStats {
  repainted: number;
  reused: number;
  ms: number;
}

export async function paintTree(
  tree: AnyRecord,
  opts: { scale: number },
): Promise<{ bitmap: ImageBitmap; stats: PaintStats }> {
  const started = performance.now();
  const scale = opts.scale;
  const width = tree.width as number;
  const height = tree.height as number;

  const sources = new Map<string, { width: number; height: number }>();
  for (const node of tree.nodes as AnyRecord[]) collectImageSources(node.drawables, sources);
  collectImageSources(tree.steps, sources);
  await Promise.all([...sources].map(([src, size]) => decodeImage(src, size)));

  const root = tree.root as AnyRecord;
  const steps = tree.steps as AnyRecord[];

  // Drop full-canvas clip pairs (they clip nothing) so segmentation by
  // root child is not collapsed into a single segment by a root clip.
  const filtered: AnyRecord[] = [];
  const clipStack: number[] = [];
  for (const step of steps) {
    if (step.type === "begin-clip") {
      const clip = step.clip as AnyRecord;
      const bounds = (step.node as AnyRecord).bounds as AnyRecord;
      const rect = clip?.rect as AnyRecord | undefined;
      const isCanvasClip =
        clip?.type === "rect" && rect &&
        Math.abs(rect.x as number) <= 0.01 && Math.abs(rect.y as number) <= 0.01 &&
        (rect.width as number) >= width - 0.01 && (rect.height as number) >= height - 0.01 &&
        bounds && (bounds.x as number) <= 0.01 && (bounds.y as number) <= 0.01;
      clipStack.push(isCanvasClip ? -1 : filtered.length);
      if (!isCanvasClip) filtered.push(step);
      continue;
    }
    if (step.type === "end-clip") {
      const open = clipStack.pop();
      if (open === -1) continue;
      filtered.push(step);
      continue;
    }
    filtered.push(step);
  }

  // Group consecutive steps by their root-level ancestor node.
  const segments: Segment[] = [];
  let current: Segment | null = null;
  let currentRoot: AnyRecord | null = null;
  for (const step of filtered) {
    const node = step.node as AnyRecord | undefined;
    const ancestor = node ? rootAncestor(node, root) : root;
    if (!current || ancestor !== currentRoot) {
      current = { steps: [], minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity, hash: "" };
      segments.push(current);
      currentRoot = ancestor;
    }
    current.steps.push(step);
    if (node?.bounds) {
      const b = node.bounds as AnyRecord;
      current.minX = Math.min(current.minX, b.x as number);
      current.minY = Math.min(current.minY, b.y as number);
      current.maxX = Math.max(current.maxX, (b.x as number) + (b.width as number));
      current.maxY = Math.max(current.maxY, (b.y as number) + (b.height as number));
    }
  }
  for (const segment of segments) {
    if (!Number.isFinite(segment.minX)) {
      segment.minX = 0; segment.minY = 0; segment.maxX = width; segment.maxY = height;
    }
    const pad = segmentPad(segment.steps);
    segment.minX = Math.max(0, Math.floor(segment.minX - pad));
    segment.minY = Math.max(0, Math.floor(segment.minY - pad));
    segment.maxX = Math.min(width, Math.ceil(segment.maxX + pad));
    segment.maxY = Math.min(height, Math.ceil(segment.maxY + pad));
    segment.hash = `${scale.toFixed(3)}|${segmentHash(segment.steps)}`;
  }

  const output = new OffscreenCanvas(Math.ceil(width * scale), Math.ceil(height * scale));
  const outCtx = output.getContext("2d");
  if (!outCtx) throw new Error("no 2d context");

  let repainted = 0;
  let reused = 0;
  for (const segment of segments) {
    let layer = layerCache.get(segment.hash);
    if (layer) {
      layerCache.delete(segment.hash);
      layerCache.set(segment.hash, layer);
      reused++;
    } else {
      const env: PaintEnv = {
        scale,
        originX: segment.minX,
        originY: segment.minY,
        segW: segment.maxX - segment.minX,
        segH: segment.maxY - segment.minY,
        clips: [],
      };
      const made = makeLayer(env);
      paintSteps(made.ctx, segment.steps, env);
      layer = { canvas: made.canvas, x: segment.minX, y: segment.minY };
      if (layerCache.size >= LAYER_CACHE_MAX) {
        const oldest = layerCache.keys().next().value;
        if (oldest) layerCache.delete(oldest);
      }
      layerCache.set(segment.hash, layer);
      repainted++;
    }
    outCtx.drawImage(layer.canvas, layer.x * scale, layer.y * scale);
  }

  const bitmap = output.transferToImageBitmap();
  return { bitmap, stats: { repainted, reused, ms: Math.round(performance.now() - started) } };
}

function paintSteps(ctx: Ctx, steps: AnyRecord[], env: PaintEnv) {
  const groupStack: { layer: { canvas: OffscreenCanvas; ctx: Ctx } | null; effects: AnyRecord; parent: Ctx }[] = [];
  let target = ctx;
  for (const step of steps) {
    if (step.type === "draw") {
      const node = step.node as AnyRecord;
      target.save();
      env.currentMatrix = node.transform as number[];
      applyMatrix(target, env.currentMatrix);
      paintDrawables(target, step.drawables as AnyRecord[], node, env);
      target.restore();
      env.currentMatrix = undefined;
    } else if (step.type === "begin-clip") {
      const node = step.node as AnyRecord;
      const path = shapePath(step.clip as AnyRecord);
      const matrix = node.transform as number[];
      target.save();
      applyMatrix(target, matrix);
      target.clip(path, ((step.clip as AnyRecord).fillRule as CanvasFillRule) || "nonzero");
      env.clips.push({ path, matrix, fillRule: (step.clip as AnyRecord).fillRule as string });
    } else if (step.type === "end-clip") {
      target.restore();
      env.clips.pop();
    } else if (step.type === "begin-group") {
      const effects = step.effects as AnyRecord;
      if (
        (effects.filters as unknown[] | undefined)?.length ||
        (effects.backdropFilters as unknown[] | undefined)?.length ||
        effects.mask || effects.clip
      ) {
        throw new UnsupportedPaint("group filters/mask");
      }
      const opacity = (effects.opacity as number) ?? 1;
      const blend = (effects.blendMode as string) ?? "normal";
      if (opacity === 1 && blend === "normal") {
        groupStack.push({ layer: null, effects, parent: target });
        continue;
      }
      const layer = makeLayer(env);
      for (const clip of env.clips) {
        layer.ctx.save();
        applyMatrix(layer.ctx, clip.matrix);
        layer.ctx.clip(clip.path, (clip.fillRule as CanvasFillRule) || "nonzero");
      }
      groupStack.push({ layer, effects, parent: target });
      target = layer.ctx;
    } else if (step.type === "end-group") {
      const group = groupStack.pop();
      if (!group) continue;
      target = group.parent;
      if (group.layer) {
        target.save();
        target.globalAlpha = ((group.effects.opacity as number) ?? 1);
        if (group.effects.blendMode && group.effects.blendMode !== "normal") {
          target.globalCompositeOperation = group.effects.blendMode as GlobalCompositeOperation;
        }
        blitLayer(target, group.layer.canvas);
        target.restore();
      }
    } else {
      throw new UnsupportedPaint(`step ${String(step.type)}`);
    }
  }
}
