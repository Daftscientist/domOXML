"""Web facade — domOXML running entirely in the browser (Pyodide + Takumi).

One async API for the web app, with no browser-DOM capture anywhere:

- :func:`apreview` renders one slide's HTML to a PNG through Takumi
  (``takumi-js``), for the editor's live preview and the slideshow viewer.
- :func:`aconvert` turns per-slide HTML fragments into a ``.pptx`` whose
  layout comes from Takumi's paint tree (``takumi-paint``), never from the
  host page's DOM. Simple fills and text become editable native objects;
  anything unsupported fails closed to one slide-owned raster, exactly as
  on desktop.
- :func:`aread_deck` reads a ``.pptx`` back into per-slide HTML plus the
  deck size and per-slide transitions, so an uploaded deck opens in the
  same editor and is edited by editing its HTML.

Under CPython the same functions work through the Node Takumi bridge, which
is how the web build is smoke-tested outside a browser.
"""

from __future__ import annotations

import base64
import sys
from collections.abc import Sequence
from typing import Any

from domoxml.core.ir.model import SlideTransition
from domoxml.core.render import compose_page
from domoxml.core.render.takumi_backend import TakumiSession
from domoxml.core.roundtrip import inline_assets
from domoxml.core.units import emu_to_px
from domoxml.presentation import Presentation
from domoxml.slides import read_pptx_result
from domoxml.types import CustomSize, OutputFormat, Slide, Theme

__all__ = ["aconvert", "apreview", "aread_deck", "environment"]


def environment() -> str:
    """``"browser"`` under a browser runtime (Pyodide), ``"server"`` under CPython."""
    return "browser" if sys.platform == "emscripten" else "server"


def _transition_from_dict(raw: dict[str, Any] | None) -> SlideTransition | None:
    if not raw:
        return None
    kind = str(raw.get("type") or "none")
    if kind == "none":
        return None
    return SlideTransition(
        type=kind,  # type: ignore[arg-type]
        duration_ms=raw.get("duration_ms"),
        direction=raw.get("direction"),
    )


def _transition_to_dict(transition: SlideTransition | None) -> dict[str, Any] | None:
    if transition is None:
        return None
    return {
        "type": transition.type,
        "duration_ms": transition.duration_ms,
        "direction": transition.direction,
    }


async def apreview(
    html: str,
    *,
    width: int,
    height: int,
    css: str | None = None,
    theme: Theme | None = None,
) -> bytes:
    """Render one slide fragment to PNG bytes via Takumi (preview/viewer path)."""
    page = compose_page(
        html, css=css, theme=theme or Theme(), width_px=width, height_px=height
    )
    async with TakumiSession() as session:
        rendered = await session.render(page, width=width, height=height)
    return rendered.png


async def aconvert(
    fragments: Sequence[str],
    *,
    width: int,
    height: int,
    css: str | None = None,
    transitions: Sequence[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Convert slide HTML fragments (at ``width`` x ``height`` CSS px) into a deck.

    Returns a JSON-friendly dict: the ``.pptx`` as base64, plus the coverage
    items and warnings from the conversion.
    """
    deck = Presentation(
        size=CustomSize(width_in=width / 96, height_in=height / 96),
        css=css,
        render_engine="takumi",
        transitions=[_transition_from_dict(t) for t in transitions or ()],
    )
    for fragment in fragments:
        deck.add(Slide(html=fragment))
    result = await deck.arender({OutputFormat.PPTX})
    if result.pptx is None:
        raise RuntimeError("conversion produced no PPTX")
    return {
        "pptx_b64": base64.b64encode(result.pptx).decode("ascii"),
        "coverage": [item.model_dump(mode="json") for item in result.coverage.items],
        "warnings": [w.model_dump(mode="json") for w in result.warnings],
    }


async def aread_deck(data: bytes) -> dict[str, Any]:
    """Read ``.pptx`` bytes into per-slide HTML, deck size and transitions.

    The HTML has its assets inlined (data URIs), so the viewer can render it
    through Takumi without any external fetches, and the user edits the deck
    by editing this HTML.
    """
    presentation = Presentation.from_pptx(data)
    inlined = inline_assets(presentation)
    irs = read_pptx_result(data).slides
    slides: list[dict[str, Any]] = []
    for index, slide in enumerate(inlined.slides):
        transition = irs[index].transition if index < len(irs) else None
        slides.append(
            {"html": slide.html, "transition": _transition_to_dict(transition)}
        )
    if irs:
        width_px = emu_to_px(irs[0].width)
        height_px = emu_to_px(irs[0].height)
    elif inlined.slides:
        width_px = inlined.slides[0].width_px
        height_px = inlined.slides[0].height_px
    else:
        width_px, height_px = 1280, 720
    return {
        "width_px": width_px,
        "height_px": height_px,
        "css": inlined.css,
        "slides": slides,
    }
