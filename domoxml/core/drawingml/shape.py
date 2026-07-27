"""Render an IR :class:`ShapeNode` to a DrawingML/PresentationML ``<p:sp>`` element."""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from xml.sax.saxutils import escape

from domoxml.core.drawingml.identity import node_identity_xml
from domoxml.core.ir.model import (
    ArcTo,
    Arrowhead,
    Blur,
    Box,
    CharBullet,
    ColorSpec,
    ColorTransform,
    CubicTo,
    CustomGeometry,
    Fill,
    Glow,
    GradientFill,
    GradientStop,
    Hyperlink,
    Line,
    LineTo,
    MoveTo,
    PatternFill,
    PictureFill,
    QuadTo,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SoftEdge,
    SolidFill,
    SrcRect,
    TextBody,
    TextParagraph,
    TextRun,
    ThemeColorRef,
)
from domoxml.core.units import pt_to_emu

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
# a:ln cap attribute values (ECMA-376 §20.1.10.30).
_CAP_TO_OOXML = {"flat": "flat", "round": "rnd", "square": "sq"}
# Join child elements; miter uses ECMA default limit of 800000 (8x width).
_JOIN_OOXML_TAG = {
    "round": "<a:round/>",
    "bevel": "<a:bevel/>",
    "miter": '<a:miter lim="800000"/>',
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


def _powerpoint_gradient_stops(gradient: GradientFill) -> tuple[GradientStop, ...]:
    """Subdivide sRGB stops so PowerPoint's linear-light interpolation tracks CSS."""
    expanded: list[GradientStop] = []
    subdivisions = 8
    for index, (start, end) in enumerate(zip(gradient.stops, gradient.stops[1:], strict=False)):
        for step in range(subdivisions + 1):
            if index > 0 and step == 0:
                continue
            amount = step / subdivisions
            expanded.append(
                GradientStop(
                    pos=start.pos + (end.pos - start.pos) * amount,
                    color=Rgba(
                        r=round(start.color.r + (end.color.r - start.color.r) * amount),
                        g=round(start.color.g + (end.color.g - start.color.g) * amount),
                        b=round(start.color.b + (end.color.b - start.color.b) * amount),
                        a=start.color.a + (end.color.a - start.color.a) * amount,
                    ),
                )
            )
    return tuple(expanded)


def _gradient_fill(gradient: GradientFill, *, opacity: float, box: Box | None = None) -> str:
    gradient_stops = _powerpoint_gradient_stops(gradient) if box is not None else gradient.stops
    stops = "".join(
        f'<a:gs pos="{round(stop.pos * 100000)}">{_srgb(stop.color, opacity=opacity)}</a:gs>'
        for stop in gradient_stops
    )
    gs_lst = f"<a:gsLst>{stops}</a:gsLst>"
    if gradient.radial:
        path = (
            '<a:path path="circle"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path>'
        )
        return f"<a:gradFill>{gs_lst}{path}</a:gradFill>"
    # CSS gradients use the physical box aspect ratio to find their corner endpoints, while
    # DrawingML's scaled angle is measured in normalized shape coordinates. Correct the angle
    # by the shape aspect ratio before serializing it.
    angle_deg = (gradient.angle_deg + 270.0) % 360.0
    if box is not None and box.width > 0 and box.height > 0:
        angle = math.radians(angle_deg)
        angle_deg = (
            math.degrees(math.atan2(math.sin(angle) * box.height, math.cos(angle) * box.width))
            % 360.0
        )
    ooxml_angle = round(angle_deg * 60000)
    return f'<a:gradFill>{gs_lst}<a:lin ang="{ooxml_angle}" scaled="1"/></a:gradFill>'


def _src_rect_xml(crop: SrcRect | None) -> str:
    """Emit ``a:srcRect`` (a crop inset in 1000ths-of-a-percent) or ``""`` when there is none."""
    if crop is None:
        return ""
    attrs = ""
    for name, value in (("l", crop.left), ("t", crop.top), ("r", crop.right), ("b", crop.bottom)):
        if value > 0:
            attrs += f' {name}="{round(value * 100000)}"'
    return f"<a:srcRect{attrs}/>" if attrs else ""


# Office 2016 DrawingML SVG blip extension (vector source alongside the PNG fallback).
_ASVG_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
_ASVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"


def _blip_fill(
    blip_rid: str,
    crop: SrcRect | None = None,
    svg_rid: str | None = None,
    *,
    tag: str = "a:blipFill",
) -> str:
    if svg_rid is not None:
        # Pair the raster PNG (a:blip) with the original SVG so PowerPoint renders the vector
        # at native resolution while the PNG is the downlevel fallback.
        ext = (
            f'<a:ext uri="{_ASVG_URI}">'
            f'<asvg:svgBlip xmlns:asvg="{_ASVG_NS}" r:embed="{svg_rid}"/></a:ext>'
        )
        blip = f'<a:blip r:embed="{blip_rid}"><a:extLst>{ext}</a:extLst></a:blip>'
    else:
        blip = f'<a:blip r:embed="{blip_rid}"/>'
    return f"<{tag}>{blip}{_src_rect_xml(crop)}<a:stretch><a:fillRect/></a:stretch></{tag}>"


# DrawingML colour-transform child tags (value in 1000ths of a percent).
_TRANSFORM_TAG = {
    "lumMod": "lumMod",
    "lumOff": "lumOff",
    "shade": "shade",
    "tint": "tint",
    "alpha": "alpha",
    "satMod": "satMod",
}


def _color_transforms(transforms: tuple[ColorTransform, ...]) -> str:
    return "".join(
        f'<a:{_TRANSFORM_TAG[t.kind]} val="{round(t.value * 100000)}"/>' for t in transforms
    )


def _color_spec_xml(color: ColorSpec) -> str:
    """Emit a colour child (``a:srgbClr`` or ``a:schemeClr``) for a resolved or theme colour."""
    if isinstance(color, ThemeColorRef):
        inner = _color_transforms(color.transforms)
        return f'<a:schemeClr val="{color.slot}">{inner}</a:schemeClr>'
    return _srgb(color)


def _pattern_fill(fill: PatternFill) -> str:
    """Emit ``a:pattFill`` with its preset and foreground/background colours
    (ECMA-376 §20.1.8.40 / ST_PresetPatternVal)."""
    fg = f"<a:fgClr>{_color_spec_xml(fill.fg)}</a:fgClr>"
    bg = f"<a:bgClr>{_color_spec_xml(fill.bg)}</a:bgClr>"
    return f'<a:pattFill prst="{_attr(fill.preset)}">{fg}{bg}</a:pattFill>'


def _fill_xml(
    fill: Fill | None,
    *,
    opacity: float,
    blip_rid: str | None,
    svg_rid: str | None = None,
    box: Box | None = None,
) -> str:
    if fill is None:
        return "<a:noFill/>"
    if isinstance(fill, SolidFill):
        return _solid_fill(fill.color, opacity=opacity)
    if isinstance(fill, GradientFill):
        return _gradient_fill(fill, opacity=opacity, box=box)
    if isinstance(fill, PatternFill):
        return _pattern_fill(fill)
    # PictureFill: a blip fill if the package writer assigned a media relationship, else nothing.
    return _blip_fill(blip_rid, fill.crop, svg_rid) if blip_rid is not None else "<a:noFill/>"


def line_xml(line: Line | None) -> str:
    if line is None:
        return ""
    cap = _CAP_TO_OOXML.get(line.cap, "flat")
    dash = _DASH_TO_OOXML.get(line.dash, "solid")
    join_tag = _JOIN_OOXML_TAG.get(line.join, "<a:round/>")
    fill_xml = (
        _gradient_fill(line.gradient, opacity=1.0)
        if line.gradient is not None
        else _solid_fill(line.color)
    )
    head_xml = _arrowhead_xml("headEnd", line.head) if line.head is not None else ""
    tail_xml = _arrowhead_xml("tailEnd", line.tail) if line.tail is not None else ""
    return (
        f'<a:ln w="{line.width_emu}" cap="{cap}">'
        f"{fill_xml}"
        f'<a:prstDash val="{dash}"/>'
        f"{join_tag}"
        f"{head_xml}{tail_xml}"
        f"</a:ln>"
    )


def _arrowhead_xml(tag: str, arrow: Arrowhead) -> str:
    """Emit ``a:headEnd`` or ``a:tailEnd`` for a line arrowhead decoration."""
    if arrow.type == "none":
        return f'<a:{tag} type="none"/>'
    return f'<a:{tag} type="{arrow.type}" w="{arrow.width}" len="{arrow.length}"/>'


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
        elif isinstance(effect, Reflection):
            parts.append(
                f'<a:reflection blurRad="{effect.blur_emu}" '
                f'dist="{effect.distance_emu}" '
                f'stA="{round(effect.start_alpha * 100_000)}" '
                f'endA="{round(effect.end_alpha * 100_000)}" '
                f'dir="5400000" fadeDir="5400000" sx="100000" sy="-100000" '
                f'ky="0" kx="0" algn="bl" rotWithShape="0"/>'
            )
        else:
            parts.append(
                f'<a:fillOverlay blend="{effect.blend}">'
                f"{_solid_fill(effect.fill.color)}</a:fillOverlay>"
            )
    if not parts:
        return ""
    return f"<a:effectLst>{''.join(parts)}</a:effectLst>"


def _custgeom_xml(cg: CustomGeometry) -> str:
    """Emit ``a:custGeom`` for a free-form path (ECMA-376 §20.1.9.8)."""
    parts: list[str] = []
    for cmd in cg.path:
        if isinstance(cmd, MoveTo):
            parts.append(f'<a:moveTo><a:pt x="{cmd.to.x}" y="{cmd.to.y}"/></a:moveTo>')
        elif isinstance(cmd, LineTo):
            parts.append(f'<a:lnTo><a:pt x="{cmd.to.x}" y="{cmd.to.y}"/></a:lnTo>')
        elif isinstance(cmd, CubicTo):
            parts.append(
                f"<a:cubicBezTo>"
                f'<a:pt x="{cmd.c1.x}" y="{cmd.c1.y}"/>'
                f'<a:pt x="{cmd.c2.x}" y="{cmd.c2.y}"/>'
                f'<a:pt x="{cmd.to.x}" y="{cmd.to.y}"/>'
                f"</a:cubicBezTo>"
            )
        elif isinstance(cmd, QuadTo):
            parts.append(
                f"<a:quadBezTo>"
                f'<a:pt x="{cmd.c1.x}" y="{cmd.c1.y}"/>'
                f'<a:pt x="{cmd.to.x}" y="{cmd.to.y}"/>'
                f"</a:quadBezTo>"
            )
        elif isinstance(cmd, ArcTo):
            parts.append(
                f'<a:arcTo wR="{cmd.width_radius}" hR="{cmd.height_radius}" '
                f'stAng="{cmd.start_angle}" swAng="{cmd.sweep_angle}"/>'
            )
        else:
            parts.append("<a:close/>")
    path = f'<a:path w="{cg.width_emu}" h="{cg.height_emu}">{"".join(parts)}</a:path>'
    return (
        "<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        '<a:rect l="0" t="0" r="r" b="b"/>'
        f"<a:pathLst>{path}</a:pathLst></a:custGeom>"
    )


def _geometry_xml(node: ShapeNode) -> str:
    if node.custom_geom is not None:
        return _custgeom_xml(node.custom_geom)
    if node.geom == "roundRect" and node.corner_radius_emu > 0:
        shorter = max(1, min(node.box.width, node.box.height))
        adj = min(50000, round(node.corner_radius_emu / shorter * 100000))
        return (
            '<a:prstGeom prst="roundRect"><a:avLst>'
            f'<a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
        )
    # For all other presets (including the new polygon-expressible ones) emit with empty avLst
    # (default adj values).  Custom adj overrides are not authored on the forward path today.
    return f'<a:prstGeom prst="{node.geom}"><a:avLst/></a:prstGeom>'


def _underline_attr(underline: bool | str) -> str:
    if underline is False:
        return ""
    token = "sng" if underline is True else underline
    return f' u="{_attr(token)}"'


def _hyperlink_xml(hyperlink: Hyperlink | None, rid: str | None) -> str:
    """An ``a:hlinkClick`` for a run, or ``""``. External links carry the rel id; slide jumps
    carry both the jump action and the rel id pointing at the target slide part."""
    if hyperlink is None or rid is None:
        # No relationship was written for this link (e.g. out-of-range slide jump
        # dropped by the writer) — an hlinkClick with an empty r:id is invalid.
        return ""
    if hyperlink.slide_index is not None:
        return f'<a:hlinkClick r:id="{rid}" action="{_SLIDE_JUMP_ACTION}"/>'
    return f'<a:hlinkClick r:id="{rid}"/>'


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
    bold = "" if run.bold_inherited else f' b="{1 if run.bold else 0}"'
    rpr = (
        f'<a:rPr lang="en-US" sz="{round(run.size_pt * 100)}"{bold} '
        f'i="{1 if run.italic else 0}"{decorations} dirty="0">'
        f"{_solid_fill(run.color)}"
        f"{_hyperlink_xml(run.hyperlink, rid)}"
        f'<a:latin typeface="{_attr(run.font_family)}"/></a:rPr>'
    )
    return f"<a:r>{rpr}<a:t>{escape(run.text)}</a:t></a:r>"


def _paragraph(paragraph: TextParagraph, hyperlink_rid: HyperlinkRid) -> str:
    align = _ALIGN_TO_OOXML.get(paragraph.align, "l")
    runs = "".join(_run(run, hyperlink_rid) for run in paragraph.runs)

    # Build a:pPr attributes.  Mandatory: algn.
    # marL and indent are in EMUs (ECMA-376 §21.1.2.2.6 ST_TextMargin → EMU).
    ppr_attrs = f' algn="{align}"'
    if paragraph.left_margin_pt:
        ppr_attrs += f' marL="{pt_to_emu(paragraph.left_margin_pt)}"'
    if paragraph.indent_pt:
        ppr_attrs += f' indent="{pt_to_emu(paragraph.indent_pt)}"'
    if paragraph.level:
        ppr_attrs += f' lvl="{paragraph.level}"'

    # Build a:pPr children in ECMA order:
    # a:lnSpc, a:spcBef, a:spcAft, [bullet color/size/font], a:buNone/a:buChar/a:buAutoNum
    ppr_children = ""

    # a:lnSpc
    if paragraph.line_spacing is not None:
        ls = paragraph.line_spacing
        if ls.percent is not None:
            val = round(ls.percent * 100_000)
            ppr_children += f'<a:lnSpc><a:spcPct val="{val}"/></a:lnSpc>'
        elif ls.points is not None:
            val = round(ls.points * 100)
            ppr_children += f'<a:lnSpc><a:spcPts val="{val}"/></a:lnSpc>'

    # a:spcBef
    if paragraph.space_before_pt is not None:
        val = round(paragraph.space_before_pt * 100)
        ppr_children += f'<a:spcBef><a:spcPts val="{val}"/></a:spcBef>'

    # a:spcAft
    if paragraph.space_after_pt is not None:
        val = round(paragraph.space_after_pt * 100)
        ppr_children += f'<a:spcAft><a:spcPts val="{val}"/></a:spcAft>'

    # bullet: a:buChar or a:buAutoNum
    if paragraph.bullet is not None:
        if isinstance(paragraph.bullet, CharBullet):
            char = _attr(paragraph.bullet.char)
            ppr_children += f'<a:buChar char="{char}"/>'
        else:
            scheme = _attr(paragraph.bullet.scheme)
            start = paragraph.bullet.start_at
            ppr_children += f'<a:buAutoNum type="{scheme}" startAt="{start}"/>'

    ppr = f"<a:pPr{ppr_attrs}>{ppr_children}</a:pPr>" if ppr_children else f"<a:pPr{ppr_attrs}/>"
    return f"<a:p>{ppr}{runs}</a:p>"


# Maps IR vertical anchor → DrawingML bodyPr anchor attribute value.
_ANCHOR_TO_OOXML = {"top": "t", "middle": "ctr", "bottom": "b"}


def _text_body(body: TextBody | None, hyperlink_rid: HyperlinkRid) -> str:
    if body is None:
        return ""
    # Vertical anchor: default "t" is the block-flow equivalent (text at the top).
    anchor = _ANCHOR_TO_OOXML.get(body.anchor, "t")

    # Multi-column: emit numCol/spcCol when columns > 1.
    col_attrs = ""
    if body.columns > 1:
        col_attrs = f' numCol="{body.columns}"'
        if body.column_gap_emu > 0:
            col_attrs += f' spcCol="{body.column_gap_emu}"'

    left, top, right, bottom = body.margins

    if body.autofit == "shape":
        autofit_el = "<a:spAutoFit/>"
    elif body.autofit == "normal":
        autofit_el = "<a:normAutofit/>"
    else:
        autofit_el = "<a:noAutofit/>"

    paragraphs = "".join(_paragraph(paragraph, hyperlink_rid) for paragraph in body.paragraphs)
    return (
        f'<p:txBody><a:bodyPr wrap="square" anchor="{anchor}" lIns="{left}" rIns="{right}"'
        f' tIns="{top}" bIns="{bottom}"{col_attrs}>'
        f"{autofit_el}</a:bodyPr><a:lstStyle/>{paragraphs}</p:txBody>"
    )


def _no_hyperlink_rid(_hyperlink: Hyperlink) -> str | None:
    return None


def _xfrm_xml(node: ShapeNode) -> str:
    """Build the ``a:xfrm`` element for a shape, including rotation and flip attributes.

    OOXML ``rot`` is in 60000ths of a degree, clockwise-positive — the same sign convention
    as CSS ``rotate()``.  Flip attributes are boolean (``"1"``/absent).
    """
    xfrm_attrs = ""
    if node.transform is not None:
        t = node.transform
        if t.rotation_deg != 0.0:
            rot_emu = round(t.rotation_deg * 60_000)
            xfrm_attrs += f' rot="{rot_emu}"'
        if t.flip_h:
            xfrm_attrs += ' flipH="1"'
        if t.flip_v:
            xfrm_attrs += ' flipV="1"'
    return (
        f"<a:xfrm{xfrm_attrs}>"
        f'<a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/>'
        f"</a:xfrm>"
    )


def shape_xml(
    node: ShapeNode,
    *,
    shape_id: int,
    blip_rid: str | None = None,
    svg_rid: str | None = None,
    hyperlink_rid: HyperlinkRid = _no_hyperlink_rid,
) -> str:
    """Build the ``<p:sp>`` for one shape. ``shape_id`` must be unique within the slide.

    ``blip_rid`` is the slide-relationship id for this shape's picture fill, if any (assigned
    by the package writer, which owns the media parts). ``svg_rid`` is the rel id of the paired
    SVG part for vector preservation. ``hyperlink_rid`` resolves a run hyperlink to its
    slide-relationship id (also assigned by the package writer).
    """
    fill = _fill_xml(
        node.fill,
        opacity=node.opacity,
        blip_rid=blip_rid,
        svg_rid=svg_rid,
        box=node.box,
    )
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Shape {shape_id}"/>'
        f"<p:cNvSpPr/><p:nvPr>{node_identity_xml(node)}</p:nvPr></p:nvSpPr>"
        f"<p:spPr>{_xfrm_xml(node)}"
        f"{_geometry_xml(node)}{fill}{line_xml(node.line)}{_effects_xml(node)}</p:spPr>"
        f"{_text_body(node.text, hyperlink_rid)}</p:sp>"
    )


def can_emit_picture(node: ShapeNode) -> bool:
    """Whether a shape is a pure bitmap that maps losslessly to native ``p:pic``."""
    return (
        isinstance(node.fill, PictureFill)
        and node.geom == "rect"
        and node.custom_geom is None
        and node.line is None
        and node.side_lines is None
        and not node.effects
        and node.corner_radius_emu == 0
        and node.opacity == 1.0
        and node.text is None
    )


def picture_xml(
    node: ShapeNode,
    *,
    shape_id: int,
    blip_rid: str,
    svg_rid: str | None = None,
) -> str:
    """Build an interoperable native ``p:pic`` for one pure bitmap node."""
    if not can_emit_picture(node):
        raise ValueError("native picture output requires a pure rectangular PictureFill node")
    fill = node.fill
    assert isinstance(fill, PictureFill)
    descr = (
        f' descr="{_attr(f"domoxml-raster:{fill.raster_role}")}"'
        if fill.raster_role is not None
        else ""
    )
    blip_fill = _blip_fill(blip_rid, fill.crop, svg_rid, tag="p:blipFill")
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="Picture {shape_id}"{descr}/>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f"<p:nvPr>{node_identity_xml(node)}</p:nvPr></p:nvPicPr>"
        f"{blip_fill}<p:spPr>{_xfrm_xml(node)}"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )
