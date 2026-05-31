"""Read PresentationML into PowerPoint canvas IR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from PIL import ImageColor

from domoxml.core.ir.model import (
    Box,
    Fill,
    GradientFill,
    GradientStop,
    Line,
    PictureFill,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.opc import OpcPackage
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P, "r": _R}
_RID = f"{{{_R}}}id"
_EMBED = f"{{{_R}}}embed"
_OFFICE_DOCUMENT_REL = f"{_R}/officeDocument"
_SLIDE_LAYOUT_REL = f"{_R}/slideLayout"
_SLIDE_MASTER_REL = f"{_R}/slideMaster"
_THEME_REL = f"{_R}/theme"
_ALIGN_FROM_OOXML: dict[str, Literal["left", "center", "right", "justify"]] = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
}
_DASH_FROM_OOXML: dict[str, Literal["solid", "dash", "dot"]] = {
    "solid": "solid",
    "dash": "dash",
    "sysDot": "dot",
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


def _line(shape_properties: Element, colors: ThemeColors) -> Line | None:
    element = shape_properties.find("a:ln", _NS)
    if element is None:
        return None
    color = _rgba(element.find("a:solidFill", _NS), colors)
    if color is None:
        return None
    dash = element.find("a:prstDash", _NS)
    return Line(
        color=color,
        width_emu=max(1, _int_attr(element, "w", 1)),
        dash=_DASH_FROM_OOXML.get(
            dash.get("val", "solid") if dash is not None else "solid", "solid"
        ),
    )


def _shadow(shape_properties: Element, colors: ThemeColors) -> Shadow | None:
    effects = shape_properties.find("a:effectLst", _NS)
    if effects is None:
        return None
    for tag, inset in (("a:outerShdw", False), ("a:innerShdw", True)):
        element = effects.find(tag, _NS)
        if element is None:
            continue
        color = _rgba(element, colors) or Rgba(r=0, g=0, b=0, a=0.5)
        return Shadow(
            color=color,
            blur_emu=_int_attr(element, "blurRad"),
            distance_emu=_int_attr(element, "dist"),
            direction_deg=_int_attr(element, "dir") / 60_000,
            inset=inset,
        )
    return None


def _text_run(element: Element, colors: ThemeColors) -> TextRun | None:
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
        color=color,
    )


def _text_body(shape: Element, colors: ThemeColors) -> TextBody | None:
    body = shape.find("p:txBody", _NS)
    if body is None:
        return None
    paragraphs: list[TextParagraph] = []
    for paragraph in body.findall("a:p", _NS):
        properties = paragraph.find("a:pPr", _NS)
        align = _ALIGN_FROM_OOXML.get(
            properties.get("algn", "l") if properties is not None else "l", "left"
        )
        runs = tuple(
            run
            for element in paragraph.findall("a:r", _NS)
            if (run := _text_run(element, colors)) is not None
        )
        paragraphs.append(TextParagraph(runs=runs, align=align))
    return TextBody(paragraphs=tuple(paragraphs)) if paragraphs else None


def _shape(
    element: Element, package: OpcPackage, slide_part: str, colors: ThemeColors
) -> ShapeNode | None:
    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if properties is None or offset is None or extent is None:
        return None
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    geometry = properties.find("a:prstGeom", _NS)
    geom_name = geometry.get("prst", "rect") if geometry is not None else "rect"
    geom: Literal["rect", "roundRect", "ellipse"]
    if geom_name == "roundRect":
        geom = "roundRect"
    elif geom_name == "ellipse":
        geom = "ellipse"
    else:
        geom = "rect"
    guide = geometry.find("a:avLst/a:gd", _NS) if geometry is not None else None
    formula = guide.get("fmla", "") if guide is not None else ""
    corner = 0
    if formula.startswith("val "):
        try:
            corner = round(int(formula.removeprefix("val ")) / 100_000 * min(box.width, box.height))
        except (TypeError, ValueError):
            corner = 0
    return ShapeNode(
        box=box,
        geom=geom,
        fill=_fill(properties, package, slide_part, colors),
        line=_line(properties, colors),
        shadow=_shadow(properties, colors),
        corner_radius_emu=corner,
        text=_text_body(element, colors),
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


def _slide(
    package: OpcPackage, slide_part: str, *, width: int, height: int
) -> tuple[SlideIR, tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    colors = _slide_colors(package, slide_part)
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
                shape = _shape(element, package, slide_part, colors)
                if shape is not None:
                    shapes.append(shape)
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
    results = [
        _slide(
            package,
            package.related_part(presentation_part, slide_id.attrib[_RID]),
            width=width,
            height=height,
        )
        for slide_id in slide_ids
    ]
    return PptxReadResult(
        slides=tuple(result[0] for result in results),
        warnings=tuple(warning for result in results for warning in result[1]),
        preserved=tuple(fragment for result in results for fragment in result[2]),
    )


def read_pptx(pptx: bytes) -> list[SlideIR]:
    """Read a PPTX package into ordered canvas slides."""
    return list(read_pptx_result(pptx).slides)
