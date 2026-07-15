"""DrawingML fill, picture, color, and line parsing for reverse conversion."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal
from xml.etree.ElementTree import Element

from PIL import ImageColor

from domoxml.core.ir.model import (
    Arrowhead,
    ArrowheadSize,
    ArrowheadType,
    ColorSpec,
    ColorTransform,
    Fill,
    GradientFill,
    GradientStop,
    Line,
    PatternFill,
    PictureFill,
    Rgba,
    SolidFill,
    SrcRect,
    ThemeColorRef,
)
from domoxml.core.opc import OpcPackage

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A}
_EMBED = f"{{{_R}}}embed"
_ASVG_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
_IMAGE_EXT = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif"}
DEFAULT_THEME_COLORS: dict[str, str] = {
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
_TRANSFORM_KINDS = {"lumMod", "lumOff", "shade", "tint", "alpha", "satMod"}
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
_CAP_FROM_OOXML: dict[str, Literal["flat", "round", "square"]] = {
    "flat": "flat",
    "rnd": "round",
    "sq": "square",
}

type ThemeColors = dict[str, str]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    value = element.get(name)
    return int(value) if value is not None else default


def rgb_hex(element: Element, colors: ThemeColors) -> str | None:
    """Resolve a DrawingML color container to six-digit sRGB."""
    srgb = element.find("a:srgbClr", _NS)
    if srgb is not None:
        return srgb.get("val")
    scheme = element.find("a:schemeClr", _NS)
    if scheme is not None:
        value = scheme.get("val", "")
        return colors.get(value) or DEFAULT_THEME_COLORS.get(value)
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


def rgba(element: Element | None, colors: ThemeColors) -> Rgba | None:
    """Resolve a DrawingML color container, including alpha."""
    if element is None:
        return None
    value = rgb_hex(element, colors) or ""
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


def gradient(element: Element, colors: ThemeColors) -> GradientFill | None:
    """Parse a DrawingML linear or path gradient."""
    stops = tuple(
        GradientStop(pos=_int_attr(stop, "pos") / 100_000, color=color)
        for stop in element.findall("a:gsLst/a:gs", _NS)
        if (color := rgba(stop, colors)) is not None
    )
    if len(stops) < 2:
        return None
    linear = element.find("a:lin", _NS)
    angle = ((_int_attr(linear, "ang") / 60_000) - 270.0) % 360.0 if linear is not None else 180.0
    return GradientFill(
        stops=stops,
        angle_deg=angle,
        radial=element.find("a:path", _NS) is not None,
    )


def src_rect(element: Element) -> SrcRect | None:
    """Read an ``a:srcRect`` crop into normalized edge insets."""
    rect = element.find("a:srcRect", _NS)
    if rect is None:
        return None
    values = tuple(_int_attr(rect, edge) / 100_000 for edge in ("l", "t", "r", "b"))
    if not any(values):
        return None
    left, top, right, bottom = values
    return SrcRect(
        left=min(1.0, max(0.0, left)),
        top=min(1.0, max(0.0, top)),
        right=min(1.0, max(0.0, right)),
        bottom=min(1.0, max(0.0, bottom)),
    )


def _svg_blip(blip: Element, package: OpcPackage, slide_part: str) -> bytes | None:
    for extension in blip.findall("a:extLst/a:ext", _NS):
        if extension.get("uri") != _ASVG_URI:
            continue
        for child in extension:
            if child.tag.rsplit("}", 1)[-1] != "svgBlip":
                continue
            relationship_id = child.get(_EMBED)
            if relationship_id is not None:
                try:
                    return package.read(package.related_part(slide_part, relationship_id))
                except KeyError:
                    return None
    return None


def picture(
    element: Element,
    package: OpcPackage,
    slide_part: str,
    *,
    raster_role: str | None = None,
) -> PictureFill | None:
    """Resolve a picture fill, preferring its Office SVG extension when present."""
    blip = element.find("a:blip", _NS)
    relationship_id = blip.get(_EMBED) if blip is not None else None
    if relationship_id is None:
        return None
    crop = src_rect(element)
    if blip is not None and (svg_data := _svg_blip(blip, package, slide_part)) is not None:
        return PictureFill(
            data=svg_data,
            ext="png",
            svg_data=svg_data,
            crop=crop,
            raster_role=raster_role,
        )
    part = package.related_part(slide_part, relationship_id)
    extension = _IMAGE_EXT.get(PurePosixPath(part).suffix.lower().lstrip("."))
    if extension is None:
        return None
    return PictureFill(
        data=package.read(part),
        ext=extension,  # type: ignore[arg-type]
        crop=crop,
        raster_role=raster_role,
    )


def color_spec(element: Element | None, colors: ThemeColors) -> ColorSpec | None:
    """Retain theme references and transforms; resolve other color forms to RGBA."""
    if element is None:
        return None
    scheme = element.find("a:schemeClr", _NS)
    if scheme is not None:
        slot = scheme.get("val", "")
        if slot in ThemeColorRef.model_fields["slot"].annotation.__args__:  # type: ignore[union-attr]
            transforms = tuple(
                ColorTransform(
                    kind=child.tag.rsplit("}", 1)[-1],  # type: ignore[arg-type]
                    value=min(1.0, max(0.0, _int_attr(child, "val", 100_000) / 100_000)),
                )
                for child in scheme
                if child.tag.rsplit("}", 1)[-1] in _TRANSFORM_KINDS
            )
            return ThemeColorRef(slot=slot, transforms=transforms)  # type: ignore[arg-type]
    return rgba(element, colors)


def pattern_fill(element: Element, colors: ThemeColors) -> PatternFill | None:
    preset = element.get("prst")
    foreground = color_spec(element.find("a:fgClr", _NS), colors)
    background = color_spec(element.find("a:bgClr", _NS), colors)
    if not preset or foreground is None or background is None:
        return None
    return PatternFill(preset=preset, fg=foreground, bg=background)


def fill(
    shape_properties: Element,
    package: OpcPackage,
    slide_part: str,
    colors: ThemeColors,
) -> Fill | None:
    """Parse the first supported fill child on a shape-properties container."""
    solid = shape_properties.find("a:solidFill", _NS)
    if solid is not None:
        color = rgba(solid, colors)
        return SolidFill(color=color) if color is not None else None
    gradient_element = shape_properties.find("a:gradFill", _NS)
    if gradient_element is not None:
        return gradient(gradient_element, colors)
    pattern = shape_properties.find("a:pattFill", _NS)
    if pattern is not None:
        return pattern_fill(pattern, colors)
    picture_element = shape_properties.find("a:blipFill", _NS)
    return picture(picture_element, package, slide_part) if picture_element is not None else None


def _arrowhead(element: Element | None) -> Arrowhead | None:
    if element is None:
        return None
    arrow_type = element.get("type", "none")
    if arrow_type not in {"triangle", "stealth", "diamond", "oval", "arrow"}:
        return None
    raw_width = element.get("w", "med")
    raw_length = element.get("len", "med")
    width: ArrowheadSize = raw_width if raw_width in {"sm", "med", "lg"} else "med"  # type: ignore[assignment]
    length: ArrowheadSize = raw_length if raw_length in {"sm", "med", "lg"} else "med"  # type: ignore[assignment]
    typed_arrow: ArrowheadType = arrow_type  # type: ignore[assignment]
    return Arrowhead(type=typed_arrow, width=width, length=length)


def line_element(element: Element, colors: ThemeColors) -> Line | None:
    """Parse one DrawingML line after its owner has located it."""
    solid = element.find("a:solidFill", _NS)
    gradient_element = element.find("a:gradFill", _NS)
    gradient_fill: GradientFill | None = None
    color = rgba(solid, colors) if solid is not None else None
    if solid is None and gradient_element is not None:
        gradient_fill = gradient(gradient_element, colors)
        if gradient_fill is not None and gradient_fill.stops:
            color = gradient_fill.stops[0].color
    if color is None:
        return None
    dash = element.find("a:prstDash", _NS)
    dash_value = dash.get("val", "solid") if dash is not None else "solid"
    join: Literal["round", "bevel", "miter"] = "round"
    if element.find("a:bevel", _NS) is not None:
        join = "bevel"
    elif element.find("a:miter", _NS) is not None:
        join = "miter"
    return Line(
        color=color,
        width_emu=max(1, _int_attr(element, "w", 1)),
        dash=_DASH_FROM_OOXML.get(dash_value, "solid"),
        cap=_CAP_FROM_OOXML.get(element.get("cap", "flat"), "flat"),
        join=join,
        gradient=gradient_fill,
        head=_arrowhead(element.find("a:headEnd", _NS)),
        tail=_arrowhead(element.find("a:tailEnd", _NS)),
    )


def line(shape_properties: Element, colors: ThemeColors) -> Line | None:
    """Locate and parse a shape's ``a:ln`` child."""
    element = shape_properties.find("a:ln", _NS)
    return line_element(element, colors) if element is not None else None
