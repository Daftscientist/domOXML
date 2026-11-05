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

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.extract import extract_slide
from domoxml.core.ir.model import GroupNode, ShapeNode, SlideTransition, TableNode
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
    "normalize_captured",
    "slide_ir",
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


_IR_KINDS = {
    "ShapeNode": "shape",
    "GroupNode": "group",
    "Connector": "connector",
    "TableNode": "table",
    "MediaNode": "media",
    "PreservedNode": "preserved",
}


def _ir_label(node: Any) -> str:
    """A short human label for one IR node: its text, else its kind/geom."""
    text = getattr(node, "text", None)
    if text is not None:
        for paragraph in text.paragraphs:
            joined = "".join(run.text for run in paragraph.runs).strip()
            if joined:
                return joined[:64]
    alt = getattr(node, "alt_text", None)
    if alt:
        return alt[:64]
    if isinstance(node, ShapeNode):
        return node.geom if node.geom != "rect" else "Shape"
    if isinstance(node, GroupNode):
        return "Group"
    if isinstance(node, TableNode):
        rows = len(node.rows)
        cols = len(node.rows[0].cells) if rows else 0
        return f"Table {rows} × {cols}"
    return _IR_KINDS.get(type(node).__name__, "Node")


def _build_captured(capture: dict[str, Any], *, width: int, height: int):
    """Assemble one host capture into a rendered slide (shared by the
    IR derivation and the normaliser, so both see identical input)."""
    return build_slide(
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


def slide_ir(
    capture: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Derive one slide's IR from a host capture, as a display tree.

    Runs the same assembly and extraction the export path uses
    (:func:`domoxml.core.render.host.build_slide` then
    :func:`domoxml.core.ir.extract.extract_slide`) and prunes the result
    to what a tree view needs: kind, label, box in CSS px, whether the
    node carries a portable (raster) fallback, and a DOM path.

    The path locates the source element in the composed page: element
    child indices from ``document.body`` (the snapshot walk's root), so
    the client can map a tree node back to the live preview element.
    It is derived from the node's provenance source index through the
    snapshot's parent chain; nodes without HTML provenance get ``None``.
    """
    rendered = _build_captured(capture, width=width, height=height)
    result = extract_slide(rendered)
    ir = result.slide

    children_of: dict[int, list[int]] = {}
    for rendered_node in rendered.nodes:
        children_of.setdefault(rendered_node.parent, []).append(rendered_node.index)
    paths: dict[int, list[int]] = {}
    for rendered_node in sorted(rendered.nodes, key=lambda n: n.index):
        if rendered_node.parent < 0:
            paths[rendered_node.index] = []
        else:
            siblings = children_of[rendered_node.parent]
            paths[rendered_node.index] = paths[rendered_node.parent] + [
                siblings.index(rendered_node.index)
            ]

    def node_dict(node: Any) -> dict[str, Any]:
        box = getattr(node, "box", None)
        path: list[int] | None = None
        provenance = getattr(node, "provenance", None)
        if provenance is not None and provenance.source_format == "html":
            # Extraction records the snapshot index as "dom:<index>"
            # (domoxml.core.ir.extract._IdentityAllocator).
            raw_id = provenance.source_id.removeprefix("dom:")
            try:
                path = paths.get(int(raw_id))
            except (TypeError, ValueError):
                path = None
        return {
            "kind": _IR_KINDS.get(type(node).__name__, "node"),
            "label": _ir_label(node),
            "box": (
                {
                    "x": round(emu_to_px(box.x)),
                    "y": round(emu_to_px(box.y)),
                    "w": round(emu_to_px(box.width)),
                    "h": round(emu_to_px(box.height)),
                }
                if box is not None
                else None
            ),
            "path": path,
            "fallback": getattr(node, "portable_fallback", None) is not None,
            "children": (
                [node_dict(child) for child in node.children]
                if isinstance(node, GroupNode)
                else []
            ),
        }

    return {
        "width_px": round(emu_to_px(ir.width)),
        "height_px": round(emu_to_px(ir.height)),
        "tree": [node_dict(node) for node in ir.contents],
        "warnings": [w.model_dump(mode="json") for w in result.warnings],
    }


def normalize_captured(
    capture: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Normalise one captured slide back to canonical domOXML HTML.

    Extraction turns the captured layout into IR; serialising that IR
    with :func:`domoxml.core.html.serialize_canvas` produces the same
    fully geometric fragment form the .pptx read path emits — every
    element absolutely positioned with inline styles — which parses
    straight back to IR with no browser involved. Foreign HTML that
    needed the browser's layout to be understood (flow layout, classes,
    authored CSS) is thereby replaced by its normalised equivalent.

    The returned ``css`` carries only shared assets (in practice
    @font-face rules); layout is inline on every element. Assets are
    inlined as data URIs, as in :func:`aread_deck`.
    """
    rendered = _build_captured(capture, width=width, height=height)
    result = extract_slide(rendered)
    inlined = inline_assets(
        serialize_canvas([result.slide], warnings=tuple(result.warnings))
    )
    slide = inlined.slides[0]
    return {
        "html": slide.html,
        "css": inlined.css,
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
