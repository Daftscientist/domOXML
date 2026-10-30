"""Environment-adaptive facade — one entry point, two capture backends.

Callers never branch on the runtime. :func:`open_session` (re-exported from the render
layer) autodetects the environment: under CPython, capture drives a Playwright
Chromium exactly as before; under a browser runtime (Pyodide), capture renders in an
offscreen iframe in the host page and lets the host's own Chromium do the layout.
:func:`aconvert` / :func:`convert` turn slide HTML fragments into a deck, and
:func:`aread_deck` / :func:`read_deck` run the reverse path (``.pptx`` → per-slide
HTML, plus the re-emitted round-tripped deck) — all through the same session factory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from domoxml.core.render.web import (
    _is_browser_runtime,
    capture_slide,
    compose_pptx,
    open_session,
)
from domoxml.core.roundtrip import inline_assets
from domoxml.presentation import Presentation
from domoxml.types import (
    ConversionWarning,
    CoverageItem,
    CustomSize,
    OutputFormat,
    Slide,
    Theme,
)

__all__ = [
    "aconvert",
    "aread_deck",
    "convert",
    "environment",
    "open_session",
    "read_deck",
]


def environment() -> str:
    """``"browser"`` under a browser runtime (Pyodide), ``"server"`` under CPython."""
    return "browser" if _is_browser_runtime() else "server"


async def aconvert(
    fragments: Sequence[str],
    *,
    width: int,
    height: int,
    theme: Theme | None = None,
    css: str | None = None,
    raster_library_url: str | None = None,
) -> tuple[bytes, tuple[CoverageItem, ...], tuple[ConversionWarning, ...]]:
    """Convert slide HTML fragments (one per slide, at ``width`` x ``height`` CSS px)
    into a single ``.pptx``, in whichever runtime this is called from. Returns the deck
    bytes, the coverage items and the conversion warnings."""
    theme = theme or Theme()
    rendered = []
    async with open_session(raster_library_url=raster_library_url) as session:
        for fragment in fragments:
            rendered.append(
                await capture_slide(
                    session, fragment, css=css, theme=theme, width=width, height=height
                )
            )
    return compose_pptx(rendered)


def convert(
    fragments: Sequence[str], **kwargs: Any
) -> tuple[bytes, tuple[CoverageItem, ...], tuple[ConversionWarning, ...]]:
    """Synchronous :func:`aconvert` for CPython callers. In a browser runtime there is
    no way to block on the host page, so this raises there — ``await aconvert(...)`."""
    if _is_browser_runtime():
        raise RuntimeError(
            "convert() cannot block in a browser runtime; await aconvert(...) instead"
        )
    return asyncio.run(aconvert(fragments, **kwargs))


async def aread_deck(data: bytes, *, reemit: bool = True) -> dict[str, Any]:
    """Reverse path: read ``.pptx`` bytes into per-slide HTML (the deterministic
    reverse output), and — unless ``reemit`` is off — the round-tripped ``.pptx``
    re-emitted from that HTML through the same capture/compose path as
    :func:`domoxml.core.roundtrip.render_html_roundtrip`, awaited instead of blocked
    on so it works in a browser runtime too."""
    presentation = Presentation.from_pptx(data)
    display = inline_assets(presentation)
    reemitted: bytes | None = None
    if reemit and presentation.slides:
        inlined = inline_assets(presentation)
        first = inlined.slides[0]
        deck = Presentation(
            css=inlined.css,
            size=CustomSize(width_in=first.width_px / 96, height_in=first.height_px / 96),
        )
        for slide in inlined.slides:
            deck.add(
                Slide(
                    html=slide.html,
                    size=CustomSize(
                        width_in=slide.width_px / 96, height_in=slide.height_px / 96
                    ),
                )
            )
        result = await deck.arender({OutputFormat.PPTX})
        reemitted = result.pptx
    return {
        "slides": presentation.slides,
        "css": presentation.css,
        "assets": presentation.assets,
        "warnings": presentation.warnings,
        "coverage": presentation.coverage,
        "reemitted_pptx": reemitted,
        # Asset-inlined variants for display: the raw reverse output references
        # asset files by relative path, which a single-page host cannot serve.
        "display_slides": display.slides,
        "display_css": display.css,
    }


def read_deck(data: bytes, **kwargs: Any) -> dict[str, Any]:
    """Synchronous :func:`aread_deck` for CPython callers (same browser caveat as
    :func:`convert`)."""
    if _is_browser_runtime():
        raise RuntimeError(
            "read_deck() cannot block in a browser runtime; await aread_deck(...) instead"
        )
    return asyncio.run(aread_deck(data, **kwargs))
