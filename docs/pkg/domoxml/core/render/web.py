"""Browser-host capture: build a :class:`RenderedSlide` from snapshot data produced by
running ``snapshot.js`` inside a host page (e.g. under Pyodide), with no Playwright.

The host page owns the DOM. It composes the slide page (see :func:`compose_page`), runs
the snapshot payload in an offscreen document, rasterises any nodes the extractor would
isolate, and hands the plain results — snapshot dictionaries, PNG bytes, captured
resources — to the functions here. Everything after capture (IR extraction, font
resolution, OOXML emission) is the same code the Playwright path runs.
"""

from __future__ import annotations

import base64
import binascii
import sys
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, Self

from domoxml.core.render.browser import (
    _SNAPSHOT_JS,
    BrowserSession,
    RenderedSlide,
    _needs_isolated_raster,
    _raster_bounds,
    nodes_from_snapshot,
    rasters_from_pngs,
)
from domoxml.types import ConversionWarning, CoverageItem

__all__ = [
    "HostCaptureSession",
    "compose_pptx",
    "isolated_raster_plan",
    "open_session",
    "resources_from_base64",
    "slide_from_snapshot",
]


def _is_browser_runtime() -> bool:
    """True when running under a browser-hosted Python runtime (Pyodide): the platform
    is Emscripten, or the Pyodide ``js`` bridge module is importable. Plain CPython
    answers False on both counts, so this is safe to call anywhere."""
    if sys.platform == "emscripten":
        return True
    try:
        import js  # noqa: F401  (only exists under Pyodide)
    except ImportError:
        return False
    return True


def open_session(
    *, scale: float = 2.0, raster_library_url: str | None = None
) -> BrowserSession | HostCaptureSession:
    """Return the capture session for the current runtime — the package's single
    autodetect point. Server/normal CPython gets the Playwright :class:`BrowserSession`
    (unchanged behaviour); a browser runtime (Pyodide) gets :class:`HostCaptureSession`,
    which captures from the host page instead. Both expose the same async interface:
    ``async with session: slide = await session.render(html, width=…, height=…)``."""
    if _is_browser_runtime():
        return HostCaptureSession(scale=scale, raster_library_url=raster_library_url)
    return BrowserSession(scale=scale)


def isolated_raster_plan(
    raw: Iterable[dict[str, Any]], *, slide_width: int, slide_height: int
) -> dict[int, tuple[float, float, float, float]]:
    """Map node index → raster bounds ``(x, y, width, height)`` in CSS px for every
    snapshot node the extractor would isolate, using the same predicate
    (:func:`_needs_isolated_raster`) and bounds (:func:`_raster_bounds`) as the
    Playwright path. The host rasterises each planned region and returns PNGs keyed by
    the same indices to :func:`slide_from_snapshot`."""
    plan: dict[int, tuple[float, float, float, float]] = {}
    for node in nodes_from_snapshot(raw):
        if not _needs_isolated_raster(node):
            continue
        x, y, right, bottom = _raster_bounds(
            node, slide_width=slide_width, slide_height=slide_height
        )
        plan[node.index] = (x, y, right - x, bottom - y)
    return plan


def resources_from_base64(mapping: Mapping[str, str]) -> dict[str, bytes]:
    """Decode host-collected resources — ``{url: base64_payload}`` — into the
    ``{url: bytes}`` shape :class:`RenderedSlide` carries. The Playwright path only ever
    captures ``data:`` URLs (every other scheme is aborted at the route boundary), so the
    host collects the ``data:`` URLs the page references the same way."""
    resources: dict[str, bytes] = {}
    for url, payload in mapping.items():
        try:
            resources[url] = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            continue  # a malformed capture must not block the render, as on the server path
    return resources


def slide_from_snapshot(
    raw: Iterable[dict[str, Any]],
    *,
    width: int,
    height: int,
    scale: float = 2.0,
    png: bytes = b"",
    resources: Mapping[str, bytes] | None = None,
    raster_pngs: Mapping[int, bytes] | None = None,
) -> RenderedSlide:
    """Assemble the :class:`RenderedSlide` the Playwright path would have produced for
    the same page: nodes validated from the snapshot dictionaries, isolated rasters
    assembled from host-rendered PNGs with server-identical bounds, and the page's
    captured image/font resources attached."""
    nodes = nodes_from_snapshot(raw)
    rasters = rasters_from_pngs(
        nodes, dict(raster_pngs or {}), slide_width=width, slide_height=height
    )
    return RenderedSlide(
        png=png,
        width=width,
        height=height,
        scale=scale,
        nodes=nodes,
        resources=dict(resources or {}),
        rasters=rasters,
    )


def compose_pptx(
    rendered: list[RenderedSlide],
) -> tuple[bytes, tuple[CoverageItem, ...], tuple[ConversionWarning, ...]]:
    """Compose captured slides into a ``.pptx`` — the post-capture half of
    :meth:`Presentation.arender`, step for step: extract IR per slide, resolve font
    faces against the captured resources, emit OOXML. Returns the deck bytes plus the
    coverage items and warnings the extraction produced."""
    from domoxml.core.fonts import resolve_faces
    from domoxml.core.ir import extract_slide
    from domoxml.slides import build_pptx

    extracts = [extract_slide(slide) for slide in rendered]
    coverage: list[CoverageItem] = []
    warnings: list[ConversionWarning] = []
    for extracted in extracts:
        coverage.extend(extracted.coverage)
        warnings.extend(extracted.warnings)
    captured_fonts: dict[str, bytes] = {}
    for slide in rendered:
        captured_fonts.update(slide.resources)
    faces, font_warnings = resolve_faces(
        [extracted.slide for extracted in extracts], captured_fonts=captured_fonts
    )
    warnings.extend(font_warnings)
    pptx = build_pptx([extracted.slide for extracted in extracts], faces=faces)
    return pptx, tuple(coverage), tuple(warnings)


# Evaluated in the slide document: collect the resources the Playwright path would have
# captured. Its route boundary only ever lets data: URLs through, so this returns every
# data: URL the page references via <img> or @font-face, as {url: base64 payload}.
_RESOURCES_JS = """
(doc) => {
  const payload = (url) => {
    const comma = url.indexOf(',');
    if (comma < 0) return null;
    const meta = url.slice(0, comma);
    const data = url.slice(comma + 1);
    if (/;base64/i.test(meta)) return data;
    try {
      const text = decodeURIComponent(data);
      let bin = '';
      for (const byte of new TextEncoder().encode(text)) bin += String.fromCharCode(byte);
      return btoa(bin);
    } catch { return null; }
  };
  const resources = {};
  const add = (url) => {
    if (typeof url === 'string' && url.startsWith('data:') && !(url in resources)) {
      const data = payload(url);
      if (data !== null) resources[url] = data;
    }
  };
  for (const img of doc.images) add(img.currentSrc || img.src);
  for (const sheet of doc.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const rule of rules) {
      if (rule.type === 7) {  // CSSRule.FONT_FACE_RULE
        for (const match of rule.cssText.matchAll(/url\\((data:[^)]+)\\)/g)) add(match[1]);
      }
    }
  }
  return resources;
}
"""


class HostCaptureSession:
    """Capture backend for browser runtimes (Pyodide): instead of driving a Playwright
    Chromium, render each composed page in an offscreen iframe inside the host page and
    let the host's own Chromium do the layout — the same engine, one less process.

    Mirrors :class:`BrowserSession`'s interface (async context manager,
    ``render(html, *, width, height) -> RenderedSlide``). The snapshot payload, the
    raster predicate/bounds and the slide assembly are shared with the Playwright path;
    only transport differs. Isolated rasters and the full-slide PNG are produced with
    dom-to-image-more (loaded into the slide document from ``raster_library_url``, an
    explicit constructor argument, or the host page's ``__domoxml_raster_url`` global);
    without it, capture degrades to layout-only (no rasters, empty slide PNG) rather
    than failing.
    """

    def __init__(self, *, scale: float = 2.0, raster_library_url: str | None = None) -> None:
        self._scale = scale
        self._raster_library_url = raster_library_url

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def render(self, html: str, *, width: int, height: int) -> RenderedSlide:
        """Render the composed ``html`` page in an offscreen host-page iframe and
        capture it exactly as :meth:`BrowserSession.render` would."""
        from js import document, window

        async def js_sleep(ms: int) -> None:
            # A JS-side sleep: a Python callable handed to setTimeout would be a
            # borrowed proxy, destroyed before it ever fires.
            await window.eval(f"new Promise((resolve) => setTimeout(resolve, {ms}))")

        iframe = document.createElement("iframe")
        iframe.setAttribute(
            "style",
            f"position:absolute;left:-100000px;top:0;border:0;"
            f"width:{width}px;height:{height}px;",
        )
        document.body.appendChild(iframe)
        try:
            iframe.srcdoc = html
            # Do NOT trust the iframe load event here: it fires for the initial
            # about:blank document before the srcdoc navigation lands, and that
            # blank document also reports readyState "complete" with a body — so
            # neither signal distinguishes it. A srcdoc document is identified by
            # its URL: poll until the frame's location is about:srcdoc AND that
            # document is complete with a body.
            iwin = iframe.contentWindow
            idoc = None
            for _ in range(600):
                if iwin.location.href == "about:srcdoc":
                    candidate = iframe.contentDocument
                    if (
                        candidate is not None
                        and candidate.readyState == "complete"
                        and getattr(candidate, "body", None) is not None
                    ):
                        idoc = candidate
                        break
                await js_sleep(50)
            if idoc is None:
                raise TimeoutError("host-page iframe never finished loading the slide")
            await idoc.fonts.ready
            raw = iwin.eval(_SNAPSHOT_JS)().to_py()
            nodes = nodes_from_snapshot(raw)
            plan = isolated_raster_plan(raw, slide_width=width, slide_height=height)

            raster_pngs: dict[int, bytes] = {}
            slide_png = b""
            if await self._ensure_rasteriser(idoc, iwin):
                node_by_index = {node.index: node for node in nodes}
                for index, bounds in plan.items():
                    png = await self._rasterise_node(
                        idoc, iwin, index, bounds, node_by_index[index]
                    )
                    if png is not None:
                        raster_pngs[index] = png
                slide_png = (
                    await self._rasterise_region(iwin, idoc.body, width, height) or b""
                )
            resources = resources_from_base64(iwin.eval(_RESOURCES_JS)(idoc).to_py())
            return slide_from_snapshot(
                raw,
                width=width,
                height=height,
                scale=self._scale,
                png=slide_png,
                resources=resources,
                raster_pngs=raster_pngs,
            )
        finally:
            iframe.remove()

    async def _ensure_rasteriser(self, idoc: Any, iwin: Any) -> bool:
        """Make ``domtoimage`` available inside the slide document, injecting
        dom-to-image-more from the configured URL if it isn't already there."""
        from js import Promise

        if getattr(iwin, "domtoimage", None) is not None:
            return True
        url = self._raster_library_url
        if url is None:
            from js import window

            url = getattr(window, "__domoxml_raster_url", None)
        if not url:
            return False
        script = idoc.createElement("script")
        script.src = url
        loaded = Promise.new(
            lambda resolve, _reject: setattr(script, "onload", lambda _event: resolve(None))
        )
        idoc.head.appendChild(script)
        await loaded
        return getattr(iwin, "domtoimage", None) is not None

    async def _rasterise_region(
        self, iwin: Any, root: Any, width: float, height: float
    ) -> bytes | None:
        """PNG bytes for ``root`` at the session scale, via dom-to-image-more — the one
        raster entry point, so the library stays swappable."""
        from js import Object
        from pyodide.ffi import to_js

        options = to_js(
            {"width": width, "height": height, "scale": self._scale},
            dict_converter=Object.fromEntries,
        )
        try:
            blob = await iwin.domtoimage.toBlob(root, options)
            if blob is None:
                return None
            buffer = await blob.arrayBuffer()
            return bytes(buffer.to_py())
        except Exception:
            return None  # rasterisation is best-effort; extraction degrades, never blocks

    async def _rasterise_node(
        self,
        idoc: Any,
        iwin: Any,
        index: int,
        bounds: tuple[float, float, float, float],
        node: Any,
    ) -> bytes | None:
        """Rasterise one captured node the way the server path does: only that node's
        paint, inside its server-computed raster bounds (which include effect
        overflow). A deep clone is staged at its bounds-relative offset in a clean
        container, and dom-to-image-more clones/inlines/rasterises the stage."""
        src = idoc.querySelector(f'[data-domoxml-capture-index="{index}"]')
        if src is None:
            return None
        bound_x, bound_y, bound_w, bound_h = bounds
        stage = idoc.createElement("div")
        stage.setAttribute(
            "style",
            f"position:absolute;left:0;top:0;width:{bound_w}px;height:{bound_h}px;"
            "overflow:hidden;background:transparent;margin:0;padding:0;",
        )
        clone = src.cloneNode(True)
        clone.style.position = "absolute"
        clone.style.left = f"{node.x - bound_x}px"
        clone.style.top = f"{node.y - bound_y}px"
        clone.style.margin = "0"
        stage.appendChild(clone)
        idoc.body.appendChild(stage)
        try:
            return await self._rasterise_region(iwin, stage, bound_w, bound_h)
        finally:
            stage.remove()
