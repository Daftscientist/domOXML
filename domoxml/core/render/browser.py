"""Headless-Chromium rendering via Playwright: rasterise a page and capture its layout."""

from __future__ import annotations

import contextlib
import math
import re
from types import TracebackType
from typing import Any, Self

from playwright.async_api import Browser, Playwright, Route, async_playwright
from pydantic import BaseModel, ConfigDict, Field

from domoxml.core.images import crop_png

# Walks the rendered DOM and, per element, captures its box, direct text, ordered inline
# text runs, the computed styles the extractor needs, and enough structure (index/parent)
# to let the extractor rasterise an element together with its subtree. This is the raw material.
_SNAPSHOT_JS = """
() => {
  const pick = (cs) => ({
    color: cs.color, backgroundColor: cs.backgroundColor, backgroundImage: cs.backgroundImage,
    backgroundSize: cs.backgroundSize, backgroundPosition: cs.backgroundPosition,
    backgroundRepeat: cs.backgroundRepeat,
    fontSize: cs.fontSize, fontFamily: cs.fontFamily,
    fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
    textDecorationLine: cs.textDecorationLine, textTransform: cs.textTransform,
    fontVariantCaps: cs.fontVariantCaps, letterSpacing: cs.letterSpacing,
    textAlign: cs.textAlign, lineHeight: cs.lineHeight,
    borderRadius: cs.borderRadius, opacity: cs.opacity,
    boxShadow: cs.boxShadow, filter: cs.filter,
    mixBlendMode: cs.mixBlendMode, backdropFilter: cs.backdropFilter,
    clipPath: cs.clipPath, transform: cs.transform, transformOrigin: cs.transformOrigin,
    borderTopWidth: cs.borderTopWidth, borderTopStyle: cs.borderTopStyle,
    borderTopColor: cs.borderTopColor,
    borderRightWidth: cs.borderRightWidth, borderRightStyle: cs.borderRightStyle,
    borderRightColor: cs.borderRightColor,
    borderBottomWidth: cs.borderBottomWidth, borderBottomStyle: cs.borderBottomStyle,
    borderBottomColor: cs.borderBottomColor,
    borderLeftWidth: cs.borderLeftWidth, borderLeftStyle: cs.borderLeftStyle,
    borderLeftColor: cs.borderLeftColor,
    display: cs.display, flexDirection: cs.flexDirection,
    justifyContent: cs.justifyContent, alignItems: cs.alignItems,
    overflow: cs.overflow, whiteSpace: cs.whiteSpace,
    columnCount: cs.columnCount, columnGap: cs.columnGap,
    marginTop: cs.marginTop, marginBottom: cs.marginBottom,
    textIndent: cs.textIndent, paddingLeft: cs.paddingLeft,
    listStyleType: cs.listStyleType, listStylePosition: cs.listStylePosition,
    objectFit: cs.objectFit, objectPosition: cs.objectPosition,
  });
  // The nearest enclosing <a href> for the run, captured as a synthetic style key so the
  // extractor can recover a:hlinkClick without a separate channel. textContent (not innerText)
  // keeps the run text raw, so text-transform stays a cap attr rather than baked-in glyphs.
  const linkHref = (el) => {
    const anchor = el.closest && el.closest('a[href]');
    return anchor ? anchor.getAttribute('href') : '';
  };
  // Count nesting depth and list type for <li> elements.
  const listContext = (el) => {
    let depth = 0;
    let listType = '';
    let ordinal = null;
    let node = el.parentElement;
    while (node) {
      const tag = node.tagName && node.tagName.toLowerCase();
      if (tag === 'ul' || tag === 'ol') {
        depth++;
        if (!listType) listType = getComputedStyle(node).listStyleType;
        if (tag === 'ol' && !listType) listType = 'decimal';
        if (tag === 'ul' && !listType) listType = 'disc';
        if (depth === 1 && tag === 'ol') {
          const items = Array.from(node.children).filter(
            (child) => child.tagName && child.tagName.toLowerCase() === 'li'
          );
          const step = node.reversed ? -1 : 1;
          let value = node.hasAttribute('start')
            ? node.start
            : (node.reversed ? items.length : 1);
          for (const item of items) {
            if (item.hasAttribute('value')) value = item.value;
            if (item === el) {
              ordinal = value;
              break;
            }
            value += step;
          }
        }
      }
      node = node.parentElement;
    }
    return { depth, listType, ordinal };
  };
  const consolidatesFlexText = (root) => {
    const style = getComputedStyle(root);
    const display = style.display;
    if (display !== 'flex' && display !== 'inline-flex') return false;
    if (!style.flexDirection.startsWith('column')) return false;
    const elements = Array.from(root.children);
    return elements.length > 0 && elements.every((child) => child.children.length === 0);
  };
  const inlineRuns = (root, consolidateFlex) => {
    const runs = [];
    const collect = (node, inherited, href, allowBlock = false) => {
      if (node.nodeType === 3) {
        let text = node.textContent || '';
        if (inherited.whiteSpace === 'normal' || inherited.whiteSpace === 'nowrap') {
          text = text.replace(/\\s+/g, ' ');
        }
        if (text) {
          const styles = pick(inherited);
          if (href) styles.domoxmlHref = href;
          runs.push({ text, styles });
        }
        return;
      }
      if (node.nodeType !== 1) return;
      const el = node;
      if (el.tagName.toLowerCase() === 'br') {
        const styles = pick(inherited);
        if (href) styles.domoxmlHref = href;
        runs.push({ text: '\\n', styles });
        return;
      }
      const cs = getComputedStyle(el);
      if (!allowBlock && !cs.display.startsWith('inline')) return;
      const childHref = el.tagName.toLowerCase() === 'a' && el.getAttribute('href')
        ? el.getAttribute('href') : href;
      for (const child of el.childNodes) collect(child, cs, childHref);
    };
    const rootStyle = getComputedStyle(root);
    const rootHref = linkHref(root);
    for (const child of root.childNodes) {
      if (consolidateFlex && child.nodeType === 3 && !child.textContent.trim()) continue;
      const before = runs.length;
      collect(child, rootStyle, rootHref, consolidateFlex && child.nodeType === 1);
      if (consolidateFlex && runs.slice(before).some((run) => run.text.trim())) {
        runs.push({ text: '\\n', styles: pick(rootStyle) });
      }
    }
    if (consolidateFlex && runs.at(-1)?.text === '\\n') runs.pop();
    return runs.some((run) => run.text.trim()) ? runs : [];
  };
  const out = [];
  const walk = (el, parent) => {
    const r = el.getBoundingClientRect();
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join('').trim();
    const index = out.length;
    el.dataset.domoxmlCaptureIndex = String(index);
    const styles = pick(getComputedStyle(el));
    const tag = el.tagName.toLowerCase();
    const consolidateFlex = consolidatesFlexText(el);
    if (consolidateFlex) styles.domoxmlConsolidatedText = 'true';
    // For <li> elements record the list nesting depth and list type.
    if (tag === 'li') {
      const ctx = listContext(el);
      styles.domoxmlListDepth = String(ctx.depth);
      styles.domoxmlListType = ctx.listType || styles.listStyleType || 'disc';
      if (ctx.ordinal !== null) styles.domoxmlListOrdinal = String(ctx.ordinal);
    }
    // For SVG path elements, capture the 'd' attribute in the src slot so the extractor
    // can parse it as a custom geometry without needing the HTML source.
    const svgSrc = (tag === 'path' || tag === 'svg')
      ? (el.getAttribute('d') || el.getAttribute('viewBox') || '')
      : (el.currentSrc || el.getAttribute('src') || '');
    // For table cells record the HTML colspan/rowspan so the extractor can build the grid.
    if (tag === 'td' || tag === 'th') {
      styles.domoxmlColSpan = String(el.colSpan || 1);
      styles.domoxmlRowSpan = String(el.rowSpan || 1);
    }
    // For the slide root element (first child of body), capture data-transition* attributes
    // so the extractor can recover SlideTransition IR.
    if (el.parentElement === document.body) {
      const tr = el.getAttribute('data-transition');
      const trDur = el.getAttribute('data-transition-duration');
      const trDir = el.getAttribute('data-transition-direction');
      if (tr) styles.domoxmlTransition = tr;
      if (trDur) styles.domoxmlTransitionDuration = trDur;
      if (trDir) styles.domoxmlTransitionDirection = trDir;
    }
    out.push({
      tag,
      x: r.x, y: r.y, width: r.width, height: r.height,
      text, index, parent,
      src: svgSrc,
      styles,
      textRuns: inlineRuns(el, consolidateFlex),
    });
    for (const child of el.children) walk(child, index);
  };
  walk(document.body, -1);
  return out;
}
"""

_CAPTURED_RESOURCE_TYPES = frozenset({"image", "font"})
_BLUR_RE = re.compile(r"blur\(\s*([\d.]+)px\s*\)", re.IGNORECASE)
_MATRIX_RE = re.compile(
    r"matrix\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*"
    r"([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*\)",
    re.IGNORECASE,
)
# Matches CSS rotate(Ndeg) / rotate(Nrad) / rotate(Nturn) / rotate(Ngrad).
_ROTATE_RE = re.compile(
    r"rotate\(\s*([-\d.eE]+)(deg|rad|turn|grad)\s*\)",
    re.IGNORECASE,
)
# Matches scaleX(N) / scaleY(N) — used for flip detection.
_SCALEX_RE = re.compile(r"scaleX\(\s*([-\d.eE]+)\s*\)", re.IGNORECASE)
_SCALEY_RE = re.compile(r"scaleY\(\s*([-\d.eE]+)\s*\)", re.IGNORECASE)
_ISOLATE_JS = """
(index) => {
  const selected = document.querySelector(`[data-domoxml-capture-index="${index}"]`);
  if (!selected) return () => {};
  const changed = [];
  for (const element of document.body.querySelectorAll('*')) {
    if (selected.contains(element) || element.contains(selected)) continue;
    changed.push([element, element.style.visibility]);
    element.style.visibility = 'hidden';
  }
  return () => {
    for (const [element, visibility] of changed) element.style.visibility = visibility;
  };
}
"""


class RenderedTextRun(BaseModel):
    """One ordered inline text fragment with Chromium-resolved typography."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    text: str
    styles: dict[str, str] = Field(default_factory=dict)


class RenderedNode(BaseModel):
    """One element as Chromium laid it out: box (CSS px), direct text, computed styles, plus
    its DOM ``index`` and ``parent`` index (root = ``-1``) for subtree-aware rasterisation."""

    model_config = ConfigDict(frozen=True)

    tag: str
    x: float
    y: float
    width: float
    height: float
    text: str = ""
    index: int = 0
    parent: int = -1
    src: str = ""
    styles: dict[str, str] = Field(default_factory=dict)
    text_runs: tuple[RenderedTextRun, ...] = Field(default_factory=tuple, alias="textRuns")


class RenderedRaster(BaseModel):
    """One isolated raster fallback region, including effect overflow."""

    model_config = ConfigDict(frozen=True)

    png: bytes
    x: float
    y: float
    width: float
    height: float


class RenderedSlide(BaseModel):
    """The render of one slide: its PNG, the captured layout tree, the resources Chromium
    fetched (image/font bytes keyed by URL), and the device scale the PNG was taken at."""

    model_config = ConfigDict(frozen=True)

    png: bytes
    width: int
    height: int
    scale: float = 1.0
    nodes: tuple[RenderedNode, ...]
    resources: dict[str, bytes] = Field(default_factory=dict)
    rasters: dict[int, RenderedRaster] = Field(default_factory=dict[int, RenderedRaster])


def _raster_padding(node: RenderedNode) -> float:
    match = _BLUR_RE.search(node.styles.get("filter", ""))
    return float(match.group(1)) * 3 if match is not None else 0.0


def _decompose_matrix(a: float, b: float, c: float, d: float) -> tuple[float, bool, bool] | None:
    """Decompose a 2-D linear matrix ``[a b c d]`` into ``(rotation_deg, flip_h, flip_v)`` when
    it is a pure rotation optionally combined with axis flips (±1 scale), else ``None``.

    A CSS matrix maps to OOXML as: optional flipH (negate x), optional flipV (negate y), then a
    rotation. Browsers emit ``rotate(θ)`` as ``matrix(cosθ, sinθ, -sinθ, cosθ, 0, 0)`` (y-down,
    so positive θ is clockwise — same convention as OOXML ``rot``). We try each of the four
    flip combinations and accept the one that leaves a clean rotation."""
    tol = 1e-3
    candidates: list[tuple[float, bool, bool]] = []
    for flip_h, sx in ((False, 1.0), (True, -1.0)):
        for flip_v, sy in ((False, 1.0), (True, -1.0)):
            # Undo the flips: a column scaled by sx/sy. Remaining must be a rotation matrix
            # [cos, sin, -sin, cos] with unit columns and matching cos/sin across both columns.
            ra, rb = a * sx, b * sx
            rc, rd = c * sy, d * sy
            if (
                abs(ra - rd) <= tol  # cosθ agrees
                and abs(rb + rc) <= tol  # sinθ agrees (rb = sinθ, rc = -sinθ)
                and abs((ra * ra + rb * rb) - 1.0) <= tol  # unit length ⇒ no scale/shear
            ):
                angle = math.degrees(math.atan2(rb, ra)) % 360.0
                candidates.append((angle, flip_h, flip_v))
    if not candidates:
        return None

    # A flip can be encoded as flipV+rot180 etc.; prefer the simplest reading: least rotation,
    # then fewest flips. So scaleX(-1) reads as (0°, flipH) not (180°, flipV).
    def _rank(cand: tuple[float, bool, bool]) -> tuple[float, int]:
        angle, fh, fv = cand
        return min(angle, 360.0 - angle), int(fh) + int(fv)

    return min(candidates, key=_rank)


def _matrix_is_complex(a: float, b: float, c: float, d: float) -> bool:
    """True when a 2-D matrix is NOT a pure rotation/flip (i.e. has shear or non-unit scale)."""
    return _decompose_matrix(a, b, c, d) is None


def is_complex_transform(value: str | None) -> bool:
    """Return True when ``value`` cannot be expressed as a pure translation, rotation, or flip.

    Pure rotation (``rotate(Ndeg)``), scale-by-±1 flips (``scaleX(-1)``/``scaleY(-1)``), and
    their combinations are **not** complex — they map natively to ``a:xfrm rot/flipH/flipV``.
    Skew, perspective, matrix-with-shear, and 3-D transforms remain complex (raster fallback).
    """
    if not value or value == "none":
        return False
    lowered = value.lower()
    if lowered.startswith("matrix3d") or "skew" in lowered or "perspective" in lowered:
        return True

    # Check for a matrix() — only non-translation 2-D transforms land here. NOTE: browsers
    # resolve getComputedStyle().transform to the matrix() form, so rotate(Ndeg) arrives here
    # as matrix(cos, sin, -sin, cos, …), NOT as a rotate() token. We must accept rotation +
    # flip matrices natively; only true shear / non-unit scale is complex.
    match = _MATRIX_RE.search(lowered)
    if match is not None:
        a, b, c, d = (float(match.group(index)) for index in range(1, 5))
        return _matrix_is_complex(a, b, c, d)

    # Functional form: strip translate/scaleX(±1)/scaleY(±1)/rotate tokens and see what's left.
    # Any remaining token other than translate → complex.
    remainder = lowered
    remainder = re.sub(r"translate[xy]?\([^)]*\)", "", remainder)
    remainder = re.sub(r"rotate\([^)]*\)", "", remainder)
    remainder = re.sub(r"scalex?\(\s*-?1\s*\)", "", remainder)
    remainder = re.sub(r"scaley\(\s*-?1\s*\)", "", remainder)
    remainder = remainder.strip()
    # If anything other than whitespace/commas remains it is an unrecognised function.
    remainder = re.sub(r"[\s,]+", "", remainder)
    return bool(remainder)


def parse_native_transform(value: str | None) -> tuple[float, bool, bool]:
    """Parse a CSS transform string that has already been verified non-complex.

    Returns ``(rotation_deg, flip_h, flip_v)`` where ``rotation_deg`` is the clockwise
    rotation in degrees (CSS and OOXML both use clockwise-positive degrees).

    Handles:
    - ``rotate(Ndeg|Nrad|Nturn|Ngrad)``
    - ``scaleX(-1)`` / ``scaleY(-1)``
    - ``matrix(a,b,c,d,e,f)`` where |a|=|d|=1 and b=c=0 (pure flip)
    - Combined forms: ``rotate(Ndeg) scaleX(-1)`` etc.

    Translation components are ignored (layout comes from the element's bounding box).
    """
    if not value or value == "none":
        return 0.0, False, False

    rotation_deg = 0.0
    flip_h = False
    flip_v = False
    lowered = value.lower()

    # Matrix form (what getComputedStyle returns): decompose into rotation + flips.
    matrix_match = _MATRIX_RE.search(lowered)
    if matrix_match is not None:
        a, b, c, d = (float(matrix_match.group(i)) for i in range(1, 5))
        decomposed = _decompose_matrix(a, b, c, d)
        if decomposed is not None:
            return decomposed
        return 0.0, False, False

    # Functional form — extract rotate and scale tokens.
    rot_match = _ROTATE_RE.search(lowered)
    if rot_match is not None:
        amount = float(rot_match.group(1))
        unit = rot_match.group(2)
        if unit == "rad":
            import math

            rotation_deg = math.degrees(amount) % 360.0
        elif unit == "turn":
            rotation_deg = (amount * 360.0) % 360.0
        elif unit == "grad":
            rotation_deg = (amount * 0.9) % 360.0
        else:  # deg
            rotation_deg = amount % 360.0

    sx_match = _SCALEX_RE.search(lowered)
    if sx_match is not None:
        flip_h = float(sx_match.group(1)) < -0.5

    sy_match = _SCALEY_RE.search(lowered)
    if sy_match is not None:
        flip_v = float(sy_match.group(1)) < -0.5

    return rotation_deg, flip_h, flip_v


def _needs_isolated_raster(node: RenderedNode) -> bool:
    styles = node.styles
    return (
        node.tag in {"svg", "canvas", "video", "iframe"}
        or "inset" in styles.get("boxShadow", "").lower()
        or styles.get("clipPath", "none") not in ("none", "")
        or styles.get("mixBlendMode", "normal") not in ("normal", "")
        or styles.get("backdropFilter", "none") not in ("none", "")
        or styles.get("filter", "none") not in ("none", "")
        or is_complex_transform(styles.get("transform"))
    )


class BrowserSession:
    """A warm headless-Chromium session. Use as an async context manager and call
    :meth:`render` once per slide::

        async with BrowserSession() as session:
            slide = await session.render(html, width=1280, height=720)
    """

    def __init__(self, *, scale: float = 2.0) -> None:
        self._scale = scale
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
        except BaseException:
            # __aexit__ won't run if __aenter__ raises — clean up the started Playwright here.
            await self._playwright.stop()
            self._playwright = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def render(self, html: str, *, width: int, height: int) -> RenderedSlide:
        """Render ``html`` at ``width`` x ``height`` CSS px → PNG + captured layout + the
        image/font bytes the page fetched (so they can be embedded natively downstream)."""
        if self._browser is None:
            raise RuntimeError("BrowserSession must be entered via 'async with' before render()")
        context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=self._scale,
        )
        resources: dict[str, bytes] = {}

        async def _capture(route: Route) -> None:
            if route.request.resource_type not in _CAPTURED_RESOURCE_TYPES:
                await route.continue_()
                return
            try:
                response = await route.fetch()
                resources[route.request.url] = await response.body()
            except Exception:  # capture is best-effort; never block the render
                await route.continue_()
                return
            try:
                await route.fulfill(response=response)
            except Exception:
                # If fulfill fails, resolve the intercepted request explicitly so page load
                # doesn't stall on an unresolved route.
                with contextlib.suppress(Exception):
                    await route.continue_()

        try:
            page = await context.new_page()
            await page.route("**/*", _capture)
            await page.set_content(html, wait_until="load")
            await page.evaluate("() => document.fonts.ready.then(() => true)")
            png = await page.screenshot(type="png")
            raw: list[dict[str, Any]] = await page.evaluate(_SNAPSHOT_JS)
            nodes = tuple(RenderedNode.model_validate(node) for node in raw)
            rasters: dict[int, RenderedRaster] = {}
            for node in nodes:
                if not _needs_isolated_raster(node):
                    continue
                restore = await page.evaluate_handle(_ISOLATE_JS, node.index)
                try:
                    isolated_page = await page.screenshot(type="png")
                finally:
                    await restore.evaluate("(restore) => restore()")
                    await restore.dispose()
                padding = _raster_padding(node)
                x = max(0.0, node.x - padding)
                y = max(0.0, node.y - padding)
                right = min(float(width), node.x + node.width + padding)
                bottom = min(float(height), node.y + node.height + padding)
                crop = crop_png(
                    isolated_page,
                    left=x * self._scale,
                    top=y * self._scale,
                    width=(right - x) * self._scale,
                    height=(bottom - y) * self._scale,
                )
                if crop is not None:
                    rasters[node.index] = RenderedRaster(
                        png=crop, x=x, y=y, width=right - x, height=bottom - y
                    )
            return RenderedSlide(
                png=png,
                width=width,
                height=height,
                scale=self._scale,
                nodes=nodes,
                resources=resources,
                rasters=rasters,
            )
        finally:
            await context.close()
