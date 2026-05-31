"""Headless-Chromium rendering via Playwright: rasterise a page and capture its layout."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

from playwright.async_api import Browser, Playwright, Route, async_playwright
from pydantic import BaseModel, ConfigDict, Field

# Walks the rendered DOM and, per element, captures its box, trimmed direct text, the
# computed styles the extractor needs, and enough structure (index/parent) to let the
# extractor rasterise an element together with its subtree. This is the raw material.
_SNAPSHOT_JS = """
() => {
  const pick = (cs) => ({
    color: cs.color, backgroundColor: cs.backgroundColor, backgroundImage: cs.backgroundImage,
    fontSize: cs.fontSize, fontFamily: cs.fontFamily,
    fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
    textAlign: cs.textAlign, lineHeight: cs.lineHeight,
    borderRadius: cs.borderRadius, opacity: cs.opacity,
    boxShadow: cs.boxShadow, filter: cs.filter,
    mixBlendMode: cs.mixBlendMode, backdropFilter: cs.backdropFilter,
    clipPath: cs.clipPath, transform: cs.transform,
    borderTopWidth: cs.borderTopWidth, borderTopStyle: cs.borderTopStyle,
    borderTopColor: cs.borderTopColor,
    borderRightWidth: cs.borderRightWidth, borderRightStyle: cs.borderRightStyle,
    borderRightColor: cs.borderRightColor,
    borderBottomWidth: cs.borderBottomWidth, borderBottomStyle: cs.borderBottomStyle,
    borderBottomColor: cs.borderBottomColor,
    borderLeftWidth: cs.borderLeftWidth, borderLeftStyle: cs.borderLeftStyle,
    borderLeftColor: cs.borderLeftColor,
  });
  const out = [];
  const walk = (el, parent) => {
    const r = el.getBoundingClientRect();
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join('').trim();
    const index = out.length;
    out.push({
      tag: el.tagName.toLowerCase(),
      x: r.x, y: r.y, width: r.width, height: r.height,
      text, index, parent,
      src: el.currentSrc || el.getAttribute('src') || '',
      styles: pick(getComputedStyle(el)),
    });
    for (const child of el.children) walk(child, index);
  };
  walk(document.body, -1);
  return out;
}
"""

_CAPTURED_RESOURCE_TYPES = frozenset({"image", "font"})


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
                await route.continue_()

        try:
            page = await context.new_page()
            await page.route("**/*", _capture)
            await page.set_content(html, wait_until="load")
            await page.evaluate("() => document.fonts.ready.then(() => true)")
            png = await page.screenshot(type="png")
            raw: list[dict[str, Any]] = await page.evaluate(_SNAPSHOT_JS)
            nodes = tuple(RenderedNode.model_validate(node) for node in raw)
            return RenderedSlide(
                png=png,
                width=width,
                height=height,
                scale=self._scale,
                nodes=nodes,
                resources=resources,
            )
        finally:
            await context.close()
