"""The ``Presentation`` — author a deck from per-slide HTML, render to editable OOXML."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Self

from domoxml.core.ir import extract_slide
from domoxml.core.render import BrowserSession, RenderedSlide, compose_page
from domoxml.core.units import pixels
from domoxml.slides import build_pptx
from domoxml.types import (
    CoverageReport,
    OutputFormat,
    RenderResult,
    SizeSpec,
    Slide,
    SlideSize,
    Theme,
)


class Presentation:
    """A deck of HTML-authored slides that renders to an editable ``.pptx`` (+ PNG).

    Build it up, optionally edit ``slides`` in place, then ``render`` it::

        deck = Presentation(size=SlideSize.WIDE_16_9)
        deck.add(Slide(html="<h1>Hello</h1>"))
        result = deck.render({OutputFormat.PPTX, OutputFormat.PNG})

    ``PPTX`` and ``PNG`` are implemented; ``HTML`` (normalized) is not yet wired.
    """

    def __init__(
        self,
        *,
        theme: Theme | None = None,
        size: SizeSpec = SlideSize.WIDE_16_9,
        css: str | None = None,
    ) -> None:
        self.theme: Theme = theme or Theme()
        self.size: SizeSpec = size
        self.css: str | None = css
        self.slides: list[Slide] = []

    def add(self, slide: Slide) -> Self:
        """Append a slide and return ``self`` (chainable)."""
        self.slides.append(slide)
        return self

    def render(
        self, formats: set[OutputFormat], *, indices: set[int] | None = None
    ) -> RenderResult:
        """Render the deck. ``indices`` limits work to specific slides (live preview)."""
        return asyncio.run(self.arender(formats, indices=indices))

    async def arender(
        self,
        formats: set[OutputFormat],
        *,
        indices: set[int] | None = None,
    ) -> RenderResult:
        """Async variant of :meth:`render`."""
        if OutputFormat.HTML in formats:
            raise NotImplementedError("HTML output is not implemented yet")

        needs_render = bool(formats & {OutputFormat.PNG, OutputFormat.PPTX})
        rendered = await self._render(indices) if needs_render else []

        pngs = tuple(slide.png for slide in rendered) if OutputFormat.PNG in formats else ()
        pptx = (
            build_pptx([extract_slide(slide) for slide in rendered])
            if OutputFormat.PPTX in formats
            else None
        )
        return RenderResult(
            pptx=pptx, pngs=pngs, html=None, coverage=CoverageReport(items=()), warnings=()
        )

    def save_pptx(self, path: Path) -> None:
        """Render and write the editable ``.pptx`` to ``path``."""
        result = self.render({OutputFormat.PPTX})
        if result.pptx is None:  # pragma: no cover - render always sets it when requested
            raise RuntimeError("PPTX render produced no output")
        path.write_bytes(result.pptx)

    def save_png(self, directory: Path) -> None:
        """Render and write one PNG per slide into ``directory`` (``slide-NN.png``)."""
        result = self.render({OutputFormat.PNG})
        directory.mkdir(parents=True, exist_ok=True)
        for index, png in enumerate(result.pngs, start=1):
            (directory / f"slide-{index:02d}.png").write_bytes(png)

    async def _render(self, indices: set[int] | None) -> list[RenderedSlide]:
        if indices is None:
            chosen = self.slides
        else:
            invalid = sorted(i for i in indices if i not in range(len(self.slides)))
            if invalid:
                raise IndexError(f"slide indices out of range: {invalid}")
            chosen = [self.slides[i] for i in sorted(indices)]

        rendered: list[RenderedSlide] = []
        async with BrowserSession() as session:
            for slide in chosen:
                width, height = pixels(slide.size or self.size)
                page = compose_page(
                    slide.html, css=self.css, theme=self.theme, width_px=width, height_px=height
                )
                rendered.append(await session.render(page, width=width, height=height))
        return rendered
