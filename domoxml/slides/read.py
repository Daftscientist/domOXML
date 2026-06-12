"""Read PresentationML into PowerPoint canvas IR."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from PIL import ImageColor

from domoxml.core.fontsread import ReverseFontFace, read_embedded_fonts
from domoxml.core.ir.model import (
    Arrowhead,
    ArrowheadSize,
    ArrowheadType,
    AutoNumberBullet,
    Blur,
    Box,
    CharBullet,
    Fill,
    Geometry,
    GeometryKind,
    Glow,
    GradientFill,
    GradientStop,
    Hyperlink,
    Line,
    LineSpacing,
    PictureFill,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.opc import OpcPackage
from domoxml.core.units import emu_to_pt
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P, "r": _R}
_RID = f"{{{_R}}}id"
_EMBED = f"{{{_R}}}embed"
_OFFICE_DOCUMENT_REL = f"{_R}/officeDocument"
_HYPERLINK_REL = f"{_R}/hyperlink"
_SLIDE_REL = f"{_R}/slide"
_SLIDE_JUMP_ACTION = "ppaction://hlinksldjump"
_SLIDE_LAYOUT_REL = f"{_R}/slideLayout"
_SLIDE_MASTER_REL = f"{_R}/slideMaster"
_THEME_REL = f"{_R}/theme"
_ALIGN_FROM_OOXML: dict[str, Literal["left", "center", "right", "justify"]] = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
}
# All prstDash presets → nearest IR DashStyle (ECMA-376 §20.1.10.49).
_DASH_FROM_OOXML: dict[str, Literal["solid", "dash", "dot", "dashDot", "lgDash", "sysDash"]] = {
    "solid": "solid",
    "dash": "dash",
    "lgDash": "lgDash",
    "dashDot": "dashDot",
    "lgDashDot": "dashDot",
    "lgDashDotDot": "dashDot",
    "sysDash": "sysDash",
    "sysDot": "dot",
    "sysDashDot": "dashDot",
    "sysDashDotDot": "dashDot",
    "dot": "dot",
}
# a:ln cap attribute → IR LineCap (ECMA-376 §20.1.10.30).
_CAP_FROM_OOXML: dict[str, Literal["flat", "round", "square"]] = {
    "flat": "flat",
    "rnd": "round",
    "sq": "square",
}
_IMAGE_EXT = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif"}
_SCHEME_FALLBACK = {
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "44546A",
    "lt2": "E7E6E6",
    "accent1": "4472C4",
    "accent2": "ED7D31",
    "accent3": "A5A5A5",
    "accent4": "FFC000",
    "accent5": "5B9BD5",
    "accent6": "70AD47",
    "hlink": "0563C1",
    "folHlink": "954F72",
    "bg1": "FFFFFF",
    "tx1": "000000",
    "bg2": "E7E6E6",
    "tx2": "44546A",
}
_SYSTEM_FALLBACK = {"window": "FFFFFF", "windowText": "000000"}
type ThemeColors = dict[str, str]


@dataclass(frozen=True)
class PptxReadResult:
    """Canvas slides plus reverse-adapter diagnostics and retained OOXML."""

    slides: tuple[SlideIR, ...]
    warnings: tuple[ConversionWarning, ...] = ()
    preserved: tuple[PreservedFragment, ...] = ()
    embedded_fonts: tuple[ReverseFontFace, ...] = ()


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    value = element.get(name)
    return int(value) if value is not None else default


def _related_part_by_type(
    package: OpcPackage, source_part: str, relationship_type: str
) -> str | None:
    try:
        return package.related_part_by_type(source_part, relationship_type)
    except KeyError:
        return None


def _rgb_hex(element: Element, colors: ThemeColors) -> str | None:
    srgb = element.find("a:srgbClr", _NS)
    if srgb is not None:
        return srgb.get("val")
    scheme = element.find("a:schemeClr", _NS)
    if scheme is not None:
        value = scheme.get("val", "")
        return colors.get(value) or _SCHEME_FALLBACK.get(value)
    system = element.find("a:sysClr", _NS)
    if system is not None:
        return system.get("lastClr") or _SYSTEM_FALLBACK.get(system.get("val", ""))
    preset = element.find("a:prstClr", _NS)
    if preset is not None:
        try:
            red, green, blue = ImageColor.getrgb(preset.get("val", ""))[:3]
        except ValueError:
            return None
        return f"{red:02X}{green:02X}{blue:02X}"
    return None


def _rgba(element: Element | None, colors: ThemeColors) -> Rgba | None:
    if element is None:
        return None
    value = _rgb_hex(element, colors) or ""
    if len(value) != 6:
        return None
    color_element = next(iter(element), None)
    alpha = color_element.find("a:alpha", _NS) if color_element is not None else None
    opacity = _int_attr(alpha, "val", 100_000) / 100_000 if alpha is not None else 1.0
    return Rgba(
        r=int(value[0:2], 16),
        g=int(value[2:4], 16),
        b=int(value[4:6], 16),
        a=opacity,
    )


def _gradient(element: Element, colors: ThemeColors) -> GradientFill | None:
    stops: list[GradientStop] = []
    for stop in element.findall("a:gsLst/a:gs", _NS):
        color = _rgba(stop, colors)
        if color is not None:
            stops.append(GradientStop(pos=_int_attr(stop, "pos") / 100_000, color=color))
    if len(stops) < 2:
        return None
    path = element.find("a:path", _NS)
    linear = element.find("a:lin", _NS)
    angle = ((_int_attr(linear, "ang") / 60_000) - 270.0) % 360.0 if linear is not None else 180.0
    return GradientFill(stops=tuple(stops), angle_deg=angle, radial=path is not None)


def _picture(element: Element, package: OpcPackage, slide_part: str) -> PictureFill | None:
    blip = element.find("a:blip", _NS)
    rid = blip.get(_EMBED) if blip is not None else None
    if rid is None:
        return None
    part = package.related_part(slide_part, rid)
    ext = _IMAGE_EXT.get(PurePosixPath(part).suffix.lower().lstrip("."))
    if ext is None:
        return None
    return PictureFill(data=package.read(part), ext=ext)  # type: ignore[arg-type]


def _fill(
    shape_properties: Element,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
) -> Fill | None:
    solid = shape_properties.find("a:solidFill", _NS)
    if solid is not None:
        color = _rgba(solid, colors)
        return SolidFill(color=color) if color is not None else None
    gradient = shape_properties.find("a:gradFill", _NS)
    if gradient is not None:
        return _gradient(gradient, colors)
    picture = shape_properties.find("a:blipFill", _NS)
    return _picture(picture, package, slide_part) if picture is not None else None


def _arrowhead(element: Element | None) -> Arrowhead | None:
    """Parse ``a:headEnd``/``a:tailEnd`` into an :class:`Arrowhead`, or ``None`` when absent."""
    if element is None:
        return None
    atype = element.get("type", "none")
    if atype not in {"triangle", "stealth", "diamond", "oval", "arrow"}:
        return None
    # w / len attributes use the ArrowheadSize tokens (sm/med/lg).
    width_raw = element.get("w", "med")
    length_raw = element.get("len", "med")
    width: ArrowheadSize = width_raw if width_raw in {"sm", "med", "lg"} else "med"  # type: ignore[assignment]
    length: ArrowheadSize = length_raw if length_raw in {"sm", "med", "lg"} else "med"  # type: ignore[assignment]
    atype_typed: ArrowheadType = atype  # type: ignore[assignment]
    return Arrowhead(type=atype_typed, width=width, length=length)


def _line(shape_properties: Element, colors: ThemeColors) -> Line | None:
    element = shape_properties.find("a:ln", _NS)
    if element is None:
        return None
    # Color: prefer solidFill; fall back to gradFill (first stop as flat colour).
    solid_el = element.find("a:solidFill", _NS)
    grad_el = element.find("a:gradFill", _NS)
    gradient: GradientFill | None = None
    color: Rgba | None = None
    if solid_el is not None:
        color = _rgba(solid_el, colors)
    elif grad_el is not None:
        gradient = _gradient(grad_el, colors)
        if gradient is not None and gradient.stops:
            color = gradient.stops[0].color
    if color is None:
        return None
    dash_el = element.find("a:prstDash", _NS)
    dash_val = dash_el.get("val", "solid") if dash_el is not None else "solid"
    cap_val = element.get("cap", "flat")
    # Join: scan child tags (round/bevel/miter); default round when absent.
    join: Literal["round", "bevel", "miter"] = "round"
    if element.find("a:bevel", _NS) is not None:
        join = "bevel"
    elif element.find("a:miter", _NS) is not None:
        join = "miter"
    elif element.find("a:round", _NS) is not None:
        join = "round"
    return Line(
        color=color,
        width_emu=max(1, _int_attr(element, "w", 1)),
        dash=_DASH_FROM_OOXML.get(dash_val, "solid"),
        cap=_CAP_FROM_OOXML.get(cap_val, "flat"),
        join=join,
        gradient=gradient,
        head=_arrowhead(element.find("a:headEnd", _NS)),
        tail=_arrowhead(element.find("a:tailEnd", _NS)),
    )


type Effect = Shadow | Glow | Blur | SoftEdge | Reflection


def _parse_shadow_element(element: Element, colors: ThemeColors, *, inset: bool) -> Shadow:
    """Parse ``a:outerShdw`` or ``a:innerShdw`` into :class:`Shadow`."""
    color = _rgba(element, colors) or Rgba(r=0, g=0, b=0, a=0.5)
    blur = _int_attr(element, "blurRad")
    dist = _int_attr(element, "dist")
    direction_deg = _int_attr(element, "dir") / 60_000
    spread_emu = 0
    if not inset:
        # sx/sy grow attrs encode spread. Reverse-compute spread from sx (use width-axis sx).
        # sx = (w + 2*s) / w * 100000  =>  s = (sx/100000 - 1) * w / 2
        # Since we don't have shape dims here, store the raw sx/sy for the HTML emitter.
        # We store a representative spread as the mean of sx/sy offsets if present.
        sx = _int_attr(element, "sx", 100_000)
        sy = _int_attr(element, "sy", 100_000)
        if sx != 100_000 or sy != 100_000:
            # We can't recover absolute px spread without shape dims — store a flag value
            # that the HTML emitter will recognise (we use a sentinel EMU value encoding the
            # sx/sy pair so that the forward round-trip can reconstruct it).
            # Convention: store sx*1 + sy*1 normalised scaling factor encoded as EMU-equivalent.
            # Simplest faithful encoding: store the mean scale delta as spread_emu = scale * EMU.
            # For HTML emission we only need sx/sy; store them packed.
            # Use spread_emu = (sx - 100000) encoded — shapes without size need a best-effort.
            # The HTML emitter will use spread_emu directly as a best-effort pixel offset.
            # We encode: spread = mean of (sx-100000)/100000 * dist_emu, which approximates
            # the extra shadow radius in EMU (even without shape width knowledge).
            mean_scale = ((sx - 100_000) / 100_000 + (sy - 100_000) / 100_000) / 2
            # Minimum 1 EMU to distinguish "spread was present" from "no spread"
            spread_emu = max(1, round(mean_scale * max(dist, 1)))
    return Shadow(
        color=color,
        blur_emu=blur,
        distance_emu=dist,
        direction_deg=direction_deg,
        inset=inset,
        spread_emu=spread_emu,
    )


def _effects(
    shape_properties: Element, colors: ThemeColors
) -> tuple[tuple[Effect, ...], tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    """Parse ``a:effectLst`` into typed effect objects.

    Returns ``(effects, warnings, preserved)`` — unsupported effect kinds
    (``a:prstShdw``, ``a:fillOverlay``) become :class:`PreservedFragment` entries.
    """
    effect_lst = shape_properties.find("a:effectLst", _NS)
    if effect_lst is None:
        return (), (), ()

    effects: list[Effect] = []
    warns: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []

    for child in effect_lst:
        local = child.tag.rsplit("}", 1)[-1]
        if local == "outerShdw":
            effects.append(_parse_shadow_element(child, colors, inset=False))
        elif local == "innerShdw":
            effects.append(_parse_shadow_element(child, colors, inset=True))
        elif local == "glow":
            color = _rgba(child, colors) or Rgba(r=0, g=0, b=0, a=0.5)
            radius = _int_attr(child, "rad")
            effects.append(Glow(color=color, radius_emu=radius))
        elif local == "blur":
            radius = _int_attr(child, "rad")
            effects.append(Blur(radius_emu=radius))
            warns.append(
                ConversionWarning(
                    message="a:blur mapped to filter:blur() — forward round-trip will rasterise"
                )
            )
        elif local == "softEdge":
            radius = _int_attr(child, "rad")
            effects.append(SoftEdge(radius_emu=radius))
        elif local == "reflection":
            blur_rad = _int_attr(child, "blurRad")
            dist = _int_attr(child, "dist")
            start_a = _int_attr(child, "startA", 100_000) / 100_000
            end_a = _int_attr(child, "endA", 0) / 100_000
            effects.append(
                Reflection(
                    blur_emu=blur_rad,
                    distance_emu=dist,
                    start_alpha=min(1.0, max(0.0, start_a)),
                    end_alpha=min(1.0, max(0.0, end_a)),
                )
            )
            warns.append(
                ConversionWarning(
                    message="a:reflection approximated as -webkit-box-reflect; "
                    "forward round-trip will rasterise"
                )
            )
        elif local in {"prstShdw", "fillOverlay"}:
            warns.append(
                ConversionWarning(message=f"a:{local} has no CSS mapping; preserved as fragment")
            )
            preserved.append(
                PreservedFragment(
                    part="effectLst",
                    kind=local,
                    xml=ElementTree.tostring(child, encoding="unicode"),
                )
            )
        # Other unknown tags: skip silently per no-silent-drop policy → but these ARE unknown,
        # so we preserve them too.
        else:
            warns.append(
                ConversionWarning(
                    message=f"a:{local} (in effectLst) has no CSS mapping; preserved as fragment"
                )
            )
            preserved.append(
                PreservedFragment(
                    part="effectLst",
                    kind=local,
                    xml=ElementTree.tostring(child, encoding="unicode"),
                )
            )

    return tuple(effects), tuple(warns), tuple(preserved)


def _underline(value: str | None) -> bool | str:
    """Map ``a:rPr u`` to the IR underline value: ``"none"``/absent → ``False``, ``"sng"`` →
    ``True`` (single), any other style token kept verbatim (``"dbl"``, ``"heavy"``, …)."""
    if value is None or value == "none":
        return False
    return True if value == "sng" else value


def _caps(value: str | None) -> Literal["all", "small"] | None:
    """Map ``a:rPr cap`` to the IR caps token; ``"none"``/absent/unknown → ``None``."""
    if value == "all":
        return "all"
    return "small" if value == "small" else None


def _text_run(
    element: Element,
    colors: ThemeColors,
    hyperlink_for: Callable[[Element], Hyperlink | None],
) -> TextRun | None:
    text = element.findtext("a:t", default="", namespaces=_NS)
    if not text:
        return None
    properties = element.find("a:rPr", _NS)
    if properties is None:
        return TextRun(text=text, font_family="sans-serif", size_pt=12.0)
    latin = properties.find("a:latin", _NS)
    family = latin.get("typeface", "sans-serif") if latin is not None else "sans-serif"
    color = _rgba(properties.find("a:solidFill", _NS), colors) or Rgba(r=0, g=0, b=0)
    return TextRun(
        text=text,
        font_family=family,
        size_pt=_int_attr(properties, "sz", 1200) / 100,
        bold=properties.get("b") == "1",
        italic=properties.get("i") == "1",
        underline=_underline(properties.get("u")),
        strike=properties.get("strike", "noStrike") not in ("noStrike", None),
        caps=_caps(properties.get("cap")),
        letter_spacing_pt=_int_attr(properties, "spc", 0) / 100,
        color=color,
        hyperlink=hyperlink_for(properties),
    )


# Maps DrawingML bodyPr anchor → IR TextBody anchor literal.
_ANCHOR_FROM_OOXML: dict[str, Literal["top", "middle", "bottom"]] = {
    "t": "top",
    "ctr": "middle",
    "b": "bottom",
}


def _text_body_props(
    body: Element,
) -> tuple[Literal["top", "middle", "bottom"], Literal["none", "normal", "shape"], int, int]:
    """Parse ``a:bodyPr`` into ``(anchor, autofit, columns, column_gap_emu)``.

    - ``anchor``: vertical alignment from ``anchor`` attr (default "t" → "top").
    - ``autofit``: ``a:spAutoFit`` → "shape"; ``a:noAutofit`` → "none"; else "normal".
    - ``columns``: ``numCol`` attr (default 1).
    - ``column_gap_emu``: ``spcCol`` attr (default 0).
    """
    body_pr = body.find("a:bodyPr", _NS)
    if body_pr is None:
        return "top", "normal", 1, 0

    anchor_raw = body_pr.get("anchor", "t")
    anchor: Literal["top", "middle", "bottom"] = _ANCHOR_FROM_OOXML.get(anchor_raw, "top")

    # Autofit: check for a:spAutoFit or a:noAutofit child.
    autofit: Literal["none", "normal", "shape"] = "normal"
    if body_pr.find("a:spAutoFit", _NS) is not None:
        autofit = "shape"
    elif body_pr.find("a:noAutofit", _NS) is not None:
        autofit = "none"

    columns = max(1, _int_attr(body_pr, "numCol", 1))
    column_gap_emu = max(0, _int_attr(body_pr, "spcCol", 0))
    return anchor, autofit, columns, column_gap_emu


def _text_body(
    shape: Element,
    colors: ThemeColors,
    hyperlink_for: Callable[[Element], Hyperlink | None],
) -> TextBody | None:
    body = shape.find("p:txBody", _NS)
    if body is None:
        return None
    anchor, autofit, columns, column_gap_emu = _text_body_props(body)
    paragraphs: list[TextParagraph] = []
    for paragraph in body.findall("a:p", _NS):
        properties = paragraph.find("a:pPr", _NS)
        align = _ALIGN_FROM_OOXML.get(
            properties.get("algn", "l") if properties is not None else "l", "left"
        )

        # Spacing: lnSpc, spcBef, spcAft
        line_spacing: LineSpacing | None = None
        space_before_pt: float | None = None
        space_after_pt: float | None = None
        indent_pt: float = 0.0
        left_margin_pt: float = 0.0
        level: int = 0
        bullet = None

        if properties is not None:
            # marL / indent (EMUs → pt)
            mar_l = properties.get("marL")
            if mar_l is not None:
                with contextlib.suppress(ValueError):
                    left_margin_pt = emu_to_pt(int(mar_l))
            indent_raw = properties.get("indent")
            if indent_raw is not None:
                with contextlib.suppress(ValueError):
                    indent_pt = emu_to_pt(int(indent_raw))
            lvl_raw = properties.get("lvl")
            if lvl_raw is not None:
                with contextlib.suppress(ValueError):
                    level = max(0, int(lvl_raw))

            # a:lnSpc
            ln_spc = properties.find("a:lnSpc", _NS)
            if ln_spc is not None:
                spc_pct = ln_spc.find("a:spcPct", _NS)
                spc_pts = ln_spc.find("a:spcPts", _NS)
                if spc_pct is not None:
                    val = _int_attr(spc_pct, "val", 100_000)
                    line_spacing = LineSpacing(percent=val / 100_000)
                elif spc_pts is not None:
                    val = _int_attr(spc_pts, "val", 0)
                    if val > 0:
                        line_spacing = LineSpacing(points=val / 100)

            # a:spcBef / a:spcAft
            spc_bef = properties.find("a:spcBef", _NS)
            if spc_bef is not None:
                pts = spc_bef.find("a:spcPts", _NS)
                if pts is not None:
                    val = _int_attr(pts, "val", 0)
                    if val > 0:
                        space_before_pt = val / 100

            spc_aft = properties.find("a:spcAft", _NS)
            if spc_aft is not None:
                pts = spc_aft.find("a:spcPts", _NS)
                if pts is not None:
                    val = _int_attr(pts, "val", 0)
                    if val > 0:
                        space_after_pt = val / 100

            # Bullets
            bu_char = properties.find("a:buChar", _NS)
            bu_auto = properties.find("a:buAutoNum", _NS)
            if bu_char is not None:
                char = bu_char.get("char", "•")
                bullet = CharBullet(char=char)
            elif bu_auto is not None:
                scheme = bu_auto.get("type", "arabicPeriod")
                start_at = _int_attr(bu_auto, "startAt", 1)
                bullet = AutoNumberBullet(scheme=scheme, start_at=start_at)

        runs = tuple(
            run
            for element in paragraph.findall("a:r", _NS)
            if (run := _text_run(element, colors, hyperlink_for)) is not None
        )
        paragraphs.append(
            TextParagraph(
                runs=runs,
                align=align,
                line_spacing=line_spacing,
                space_before_pt=space_before_pt,
                space_after_pt=space_after_pt,
                indent_pt=indent_pt,
                left_margin_pt=left_margin_pt,
                level=level,
                bullet=bullet,
            )
        )
    return (
        TextBody(
            paragraphs=tuple(paragraphs),
            anchor=anchor,
            autofit=autofit,
            columns=columns,
            column_gap_emu=column_gap_emu,
        )
        if paragraphs
        else None
    )


def _shape(
    element: Element,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
    hyperlink_for: Callable[[Element], Hyperlink | None],
) -> tuple[ShapeNode | None, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if properties is None or offset is None or extent is None:
        return None, (), ()
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    geometry = properties.find("a:prstGeom", _NS)
    geom_name = geometry.get("prst", "rect") if geometry is not None else "rect"
    # Map the OOXML prstGeom name onto a GeometryKind literal. Any name that is a valid
    # GeometryKind passes through directly; unknown names fall back to "rect" so the shape
    # is still readable (geometry just loses its silhouette).
    _valid_geom_kinds: frozenset[str] = frozenset(GeometryKind.__args__)  # type: ignore[attr-defined]
    geom: Geometry = geom_name if geom_name in _valid_geom_kinds else "rect"  # type: ignore[assignment]
    guide = geometry.find("a:avLst/a:gd", _NS) if geometry is not None else None
    formula = guide.get("fmla", "") if guide is not None else ""
    corner = 0
    if geom == "roundRect" and formula.startswith("val "):
        try:
            corner = round(int(formula.removeprefix("val ")) / 100_000 * min(box.width, box.height))
        except (TypeError, ValueError):
            corner = 0
    shape_effects, effect_warns, effect_preserved = _effects(properties, colors)
    return (
        ShapeNode(
            box=box,
            geom=geom,
            fill=_fill(properties, package, slide_part, colors),
            line=_line(properties, colors),
            effects=shape_effects,
            corner_radius_emu=corner,
            text=_text_body(element, colors, hyperlink_for),
        ),
        effect_warns,
        effect_preserved,
    )


def _picture_shape(element: Element, package: OpcPackage, slide_part: str) -> ShapeNode | None:
    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    fill = element.find("p:blipFill", _NS)
    if properties is None or offset is None or extent is None or fill is None:
        return None
    picture = _picture(fill, package, slide_part)
    if picture is None:
        return None
    return ShapeNode(
        box=Box(
            x=_int_attr(offset, "x"),
            y=_int_attr(offset, "y"),
            width=_int_attr(extent, "cx"),
            height=_int_attr(extent, "cy"),
        ),
        fill=picture,
    )


def _local_name(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _preserve(
    slide_part: str, element: Element, reason: str
) -> tuple[ConversionWarning, PreservedFragment]:
    kind = _local_name(element)
    return (
        ConversionWarning(message=reason, element=f"{slide_part}:{kind}"),
        PreservedFragment(
            part=slide_part,
            kind=kind,
            xml=ElementTree.tostring(element, encoding="unicode"),
        ),
    )


def _hyperlink_resolver(
    package: OpcPackage, slide_part: str, slide_index_by_part: dict[str, int]
) -> Callable[[Element], Hyperlink | None]:
    """A resolver from a run's ``a:rPr`` to its :class:`Hyperlink`.

    An external ``a:hlinkClick r:id`` becomes a URL from the rel target; a slide-jump
    (``action="ppaction://hlinksldjump"``) resolves its internal rel to the destination slide
    part and recovers its zero-based deck index. Missing/empty links yield ``None``."""
    relationships = {rel.id: rel for rel in package.relationships(slide_part)}

    def resolve(properties: Element) -> Hyperlink | None:
        click = properties.find("a:hlinkClick", _NS)
        if click is None:
            return None
        rid = click.get(_RID)
        action = click.get("action", "")
        if action == _SLIDE_JUMP_ACTION:
            if rid and rid in relationships:
                target = package.resolve(slide_part, relationships[rid])
                index = slide_index_by_part.get(target)
                if index is not None:
                    return Hyperlink(slide_index=index)
            return None
        if not rid:
            return None
        relationship = relationships.get(rid)
        if relationship is None:
            return None
        if relationship.target_mode != "Internal":
            return Hyperlink(url=relationship.target)
        # An internal slide target without the jump action is still an in-deck jump.
        target = package.resolve(slide_part, relationship)
        index = slide_index_by_part.get(target)
        return Hyperlink(slide_index=index) if index is not None else None

    return resolve


def _slide(
    package: OpcPackage,
    slide_part: str,
    *,
    width: int,
    height: int,
    slide_index_by_part: dict[str, int],
) -> tuple[SlideIR, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    colors = _slide_colors(package, slide_part)
    hyperlink_for = _hyperlink_resolver(package, slide_part, slide_index_by_part)
    root = ElementTree.fromstring(package.read(slide_part))
    tree = root.find("./p:cSld/p:spTree", _NS)
    shapes: list[ShapeNode] = []
    warnings: list[ConversionWarning] = []
    preserved: list[PreservedFragment] = []
    if tree is not None:
        for element in tree:
            kind = _local_name(element)
            if kind in {"nvGrpSpPr", "grpSpPr"}:
                continue
            if kind == "sp":
                shape, shape_warns, shape_preserved = _shape(
                    element, package, slide_part, colors, hyperlink_for
                )
                if shape is not None:
                    shapes.append(shape)
                    warnings.extend(shape_warns)
                    preserved.extend(shape_preserved)
                    if not shape_preserved:
                        continue
                reason = "preserved shape that the reverse adapter could not map"
            elif kind == "pic":
                shape = _picture_shape(element, package, slide_part)
                if shape is not None:
                    shapes.append(shape)
                    if element.find("p:blipFill/a:srcRect", _NS) is None:
                        continue
                    reason = "preserved picture crop metadata; crop mapping pending"
                else:
                    reason = "preserved picture that the reverse adapter could not map"
            else:
                reason = f"preserved unsupported reverse slide node: {kind}"
            warning, fragment = _preserve(slide_part, element, reason)
            warnings.append(warning)
            preserved.append(fragment)
    return (
        SlideIR(width=width, height=height, shapes=tuple(shapes)),
        tuple(warnings),
        tuple(preserved),
    )


def _theme_colors(package: OpcPackage, theme_part: str | None) -> ThemeColors:
    colors = dict(_SCHEME_FALLBACK)
    if theme_part is None:
        theme_parts = [part for part in package.parts if part.startswith("ppt/theme/")]
        theme_part = theme_parts[0] if theme_parts else None
    if theme_part is None:
        return colors
    root = ElementTree.fromstring(package.read(theme_part))
    scheme = root.find("a:themeElements/a:clrScheme", _NS)
    if scheme is None:
        return colors
    for element in scheme:
        value = _rgb_hex(element, colors)
        if value is not None:
            colors[element.tag.rsplit("}", 1)[-1]] = value
    return colors


def _color_map(package: OpcPackage, part: str | None, path: str) -> dict[str, str]:
    if part is None:
        return {}
    root = ElementTree.fromstring(package.read(part))
    element = root.find(path, _NS)
    return dict(element.attrib) if element is not None else {}


def _slide_colors(package: OpcPackage, slide_part: str) -> ThemeColors:
    layout_part = _related_part_by_type(package, slide_part, _SLIDE_LAYOUT_REL)
    master_part = (
        _related_part_by_type(package, layout_part, _SLIDE_MASTER_REL)
        if layout_part is not None
        else None
    )
    theme_part = (
        _related_part_by_type(package, master_part, _THEME_REL) if master_part is not None else None
    )
    colors = _theme_colors(package, theme_part)
    mapping = _color_map(package, master_part, "p:clrMap")
    mapping.update(_color_map(package, layout_part, "p:clrMapOvr/a:overrideClrMapping"))
    mapping.update(_color_map(package, slide_part, "p:clrMapOvr/a:overrideClrMapping"))
    return {**colors, **{key: colors.get(value, value) for key, value in mapping.items()}}


def read_pptx_result(pptx: bytes) -> PptxReadResult:
    """Read a PPTX package into ordered canvas slides plus reverse diagnostics."""
    package = OpcPackage.from_bytes(pptx)
    presentation_part = package.related_part_by_type(None, _OFFICE_DOCUMENT_REL)
    root = ElementTree.fromstring(package.read(presentation_part))
    size = root.find("p:sldSz", _NS)
    if size is None:
        raise ValueError("PPTX presentation has no slide size")
    width, height = _int_attr(size, "cx"), _int_attr(size, "cy")
    slide_ids = root.findall("p:sldIdLst/p:sldId", _NS)
    slide_parts = [
        package.related_part(presentation_part, slide_id.attrib[_RID]) for slide_id in slide_ids
    ]
    # Deck-order index per slide part, so a slide-jump rel can recover its zero-based target.
    slide_index_by_part = {part: index for index, part in enumerate(slide_parts)}
    results = [
        _slide(
            package,
            slide_part,
            width=width,
            height=height,
            slide_index_by_part=slide_index_by_part,
        )
        for slide_part in slide_parts
    ]
    font_faces, font_warnings = read_embedded_fonts(package, root, presentation_part)
    all_warnings = tuple(warning for result in results for warning in result[1]) + tuple(
        font_warnings
    )
    return PptxReadResult(
        slides=tuple(result[0] for result in results),
        warnings=all_warnings,
        preserved=tuple(fragment for result in results for fragment in result[2]),
        embedded_fonts=tuple(font_faces),
    )


def read_pptx(pptx: bytes) -> list[SlideIR]:
    """Read a PPTX package into ordered canvas slides."""
    return list(read_pptx_result(pptx).slides)
