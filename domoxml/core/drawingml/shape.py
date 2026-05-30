"""Render an IR :class:`ShapeNode` to a DrawingML/PresentationML ``<p:sp>`` element."""

from __future__ import annotations

from xml.sax.saxutils import escape

from domoxml.core.ir.model import Rgba, ShapeNode, TextRun

_ALIGN_TO_OOXML = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}


def _attr(value: str) -> str:
    """Escape a string for use inside an XML attribute (double-quoted)."""
    return escape(value, {'"': "&quot;"})


def _solid_fill(color: Rgba) -> str:
    alpha = "" if color.a >= 1.0 else f'<a:alpha val="{round(color.a * 100000)}"/>'
    return f'<a:solidFill><a:srgbClr val="{color.hex}">{alpha}</a:srgbClr></a:solidFill>'


def _run(run: TextRun) -> str:
    rpr = (
        f'<a:rPr lang="en-US" sz="{round(run.size_pt * 100)}" '
        f'b="{1 if run.bold else 0}" i="{1 if run.italic else 0}" dirty="0">'
        f'{_solid_fill(run.color)}<a:latin typeface="{_attr(run.font_family)}"/></a:rPr>'
    )
    return f"<a:r>{rpr}<a:t>{escape(run.text)}</a:t></a:r>"


def _text_body(run: TextRun | None) -> str:
    if run is None:
        return ""
    align = _ALIGN_TO_OOXML.get(run.align, "l")
    return (
        '<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>'
        f'<a:p><a:pPr algn="{align}"/>{_run(run)}</a:p></p:txBody>'
    )


def shape_xml(node: ShapeNode, *, shape_id: int) -> str:
    """Build the ``<p:sp>`` for one shape. ``shape_id`` must be unique within the slide."""
    geom = "roundRect" if node.corner_radius_emu > 0 else "rect"
    fill = _solid_fill(node.fill) if node.fill is not None else "<a:noFill/>"
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Shape {shape_id}"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/></a:xfrm>'
        f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>{fill}</p:spPr>'
        f"{_text_body(node.text)}</p:sp>"
    )
