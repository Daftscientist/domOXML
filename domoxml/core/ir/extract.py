"""Turn a captured :class:`RenderedSlide` into the normalized :class:`SlideIR`."""

from __future__ import annotations

from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, TextRun
from domoxml.core.ir.parse import is_bold, parse_color, parse_length_px
from domoxml.core.render.browser import RenderedNode, RenderedSlide
from domoxml.core.units import px_to_emu, px_to_pt

_DEFAULT_TEXT_COLOR = Rgba(r=0, g=0, b=0)


def _text_run(node: RenderedNode) -> TextRun | None:
    if not node.text:
        return None
    styles = node.styles
    return TextRun(
        text=node.text,
        font_family=(styles.get("fontFamily") or "sans-serif").split(",")[0].strip().strip("'\""),
        size_pt=px_to_pt(parse_length_px(styles.get("fontSize")) or 16.0),
        bold=is_bold(styles.get("fontWeight")),
        italic=styles.get("fontStyle", "normal") == "italic",
        color=parse_color(styles.get("color")) or _DEFAULT_TEXT_COLOR,
        align=styles.get("textAlign") or "left",
    )


def _shape(node: RenderedNode) -> ShapeNode:
    background = parse_color(node.styles.get("backgroundColor"))
    fill = background if background is not None and background.a > 0 else None
    try:
        opacity = float(node.styles.get("opacity", "1"))
    except ValueError:
        opacity = 1.0
    return ShapeNode(
        box=Box(
            x=px_to_emu(node.x),
            y=px_to_emu(node.y),
            width=px_to_emu(node.width),
            height=px_to_emu(node.height),
        ),
        fill=fill,
        corner_radius_emu=px_to_emu(parse_length_px(node.styles.get("borderRadius"))),
        opacity=max(0.0, min(1.0, opacity)),
        text=_text_run(node),
    )


def extract_slide(rendered: RenderedSlide) -> SlideIR:
    """Map every captured node to an IR shape, preserving stacking (DOM) order."""
    return SlideIR(
        width=px_to_emu(rendered.width),
        height=px_to_emu(rendered.height),
        shapes=tuple(_shape(node) for node in rendered.nodes),
    )
