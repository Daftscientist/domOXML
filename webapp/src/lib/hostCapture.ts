// Host-capture export: the page's own browser does the layout.
//
// The engine composes each slide page (Python compose_page, the desktop
// code); this module loads each page in an offscreen iframe, evaluates
// the shared snapshot payload in it — the same payload the desktop
// Chromium path evaluates — and hands the captured layout to the engine,
// which runs the desktop extraction and emission over it. CSS the
// browser supports therefore converts even where Takumi's parser
// cannot. Takumi is used only for pixels a page cannot produce itself:
// the isolated-node rasters the extractor plans, backdrop layers, and
// the full-slide fallback PNG.
import { engine } from "./engine";
import type { ConvertResult, SlideTransition } from "./types";

export interface SlideCapture {
  raw: unknown[];
  resources: Record<string, string>;
  png_b64: string;
  rasters: Record<number, string>;
  backdrop_sharp: Record<number, string>;
}

interface CaptureHandle {
  iframe: HTMLIFrameElement;
  doc: Document;
  win: Window;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Rasterise with parse repair. Staged clones carry computed styles, and
 * a slide carries authored CSS; both can contain individual values
 * Takumi's parser rejects (it names the property in its error, e.g.
 * "invalid value for placeSelf ..."). One bad value must not cost the
 * whole raster: strip that property from style attributes and retry,
 * a few times. Properties whose value embeds a url( are never stripped
 * (their text can contain characters the strip pattern would misread).
 */
async function rasterWithRepair(
  html: string,
  width: number,
  height: number,
): Promise<string | null> {
  let current = html;
  for (let attempt = 0; attempt < 8; attempt++) {
    const { png, message } = await engine.takumiRasterDetailed(current, width, height);
    if (png) return png;
    const named = message?.match(/invalid value for ([A-Za-z]+)/);
    if (!named) return null;
    const cssName = named[1].replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
    const pattern = new RegExp(`${cssName}\\s*:[^;"]*;?`, "g");
    const stripped = current.replace(pattern, (segment) =>
      segment.includes("url(") ? segment : "",
    );
    if (stripped === current) return null;
    current = stripped;
  }
  return null;
}

async function openCapture(
  page: string,
  recorderJs: string,
  width: number,
  height: number,
): Promise<CaptureHandle> {
  const iframe = document.createElement("iframe");
  iframe.setAttribute(
    "style",
    `position:absolute;left:-100000px;top:0;border:0;width:${width}px;height:${height}px;`,
  );
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);
  try {
    // The canvas recorder is an init script on the desktop path; as the
    // first script in <head> it runs before the body is parsed, which
    // is close enough for slides (their canvases are static markup).
    const withRecorder = page.includes("<head>")
      ? page.replace("<head>", `<head><script>${recorderJs}<\/script>`)
      : `<script>${recorderJs}<\/script>` + page;
    iframe.srcdoc = withRecorder;
    // Do NOT trust the iframe load event: it fires for the initial
    // about:blank document before the srcdoc navigation lands, and that
    // blank document also reports readyState "complete" with a body.
    // A srcdoc document is identified by its URL.
    for (let i = 0; i < 600; i++) {
      const win = iframe.contentWindow;
      const doc = iframe.contentDocument;
      if (
        win &&
        doc &&
        win.location.href === "about:srcdoc" &&
        doc.readyState === "complete" &&
        doc.body
      ) {
        try {
          await Promise.race([
            doc.fonts.ready,
            sleep(5000),
          ]);
        } catch {
          /* fonts are best-effort; layout is already resolved */
        }
        return { iframe, doc, win };
      }
      await sleep(50);
    }
    throw new Error("Capture iframe never finished loading the slide");
  } catch (error) {
    iframe.remove();
    throw error;
  }
}

/** Copy computed styles from a live subtree onto its clone, so the clone
 * paints the same when staged on its own and handed to Takumi. */
function inlineComputedStyles(source: Element, clone: Element): void {
  const srcEls = [source, ...source.querySelectorAll("*")];
  const cloneEls = [clone, ...clone.querySelectorAll("*")];
  const budget = 500;
  for (let i = 0; i < srcEls.length && i < cloneEls.length && i < budget; i++) {
    const cs = getComputedStyle(srcEls[i]);
    const target = (cloneEls[i] as HTMLElement).style;
    if (!target) continue;
    for (let j = 0; j < cs.length; j++) {
      const prop = cs[j];
      target.setProperty(prop, cs.getPropertyValue(prop), cs.getPropertyPriority(prop));
    }
  }
}

function stageNodeHtml(
  handle: CaptureHandle,
  index: number,
  bounds: [number, number, number, number],
  nodeXY: { x: number; y: number },
): string | null {
  const { doc } = handle;
  const src = doc.querySelector(`[data-domoxml-capture-index="${index}"]`);
  if (!src) return null;
  const [bx, by, bw, bh] = bounds;
  const stage = doc.createElement("div");
  stage.setAttribute(
    "style",
    `position:relative;width:${bw}px;height:${bh}px;overflow:hidden;` +
      "background:transparent;margin:0;padding:0;",
  );
  const clone = src.cloneNode(true) as Element;
  inlineComputedStyles(src, clone);
  const cloneStyle = (clone as HTMLElement).style;
  // Re-anchor the clone root in the stage. The inlined computed styles
  // carry the element's slide-relative offsets (inset/right/bottom as
  // resolved against the whole slide); inside a bounds-sized stage
  // those squeeze the box to nothing, so the offset family is reset
  // outright and only the staged left/top survive.
  cloneStyle.removeProperty("inset");
  cloneStyle.removeProperty("inset-block");
  cloneStyle.removeProperty("inset-inline");
  cloneStyle.position = "absolute";
  cloneStyle.left = `${nodeXY.x - bx}px`;
  cloneStyle.top = `${nodeXY.y - by}px`;
  cloneStyle.right = "auto";
  cloneStyle.bottom = "auto";
  cloneStyle.margin = "0";
  stage.appendChild(clone);
  const html = stage.outerHTML;
  return (
    `<!doctype html><html><head><meta charset="utf-8">` +
    `<style>html,body{margin:0;padding:0}body{width:${bw}px;height:${bh}px;overflow:hidden}</style>` +
    `</head><body>${html}</body></html>`
  );
}

async function sharpBackdropPng(
  handle: CaptureHandle,
  index: number,
  width: number,
  height: number,
): Promise<string | null> {
  const { doc } = handle;
  const el = doc.querySelector(`[data-domoxml-capture-index="${index}"]`) as HTMLElement | null;
  if (!el) return null;
  const previous = el.style.visibility;
  el.style.visibility = "hidden";
  try {
    const html = "<!doctype html>" + doc.documentElement.outerHTML;
    return await rasterWithRepair(html, width, height);
  } finally {
    el.style.visibility = previous;
  }
}

/** Capture one composed slide page: snapshot, resources, planned rasters. */
async function captureSlide(
  page: string,
  scripts: { snapshot_js: string; resources_js: string; recorder_js: string },
  width: number,
  height: number,
): Promise<SlideCapture> {
  const handle = await openCapture(page, scripts.recorder_js, width, height);
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const raw = (handle.win as any).eval(scripts.snapshot_js)() as unknown[];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const resources = (handle.win as any).eval(scripts.resources_js)(handle.doc) as Record<
      string,
      string
    >;
    const rawByIndex = new Map<number, { x: number; y: number }>();
    for (const node of raw as { index: number; x: number; y: number }[]) {
      rawByIndex.set(node.index, { x: node.x, y: node.y });
    }
    const plan = await engine.capturePlan(raw, { width, height });

    const backdrop_sharp: Record<number, string> = {};
    for (const entry of plan.backdrops) {
      const png = await sharpBackdropPng(handle, entry.index, width, height);
      if (png) backdrop_sharp[entry.index] = png;
    }
    const rasters: Record<number, string> = {};
    for (const entry of plan.isolated) {
      const xy = rawByIndex.get(entry.index);
      if (!xy) continue;
      const staged = stageNodeHtml(handle, entry.index, entry.bounds, xy);
      if (!staged) continue;
      const png = await rasterWithRepair(staged, entry.bounds[2], entry.bounds[3]);
      if (png) rasters[entry.index] = png;
    }
    const png_b64 = (await rasterWithRepair(page, width, height)) ?? "";
    return { raw, resources, png_b64, rasters, backdrop_sharp };
  } finally {
    handle.iframe.remove();
  }
}

/** Capture a single fragment (for IR derivation of the open slide). */
export async function captureOneSlide(
  fragment: string,
  opts: { width: number; height: number; css?: string },
): Promise<SlideCapture> {
  const { pages, snapshot_js, resources_js, recorder_js } = await engine.capturePages(
    [fragment],
    opts,
  );
  return captureSlide(pages[0], { snapshot_js, resources_js, recorder_js }, opts.width, opts.height);
}

export async function exportViaHostCapture(deck: {
  fragments: string[];
  width: number;
  height: number;
  css?: string;
  transitions?: (SlideTransition | null)[];
}): Promise<ConvertResult> {
  const { width, height } = deck;
  const scripts = await engine.capturePages(deck.fragments, {
    width,
    height,
    css: deck.css,
  });
  const captures: SlideCapture[] = [];
  for (const page of scripts.pages) {
    captures.push(await captureSlide(page, scripts, width, height));
  }
  return engine.convertCaptured({
    fragments: deck.fragments,
    captures,
    width,
    height,
    css: deck.css,
    transitions: deck.transitions,
  });
}
