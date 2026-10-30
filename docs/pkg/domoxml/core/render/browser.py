"""Headless-Chromium rendering via Playwright: rasterise a page and capture its layout."""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright, Route

from domoxml.core.images import crop_png
from domoxml.core.ir.parse import parse_shadows
from domoxml.core.units import emu_to_px

# Walks the rendered DOM and, per element, captures its box, direct text, ordered inline
# text runs, the computed styles the extractor needs, and enough structure (index/parent)
# to let the extractor rasterise an element together with its subtree. This is the raw material.
# The payload lives in a standalone asset so a browser host (Pyodide) can run the
# identical text inside a host page; Playwright evaluates the same string here.
_SNAPSHOT_JS = (Path(__file__).with_name("snapshot.js")).read_text(encoding="utf-8")

_CAPTURED_RESOURCE_TYPES = frozenset({"image", "font"})
# The only scheme a render legitimately needs. Rendered HTML is attacker-influenced (callers
# embed sanitizer output, not trusted markup), so this is a hard boundary, not a default —
# there is deliberately no way to widen it from BrowserSession's constructor.
_ALLOWED_URL_SCHEMES = frozenset({"data"})
_BLUR_RE = re.compile(r"blur\(\s*([\d.]+)px\s*\)", re.IGNORECASE)
_BOX_REFLECTION_RE = re.compile(r"^(above|below|left|right)\s+(-?[\d.]+)px\b", re.IGNORECASE)
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
  const rootStyles = [
    [document.documentElement, document.documentElement.style.cssText],
    [document.body, document.body.style.cssText],
  ];
  const elements = [
    document.documentElement,
    document.body,
    ...document.body.querySelectorAll('*'),
  ];
  for (const element of elements) {
    changed.push([
      element,
      element.style.getPropertyValue('visibility'),
      element.style.getPropertyPriority('visibility'),
    ]);
    element.style.setProperty(
      'visibility',
      element === selected || selected.contains(element) ? 'visible' : 'hidden',
      'important',
    );
  }
  for (const [element] of rootStyles) {
    element.style.setProperty('background', 'transparent', 'important');
    element.style.setProperty('background-color', 'transparent', 'important');
    element.style.setProperty('background-image', 'none', 'important');
  }
  return () => {
    for (const [element, visibility, priority] of changed) {
      if (visibility) element.style.setProperty('visibility', visibility, priority);
      else element.style.removeProperty('visibility');
    }
    for (const [element, cssText] of rootStyles) element.style.cssText = cssText;
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


def _raster_bounds(
    node: RenderedNode, *, slide_width: int, slide_height: int
) -> tuple[float, float, float, float]:
    """Return slide-clamped paint bounds for an isolated element raster."""
    encoded_bounds = node.styles.get("domoxmlRasterBounds", "").split()
    if len(encoded_bounds) == 4:
        try:
            left, top, width, height = (float(value) for value in encoded_bounds)
        except ValueError:
            pass
        else:
            if all(math.isfinite(value) for value in (left, top, width, height)) and (
                width > 0 and height > 0
            ):
                clamped_left = min(float(slide_width), max(0.0, left))
                clamped_top = min(float(slide_height), max(0.0, top))
                return (
                    clamped_left,
                    clamped_top,
                    max(clamped_left, min(float(slide_width), left + width)),
                    max(clamped_top, min(float(slide_height), top + height)),
                )
    match = _BLUR_RE.search(node.styles.get("filter", ""))
    padding = float(match.group(1)) * 3 if match is not None else 0.0
    left = node.x - padding
    top = node.y - padding
    right = node.x + node.width + padding
    bottom = node.y + node.height + padding

    shadows = parse_shadows(node.styles.get("boxShadow"))
    for shadow in shadows if len(shadows) > 1 else ():
        if shadow.inset:
            continue
        radians = math.radians(shadow.direction_deg)
        offset_x = emu_to_px(shadow.distance_emu) * math.cos(radians)
        offset_y = emu_to_px(shadow.distance_emu) * math.sin(radians)
        # Chromium expands a box-shadow blur by three standard deviations, where the
        # standard deviation is half the blur radius. The 1.5x paint extent avoids
        # transparent fallback padding that would inflate raster-area accounting.
        extent = max(
            0.0,
            (1.5 * emu_to_px(shadow.blur_emu)) + emu_to_px(shadow.spread_emu),
        )
        candidates = (
            node.x + offset_x - extent,
            node.y + offset_y - extent,
            node.x + node.width + offset_x + extent,
            node.y + node.height + offset_y + extent,
        )
        snapped = tuple(
            float(round(value)) if abs(value - round(value)) < 0.001 else value
            for value in candidates
        )
        shadow_left, shadow_top, shadow_right, shadow_bottom = snapped
        left = min(left, shadow_left)
        top = min(top, shadow_top)
        right = max(right, shadow_right)
        bottom = max(bottom, shadow_bottom)

    reflection = _BOX_REFLECTION_RE.match(node.styles.get("webkitBoxReflect", ""))
    reflection_blur = 0.0
    if reflection is None and node.styles.get("domoxmlReflectionDistance"):
        direction = "below"
        distance = max(0.0, float(node.styles["domoxmlReflectionDistance"]))
        reflection_blur = max(0.0, float(node.styles.get("domoxmlReflectionBlur", "0")))
    elif reflection is not None:
        direction = reflection.group(1).lower()
        distance = max(0.0, float(reflection.group(2)))
    else:
        direction = ""
        distance = 0.0

    if direction:
        transform = node.styles.get("transform", "none")
        matrix = _MATRIX_RE.search(transform)
        if transform not in ("", "none") and matrix is None:
            return (0.0, 0.0, float(slide_width), float(slide_height))
        a, b, c, d = (
            (float(matrix.group(index)) for index in range(1, 5))
            if matrix is not None
            else (1.0, 0.0, 0.0, 1.0)
        )
        layout_width = float(node.styles.get("domoxmlLayoutWidth", node.width))
        layout_height = float(node.styles.get("domoxmlLayoutHeight", node.height))

        def transformed_rect(
            x0: float, y0: float, x1: float, y1: float
        ) -> tuple[float, float, float, float]:
            points = (
                (a * x0 + c * y0, b * x0 + d * y0),
                (a * x1 + c * y0, b * x1 + d * y0),
                (a * x0 + c * y1, b * x0 + d * y1),
                (a * x1 + c * y1, b * x1 + d * y1),
            )
            xs, ys = zip(*points, strict=True)
            return min(xs), min(ys), max(xs), max(ys)

        original = transformed_rect(0.0, 0.0, layout_width, layout_height)
        if direction == "below":
            reflected = transformed_rect(
                0.0,
                layout_height + distance,
                layout_width,
                (2 * layout_height) + distance,
            )
        elif direction == "above":
            reflected = transformed_rect(0.0, -layout_height - distance, layout_width, -distance)
        elif direction == "left":
            reflected = transformed_rect(-layout_width - distance, 0.0, -distance, layout_height)
        else:
            reflected = transformed_rect(
                layout_width + distance,
                0.0,
                (2 * layout_width) + distance,
                layout_height,
            )
        ref_left = node.x + reflected[0] - original[0]
        ref_top = node.y + reflected[1] - original[1]
        ref_right = node.x + reflected[2] - original[0]
        ref_bottom = node.y + reflected[3] - original[1]
        reflected_padding = padding + (reflection_blur * 3)
        left = min(left, ref_left - reflected_padding)
        top = min(top, ref_top - reflected_padding)
        right = max(right, ref_right + reflected_padding)
        bottom = max(bottom, ref_bottom + reflected_padding)
    return (
        max(0.0, left),
        max(0.0, top),
        min(float(slide_width), right),
        min(float(slide_height), bottom),
    )


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
    shadows = parse_shadows(styles.get("boxShadow"))
    return (
        node.tag in {"svg", "canvas", "video", "iframe"}
        or "inset" in styles.get("boxShadow", "").lower()
        or len(shadows) > 1
        or styles.get("clipPath", "none") not in ("none", "")
        or styles.get("mixBlendMode", "normal") not in ("normal", "")
        or styles.get("backdropFilter", "none") not in ("none", "")
        or styles.get("filter", "none") not in ("none", "")
        or styles.get("maskImage", "none") not in ("none", "")
        or styles.get("webkitBoxReflect", "none") not in ("none", "")
        or bool(styles.get("domoxmlReflectionDistance"))
        or is_complex_transform(styles.get("transform"))
    )


def nodes_from_snapshot(raw: Iterable[dict[str, Any]]) -> tuple[RenderedNode, ...]:
    """Validate raw snapshot dictionaries (as returned by ``snapshot.js``) into nodes.

    Shared by the Playwright capture path and the browser-host (Pyodide) capture path so
    both build identical node tuples from identical payloads."""
    return tuple(RenderedNode.model_validate(node) for node in raw)


def fixed_canvas_size(
    nodes: Iterable[RenderedNode], *, width: int, height: int
) -> tuple[int, int] | None:
    """Detect a fixed-size authoring canvas that disagrees with the declared slide size.

    Slides are often authored as one fixed-size root element (e.g. a 1600x900 ``<main>``
    whose children are positioned in its own pixel space). If such a root — a direct
    child of ``<body>``, anchored at the page origin, at least as large as the declared
    slide in both dimensions and strictly larger in one — contains every other captured
    node, the content's coordinate space is the canvas's, not the declared size's, and
    emitting it onto the declared slide mis-scales the native layer against any
    screenshot-derived layer. Return the canvas size so the caller can re-capture at
    the size the content was actually authored at; ``None`` when no such canvas exists
    (the normal case: fluid content, or a canvas that already matches the slide)."""
    node_list = list(nodes)
    body = next((node for node in node_list if node.parent == -1), None)
    if body is None:
        return None
    eps = 1.0
    best: tuple[int, int] | None = None
    for candidate in node_list:
        if candidate.parent != body.index:
            continue
        if not (-eps <= candidate.x <= eps and -eps <= candidate.y <= eps):
            continue
        canvas_w, canvas_h = round(candidate.width), round(candidate.height)
        if canvas_w < width or canvas_h < height or (canvas_w, canvas_h) == (width, height):
            continue
        right = candidate.x + candidate.width
        bottom = candidate.y + candidate.height
        if not all(
            node.x >= candidate.x - eps
            and node.y >= candidate.y - eps
            and node.x + node.width <= right + eps
            and node.y + node.height <= bottom + eps
            for node in node_list
            if node.index != body.index
        ):
            continue
        if best is None or canvas_w * canvas_h > best[0] * best[1]:
            best = (canvas_w, canvas_h)
    return best


def rasters_from_pngs(
    nodes: Iterable[RenderedNode],
    pngs: dict[int, bytes],
    *,
    slide_width: int,
    slide_height: int,
) -> dict[int, RenderedRaster]:
    """Assemble isolated-raster records from PNGs already cropped to each node's raster
    bounds, keyed by node index. Bounds come from :func:`_raster_bounds`, exactly as the
    Playwright path computes them before cropping its full-page screenshot."""
    rasters: dict[int, RenderedRaster] = {}
    for node in nodes:
        png = pngs.get(node.index)
        if png is None:
            continue
        x, y, right, bottom = _raster_bounds(
            node, slide_width=slide_width, slide_height=slide_height
        )
        rasters[node.index] = RenderedRaster(
            png=png, x=x, y=y, width=right - x, height=bottom - y
        )
    return rasters


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
        # Imported lazily so this module (and the whole package) imports cleanly where
        # Playwright is absent — notably Pyodide, where capture runs in the host page.
        from playwright.async_api import async_playwright

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
            # Unconditional network-isolation boundary. Runs before anything else so no request
            # this handler wasn't explicitly asked to fetch can reach the network — regardless of
            # how the URL got into the DOM (img src, legacy `background=`, SVG `fill="url(...)"`,
            # CSS `background-image`, @font-face, ...).
            if urlsplit(route.request.url).scheme.lower() not in _ALLOWED_URL_SCHEMES:
                await route.abort()
                return
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
            nodes = nodes_from_snapshot(raw)
            crops: dict[int, bytes] = {}
            for node in nodes:
                if not _needs_isolated_raster(node):
                    continue
                restore = await page.evaluate_handle(_ISOLATE_JS, node.index)
                try:
                    isolated_page = await page.screenshot(type="png", omit_background=True)
                finally:
                    await restore.evaluate("(restore) => restore()")
                    await restore.dispose()
                x, y, right, bottom = _raster_bounds(node, slide_width=width, slide_height=height)
                crop = crop_png(
                    isolated_page,
                    left=x * self._scale,
                    top=y * self._scale,
                    width=(right - x) * self._scale,
                    height=(bottom - y) * self._scale,
                )
                if crop is not None:
                    crops[node.index] = crop
            rasters = rasters_from_pngs(nodes, crops, slide_width=width, slide_height=height)
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
