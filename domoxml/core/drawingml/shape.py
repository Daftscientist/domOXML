"""Render an IR :class:`ShapeNode` to a DrawingML/PresentationML ``<p:sp>`` element."""

from __future__ import annotations

import warnings
from xml.sax.saxutils import escape

from domoxml.core.ir.model import (
    Blur,
    Fill,
    Glow,
    GradientFill,
    Line,
    PatternFill,
    Rgba,
    Shadow,
    ShapeNode,
    SoftEdge,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)

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


def _outer_shadow_xml(shadow: Shadow, node: ShapeNode) -> str:
    """Emit ``a:outerShdw`` with optional sx/sy grow attrs for spread.

    ECMA-376 §20.1.8.55: ``sx``/``sy`` scale the shadow copy as a percentage (100000 = 100%).
    To approximate CSS spread ``s`` on a shape of width ``w`` / height ``h``:
        sx = round((w + 2*s) / w * 100000)
        sy = round((h + 2*s) / h * 100000)
    A warning is emitted when spread > 25% of the shorter shape dimension (approximation
    degrades significantly beyond this range).
    """
    direction = round((shadow.direction_deg % 360.0) * 60000)
    extra = ""
    if shadow.spread_emu != 0 and not shadow.inset:
        w = node.box.width
        h = node.box.height
        s = shadow.spread_emu
        if w > 0 and h > 0:
            sx = round((w + 2 * s) / w * 100_000)
            sy = round((h + 2 * s) / h * 100_000)
            extra = f' sx="{sx}" sy="{sy}"'
            min_dim = min(w, h)
            if abs(s) > min_dim * 0.25:
                warnings.warn(
                    f"box-shadow spread ({s} EMU) > 25% of shape's shorter side "
                    f"({min_dim} EMU); outerShdw sx/sy approximation may be poor",
                    stacklevel=4,
                )
    return (
        f'<a:outerShdw blurRad="{shadow.blur_emu}" dist="{shadow.distance_emu}" '
        f'dir="{direction}"{extra}>{_srgb(shadow.color)}</a:outerShdw>'
    )


def _inner_shadow_xml(shadow: Shadow) -> str:
    """Emit ``a:innerShdw``.

    ``a:innerShdw`` has no grow attribute; spread is approximated by slightly increasing
    ``blurRad`` (which enlarges the visible inset region). This is an honest approximation:
    a warning is always emitted when spread is non-zero.
    """
    direction = round((shadow.direction_deg % 360.0) * 60000)
    blur = shadow.blur_emu
    if shadow.spread_emu != 0:
        # Enlarge blur by spread to approximate choke/grow effect; it's imperfect.
        blur = max(0, blur + shadow.spread_emu)
        warnings.warn(
            "innerShdw has no spread/grow attribute; "
            "spread approximated via blurRad increase (imperfect)",
            stacklevel=4,
        )
    return (
        f'<a:innerShdw blurRad="{blur}" dist="{shadow.distance_emu}" '
        f'dir="{direction}">{_srgb(shadow.color)}</a:innerShdw>'
    )


def _effects_xml(node: ShapeNode) -> str:
    """Emit ``<a:effectLst>`` for all effects on the node, or an empty string."""
    if not node.effects:
        return ""
    parts: list[str] = []
    for effect in node.effects:
        if isinstance(effect, Shadow):
            if effect.inset:
                parts.append(_inner_shadow_xml(effect))
            else:
                parts.append(_outer_shadow_xml(effect, node))
        elif isinstance(effect, Glow):
            parts.append(f'<a:glow rad="{effect.radius_emu}">{_srgb(effect.color)}</a:glow>')
        elif isinstance(effect, Blur):
            parts.append(f'<a:blur rad="{effect.radius_emu}" grow="1"/>')
        elif isinstance(effect, SoftEdge):
            parts.append(f'<a:softEdge rad="{effect.radius_emu}"/>')
        else:
            # Reflection is the remaining union arm.
            parts.append(
                f'<a:reflection blurRad="{effect.blur_emu}" '
                f'dist="{effect.distance_emu}" '
                f'startA="{round(effect.start_alpha * 100_000)}" '
                f'endA="{round(effect.end_alpha * 100_000)}" '
                f'dir="5400000" fadeDir="5400000" sx="100000" sy="-100000" '
                f'ky="0" kx="0" algn="bl" rotWithShape="0"/>'
            )
    if not parts:
        return ""
    return f"<a:effectLst>{''.join(parts)}</a:effectLst>"


def _geometry_xml(node: ShapeNode) -> str:
    if node.geom == "roundRect" and node.corner_radius_emu > 0:
        shorter = max(1, min(node.box.width, node.box.height))
        adj = min(50000, round(node.corner_radius_emu / shorter * 100000))
        return (
            '<a:prstGeom prst="roundRect"><a:avLst>'
            f'<a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
        )
    return f'<a:prstGeom prst="{node.geom}"><a:avLst/></a:prstGeom>'


def _run(run: TextRun) -> str:
    rpr = (
        f'<a:rPr lang="en-US" sz="{round(run.size_pt * 100)}" '
        f'b="{1 if run.bold else 0}" i="{1 if run.italic else 0}" dirty="0">'
        f'{_solid_fill(run.color)}<a:latin typeface="{_attr(run.font_family)}"/></a:rPr>'
    )
    return f"<a:r>{rpr}<a:t>{escape(run.text)}</a:t></a:r>"


def _paragraph(paragraph: TextParagraph) -> str:
    align = _ALIGN_TO_OOXML.get(paragraph.align, "l")
    return f'<a:p><a:pPr algn="{align}"/>{"".join(_run(run) for run in paragraph.runs)}</a:p>'


def _text_body(body: TextBody | None) -> str:
    if body is None:
        return ""
    # anchor="t": match HTML block flow (text at the top of the box). Office centres shape
    # text vertically by default, which sits lower than the source.
    return (
        '<p:txBody><a:bodyPr wrap="square" anchor="t" lIns="0" rIns="0" tIns="0" bIns="0">'
        "<a:normAutofit/></a:bodyPr><a:lstStyle/>"
        f"{''.join(_paragraph(paragraph) for paragraph in body.paragraphs)}</p:txBody>"
    )


def shape_xml(node: ShapeNode, *, shape_id: int, blip_rid: str | None = None) -> str:
    """Build the ``<p:sp>`` for one shape. ``shape_id`` must be unique within the slide.

    ``blip_rid`` is the slide-relationship id for this shape's picture fill, if any (assigned
    by the package writer, which owns the media parts).
    """
    fill = _fill_xml(node.fill, opacity=node.opacity, blip_rid=blip_rid)
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Shape {shape_id}"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/></a:xfrm>'
        f"{_geometry_xml(node)}{fill}{_line_xml(node.line)}{_effects_xml(node)}</p:spPr>"
        f"{_text_body(node.text)}</p:sp>"
    )
