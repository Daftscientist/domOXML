"""The ``Presentation`` — author a deck from per-slide HTML, render to editable OOXML."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from domoxml.types import (
    OutputFormat,
    RenderResult,
    SizeSpec,
    Slide,
    SlideSize,
    Theme,
)


class Presentation:
    """A deck of HTML-authored slides that renders to an editable ``.pptx`` (+ PNG, HTML).

    Build it up, optionally edit ``slides`` in place, then ``render`` it to an immutable
    :class:`~domoxml.types.RenderResult`::

        deck = Presentation(size=SlideSize.WIDE_16_9)
        deck.add(Slide(html="<h1>Hello</h1>"))
        result = deck.render({OutputFormat.PPTX})
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
        self,
        formats: set[OutputFormat],
        *,
        indices: set[int] | None = None,
    ) -> RenderResult:
        """Render the deck. ``indices`` limits work to specific slides (live preview)."""
        raise NotImplementedError

    async def arender(
        self,
        formats: set[OutputFormat],
        *,
        indices: set[int] | None = None,
    ) -> RenderResult:
        """Async variant of :meth:`render`."""
        raise NotImplementedError

    def save_pptx(self, path: Path) -> None:
        """Render and write the editable ``.pptx`` to ``path``."""
        raise NotImplementedError

    def save_png(self, directory: Path) -> None:
        """Render and write one PNG per slide into ``directory``."""
        raise NotImplementedError
