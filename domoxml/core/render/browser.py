"""Headless-Chromium rendering via Playwright: rasterise a page and capture its layout."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

from playwright.async_api import Browser, Playwright, async_playwright
from pydantic import BaseModel, ConfigDict, Field

# Walks the rendered DOM and, per element, captures its box, trimmed direct text, and a
# subset of computed styles. This is the raw material the extractor turns into the IR.
_SNAPSHOT_JS = """
() => {
  const pick = (cs) => ({
    color: cs.color, backgroundColor: cs.backgroundColor,
    fontSize: cs.fontSize, fontFamily: cs.fontFamily,
    fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
    textAlign: cs.textAlign, lineHeight: cs.lineHeight,
    borderRadius: cs.borderRadius, opacity: cs.opacity,
  });
  const out = [];
  const walk = (el) => {
    const r = el.getBoundingClientRect();
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join('').trim();
    out.push({
      tag: el.tagName.toLowerCase(),
      x: r.x, y: r.y, width: r.width, height: r.height,
      text, styles: pick(getComputedStyle(el)),
    });
    for (const child of el.children) walk(child);
  };
  walk(document.body);
  return out;
}
"""


class RenderedNode(BaseModel):
    """One element as Chromium laid it out: box (CSS px), direct text, computed styles."""

    model_config = ConfigDict(frozen=True)

    tag: str
    x: float
    y: float
    width: float
    height: float
    text: str = ""
    styles: dict[str, str] = Field(default_factory=dict)


class RenderedSlide(BaseModel):
    """The render of one slide: its PNG plus the captured layout tree."""

    model_config = ConfigDict(frozen=True)

    png: bytes
    width: int
    height: int
    nodes: tuple[RenderedNode, ...]


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
        self._browser = await self._playwright.chromium.launch(headless=True)
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
        """Render ``html`` at ``width`` x ``height`` CSS px → PNG + captured layout."""
        if self._browser is None:
            raise RuntimeError("BrowserSession must be entered via 'async with' before render()")
        context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=self._scale,
        )
        try:
            page = await context.new_page()
            await page.set_content(html, wait_until="load")
            await page.evaluate("() => document.fonts.ready.then(() => true)")
            png = await page.screenshot(type="png")
            raw: list[dict[str, Any]] = await page.evaluate(_SNAPSHOT_JS)
            nodes = tuple(RenderedNode.model_validate(node) for node in raw)
            return RenderedSlide(png=png, width=width, height=height, nodes=nodes)
        finally:
            await context.close()
