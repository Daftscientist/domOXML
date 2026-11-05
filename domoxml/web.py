"""Web facade — domOXML running entirely in the browser (Pyodide).

One async API for the web app, with two conversion paths:

- :func:`aconvert` turns per-slide HTML fragments into a ``.pptx`` whose
  layout comes from Takumi's paint tree (``takumi-paint``). Simple fills
  and text become editable native objects; anything unsupported fails
  closed to one slide-owned raster, exactly as on desktop.
- The host-capture path (:func:`capture_pages`, :func:`capture_plan`,
  :func:`aconvert_captured`) converts from layout the host page's own
  browser captured in an offscreen iframe — the shared snapshot payload
  the desktop Chromium path evaluates — so CSS the browser supports
  converts even where Takumi's parser cannot. The host rasterises the
  isolated nodes the extractor plans (the web build uses Takumi for
  those pixels); extraction, font resolution and emission are the
  desktop code, fed pre-rendered slides.
- :func:`aread_deck` reads a ``.pptx`` back into per-slide HTML plus the
  deck size and per-slide transitions, so an uploaded deck opens in the
  same editor and is edited by editing its HTML.

Under CPython the Takumi functions work through the Node Takumi bridge,
which is how the web build is smoke-tested outside a browser.
"""

from __future__ import annotations

import base64
import sys
from collections.abc import Sequence
from typing import Any

from domoxml.core.ir.model import SlideTransition
from domoxml.core.render import compose_page
from domoxml.core.render.host import (
    RECORDER_JS,
    RESOURCES_JS,
    SNAPSHOT_JS,
    build_slide,
    plan_capture,
)
from domoxml.core.render.takumi_backend import TakumiSession
from domoxml.core.roundtrip import inline_assets
from domoxml.core.units import emu_to_px
from domoxml.presentation import Presentation
from domoxml.slides import read_pptx_result
from domoxml.types import CustomSize, OutputFormat, Slide, Theme

__all__ = [
    "aconvert",
    "aconvert_captured",
    "apreview",
    "aread_deck",
    "capture_pages",
    "capture_plan",
    "environment",
]


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
    return await _convert_result(deck)


async def _convert_result(deck: Presentation) -> dict[str, Any]:
    result = await deck.arender({OutputFormat.PPTX})
    if result.pptx is None:
        raise RuntimeError("conversion produced no PPTX")
    return {
        "pptx_b64": base64.b64encode(result.pptx).decode("ascii"),
        "coverage": [item.model_dump(mode="json") for item in result.coverage.items],
        "warnings": [w.model_dump(mode="json") for w in result.warnings],
    }


def capture_pages(
    fragments: Sequence[str],
    *,
    width: int,
    height: int,
    css: str | None = None,
) -> dict[str, Any]:
    """Compose the full slide pages for host capture, plus the JavaScript
    payloads the host evaluates in the capture document (the shared
    snapshot payload, the resources collector, the canvas recorder)."""
    theme = Theme()
    return {
        "pages": [
            compose_page(
                fragment, css=css, theme=theme, width_px=width, height_px=height
            )
            for fragment in fragments
        ],
        "snapshot_js": SNAPSHOT_JS,
        "resources_js": RESOURCES_JS,
        "recorder_js": RECORDER_JS,
    }


def capture_plan(
    raw: Sequence[dict[str, Any]], *, width: int, height: int
) -> dict[str, Any]:
    """Raster planning for one host-captured slide (see
    :func:`domoxml.core.render.host.plan_capture`)."""
    return plan_capture(raw, width=width, height=height)


async def aconvert_captured(
    fragments: Sequence[str],
    captures: Sequence[dict[str, Any]],
    *,
    width: int,
    height: int,
    css: str | None = None,
    transitions: Sequence[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Convert host-captured slides into a ``.pptx``.

    ``captures`` aligns with ``fragments``; each entry carries the raw
    snapshot (``raw``), the page's data: resources (``resources``), the
    full-slide PNG (``png_b64``), isolated-node PNGs keyed by snapshot
    index (``rasters``) and, per backdrop node, a sharp full-slide render
    taken with that node hidden (``backdrop_sharp``). PNG payloads are
    base64. Extraction and emission are the desktop pipeline's, fed the
    assembled pre-rendered slides.
    """
    if len(captures) != len(fragments):
        raise ValueError(
            f"got {len(captures)} captures for {len(fragments)} fragments"
        )
    slides = [
        build_slide(
            capture["raw"],
            width=width,
            height=height,
            scale=1.0,
            png_b64=capture.get("png_b64"),
            resources_b64=capture.get("resources"),
            raster_pngs_b64={
                int(index): payload
                for index, payload in (capture.get("rasters") or {}).items()
            },
            backdrop_sharp_b64={
                int(index): payload
                for index, payload in (capture.get("backdrop_sharp") or {}).items()
            },
        )
        for capture in captures
    ]
    deck = Presentation(
        size=CustomSize(width_in=width / 96, height_in=height / 96),
        css=css,
        transitions=[_transition_from_dict(t) for t in transitions or ()],
        rendered_slides=slides,
    )
    for fragment in fragments:
        deck.add(Slide(html=fragment))
    return await _convert_result(deck)


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
