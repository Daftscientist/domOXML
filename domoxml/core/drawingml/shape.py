"""Render an IR :class:`ShapeNode` to a DrawingML/PresentationML ``<p:sp>`` element."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from xml.sax.saxutils import escape

from domoxml.core.ir.model import (
    Fill,
    GradientFill,
    Hyperlink,
    Line,
    PatternFill,
    Rgba,
    Shadow,
    ShapeNode,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)

# A resolver the package writer supplies: given a run hyperlink, return its slide-relationship id
# (the writer owns the rels), or ``None`` when no rel was registered.
type HyperlinkRid = Callable[[Hyperlink], str | None]

# ``a:hlinkClick action`` for an in-deck slide jump (ECMA-376 §19.5.46 / ST_HyperlinkAction).
_SLIDE_JUMP_ACTION = "ppaction://hlinksldjump"

_ALIGN_TO_OOXML = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}
# Maps the IR DashStyle literal onto a:prstDash preset names (ECMA-376 §20.1.10.49).
_DASH_TO_OOXML = {
    "solid": "solid",
    "dash": "dash",
    "dot": "sysDot",
    "dashDot": "dashDot",
    "lgDash": "lgDash",
    "sysDash": "sysDash",
}


def _attr(value: str) -> str:
    """Escape a string for use inside an XML attribute (double-quoted)."""
    return escape(value, {'"': "&quot;"})


def _srgb(color: Rgba, *, opacity: float = 1.0) -> str:
    alpha_val = color.a * opacity
    alpha = "" if alpha_val >= 1.0 else f'<a:alpha val="{round(alpha_val * 100000)}"/>'
    return f'<a:srgbClr val="{color.hex}">{alpha}</a:srgbClr>'


def _solid_fill(color: Rgba, *, opacity: float = 1.0) -> str:
    return f"<a:solidFill>{_srgb(color, opacity=opacity)}</a:solidFill>"


def _gradient_fill(gradient: GradientFill, *, opacity: float) -> str:
    stops = "".join(
        f'<a:gs pos="{round(stop.pos * 100000)}">{_srgb(stop.color, opacity=opacity)}</a:gs>'
        for stop in gradient.stops
    )
    gs_lst = f"<a:gsLst>{stops}</a:gsLst>"
    if gradient.radial:
        path = (
            '<a:path path="circle"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path>'
        )
        return f"<a:gradFill>{gs_lst}{path}</a:gradFill>"
    # CSS angle (0 = up, clockwise) → OOXML angle (0 = right, clockwise), in 60000ths.
    ooxml_angle = round(((gradient.angle_deg + 270.0) % 360.0) * 60000)
    return f'<a:gradFill>{gs_lst}<a:lin ang="{ooxml_angle}" scaled="1"/></a:gradFill>'


def _blip_fill(blip_rid: str) -> str:
    return (
        f'<a:blipFill><a:blip r:embed="{blip_rid}"/>'
        "<a:stretch><a:fillRect/></a:stretch></a:blipFill>"
    )


def _fill_xml(fill: Fill | None, *, opacity: float, blip_rid: str | None) -> str:
    if fill is None:
        return "<a:noFill/>"
    if isinstance(fill, SolidFill):
        return _solid_fill(fill.color, opacity=opacity)
    if isinstance(fill, GradientFill):
        return _gradient_fill(fill, opacity=opacity)
    if isinstance(fill, PatternFill):
        # TODO(coverage): emit a:pattFill. No writer yet, so warn and fall back to no-fill
        # rather than drop silently (no-silent-drop policy).
        warnings.warn(
            "pattern fill has no PresentationML writer yet; emitted as no-fill", stacklevel=2
        )
        return "<a:noFill/>"
    # PictureFill: a blip fill if the package writer assigned a media relationship, else nothing.
    return _blip_fill(blip_rid) if blip_rid is not None else "<a:noFill/>"


def _line_xml(line: Line | None) -> str:
    if line is None:
        return ""
    dash = _DASH_TO_OOXML.get(line.dash, "solid")
    return f'<a:ln w="{line.width_emu}">{_solid_fill(line.color)}<a:prstDash val="{dash}"/></a:ln>'


def _effect_xml(shadow: Shadow | None) -> str:
    if shadow is None:
        return ""
    tag = "a:innerShdw" if shadow.inset else "a:outerShdw"
    direction = round((shadow.direction_deg % 360.0) * 60000)
    return (
        f'<a:effectLst><{tag} blurRad="{shadow.blur_emu}" dist="{shadow.distance_emu}" '
        f'dir="{direction}">{_srgb(shadow.color)}</{tag}></a:effectLst>'
    )


def _geometry_xml(node: ShapeNode) -> str:
    if node.geom == "roundRect" and node.corner_radius_emu > 0:
        shorter = max(1, min(node.box.width, node.box.height))
        adj = min(50000, round(node.corner_radius_emu / shorter * 100000))
        return (
            '<a:prstGeom prst="roundRect"><a:avLst>'
            f'<a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
        )
    return f'<a:prstGeom prst="{node.geom}"><a:avLst/></a:prstGeom>'


def _underline_attr(underline: bool | str) -> str:
    if underline is False:
        return ""
    token = "sng" if underline is True else underline
    return f' u="{_attr(token)}"'


def _hyperlink_xml(hyperlink: Hyperlink | None, rid: str | None) -> str:
    """An ``a:hlinkClick`` for a run, or ``""``. External links carry the rel id; slide jumps
    carry both the jump action and the rel id pointing at the target slide part."""
    if hyperlink is None:
        return ""
    embed = f' r:id="{rid}"' if rid is not None else ' r:id=""'
    if hyperlink.slide_index is not None:
        return f'<a:hlinkClick{embed} action="{_SLIDE_JUMP_ACTION}"/>'
    return f"<a:hlinkClick{embed}/>"


def _run(run: TextRun, hyperlink_rid: HyperlinkRid) -> str:
    rid = hyperlink_rid(run.hyperlink) if run.hyperlink is not None else None
    decorations = _underline_attr(run.underline)
    if run.strike:
        decorations += ' strike="sngStrike"'
    if run.caps is not None:
        decorations += f' cap="{"all" if run.caps == "all" else "small"}"'
    if run.letter_spacing_pt:
        # a:rPr spc is in 1/100 pt (ECMA-376 §21.1.2.3.9), may be negative.
        decorations += f' spc="{round(run.letter_spacing_pt * 100)}"'
    rpr = (
        f'<a:rPr lang="en-US" sz="{round(run.size_pt * 100)}" '
        f'b="{1 if run.bold else 0}" i="{1 if run.italic else 0}"{decorations} dirty="0">'
        f"{_solid_fill(run.color)}"
        f"{_hyperlink_xml(run.hyperlink, rid)}"
        f'<a:latin typeface="{_attr(run.font_family)}"/></a:rPr>'
    )
    return f"<a:r>{rpr}<a:t>{escape(run.text)}</a:t></a:r>"


def _paragraph(paragraph: TextParagraph, hyperlink_rid: HyperlinkRid) -> str:
    align = _ALIGN_TO_OOXML.get(paragraph.align, "l")
    runs = "".join(_run(run, hyperlink_rid) for run in paragraph.runs)
    return f'<a:p><a:pPr algn="{align}"/>{runs}</a:p>'


def _text_body(body: TextBody | None, hyperlink_rid: HyperlinkRid) -> str:
    if body is None:
        return ""
    # anchor="t": match HTML block flow (text at the top of the box). Office centres shape
    # text vertically by default, which sits lower than the source.
    paragraphs = "".join(_paragraph(paragraph, hyperlink_rid) for paragraph in body.paragraphs)
    return (
        '<p:txBody><a:bodyPr wrap="square" anchor="t" lIns="0" rIns="0" tIns="0" bIns="0">'
        f"<a:normAutofit/></a:bodyPr><a:lstStyle/>{paragraphs}</p:txBody>"
    )


def _no_hyperlink_rid(_hyperlink: Hyperlink) -> str | None:
    return None


def shape_xml(
    node: ShapeNode,
    *,
    shape_id: int,
    blip_rid: str | None = None,
    hyperlink_rid: HyperlinkRid = _no_hyperlink_rid,
) -> str:
    """Build the ``<p:sp>`` for one shape. ``shape_id`` must be unique within the slide.

    ``blip_rid`` is the slide-relationship id for this shape's picture fill, if any (assigned
    by the package writer, which owns the media parts). ``hyperlink_rid`` resolves a run
    hyperlink to its slide-relationship id (also assigned by the package writer).
    """
    fill = _fill_xml(node.fill, opacity=node.opacity, blip_rid=blip_rid)
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Shape {shape_id}"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/></a:xfrm>'
        f"{_geometry_xml(node)}{fill}{_line_xml(node.line)}{_effect_xml(node.shadow)}</p:spPr>"
        f"{_text_body(node.text, hyperlink_rid)}</p:sp>"
    )
