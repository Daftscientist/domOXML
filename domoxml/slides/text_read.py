"""DrawingML text body, paragraph, and run parsing for reverse conversion."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Literal
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import (
    AutoNumberBullet,
    CharBullet,
    Hyperlink,
    LineSpacing,
    Rgba,
    Shadow,
    TextBody,
    TextOutline,
    TextParagraph,
    TextRun,
)
from domoxml.core.units import emu_to_pt
from domoxml.slides.appearance_read import ThemeColors, rgba
from domoxml.slides.appearance_read import gradient as gradient_fill_for
from domoxml.slides.inherit import (
    PlaceholderContext,
    ThemeContext,
    resolve_ppr,
    resolve_run_rpr,
    resolve_scheme_color,
    resolve_typeface,
)

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}
_ALIGN_FROM_OOXML: dict[str, Literal["left", "center", "right", "justify"]] = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
}
_ANCHOR_FROM_OOXML: dict[str, Literal["top", "middle", "bottom"]] = {
    "t": "top",
    "ctr": "middle",
    "b": "bottom",
}

type HyperlinkResolver = Callable[[Element], Hyperlink | None]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    value = element.get(name)
    return int(value) if value is not None else default


def _underline_fill(element: Element | None, colors: ThemeColors) -> Rgba | None:
    """An underline's own colour (``a:uFill``), or ``None`` when it follows the text."""
    solid = element.find("a:solidFill", _NS) if element is not None else None
    return rgba(solid, colors) if solid is not None else None


def _underline(value: str | None) -> bool | str:
    if value is None or value == "none":
        return False
    return True if value == "sng" else value


def _caps(value: str | None) -> Literal["all", "small"] | None:
    if value == "all":
        return "all"
    return "small" if value == "small" else None


def _outline(element: Element | None, colors: ThemeColors) -> TextOutline | None:
    """A text run's ``a:ln`` as a :class:`TextOutline`, or ``None`` if it paints nothing."""
    if element is None or element.find("a:noFill", _NS) is not None:
        return None
    color = (
        rgba(element.find("a:solidFill", _NS), colors)
        if element.find("a:solidFill", _NS) is not None
        else None
    )
    width = int(element.get("w", "0") or "0")
    if color is None or width <= 0:
        return None
    return TextOutline(width_pt=emu_to_pt(width), color=color)


def _text_shadow(effects: Element | None, colors: ThemeColors) -> Shadow | None:
    """The first ``a:outerShdw`` of a run's ``a:effectLst`` as a :class:`Shadow`."""
    shadow = effects.find("a:outerShdw", _NS) if effects is not None else None
    if shadow is None:
        return None
    color = rgba(shadow, colors)
    if color is None:
        return None
    return Shadow(
        color=color,
        blur_emu=int(shadow.get("blurRad", "0") or "0"),
        distance_emu=int(shadow.get("dist", "0") or "0"),
        direction_deg=int(shadow.get("dir", "0") or "0") / 60_000,
    )


_FILL_CHOICES = ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")


# What PowerPoint sets text in when nothing in the chain (run, list style, master, presentation
# default) names a size.
_DEFAULT_SIZE_PT = 18.0


def read_text_run(
    element: Element,
    colors: ThemeColors,
    hyperlink_for: HyperlinkResolver,
    *,
    fallback_rpr: Element | None = None,
    theme_ctx: ThemeContext | None = None,
) -> TextRun | None:
    """Parse one text run, resolving fallback properties and theme fonts/colors."""
    text = element.findtext("a:t", default="", namespaces=_NS)
    if not text:
        return None
    slide_rpr = element.find("a:rPr", _NS)
    properties = slide_rpr if slide_rpr is not None else fallback_rpr

    def attribute(name: str, default: str | None = None) -> str | None:
        if slide_rpr is not None and (value := slide_rpr.get(name)) is not None:
            return value
        if fallback_rpr is not None and (value := fallback_rpr.get(name)) is not None:
            return value
        return default

    def child(tag: str) -> Element | None:
        if slide_rpr is not None and (found := slide_rpr.find(tag, _NS)) is not None:
            return found
        return fallback_rpr.find(tag, _NS) if fallback_rpr is not None else None

    # Text that names no typeface anywhere in its chain is set in the theme's body font.
    unnamed = "+mn-lt" if theme_ctx is not None else "sans-serif"
    if properties is None:
        family = resolve_typeface(unnamed, theme_ctx) if theme_ctx is not None else unnamed
        return TextRun(text=text, font_family=family, size_pt=_DEFAULT_SIZE_PT)
    latin = child("a:latin")
    raw_typeface = latin.get("typeface", unnamed) if latin is not None else unnamed
    family = resolve_typeface(raw_typeface, theme_ctx) if theme_ctx is not None else raw_typeface
    raw_size = attribute("sz", str(round(_DEFAULT_SIZE_PT * 100)))
    size_pt = int(raw_size) / 100 if raw_size is not None else _DEFAULT_SIZE_PT

    # The fill is one choice (no fill, solid or gradient), so it comes from the run's own
    # properties when they make a choice and from the inherited ones only when they do not.
    fill_owner = next(
        (
            candidate
            for candidate in (slide_rpr, fallback_rpr)
            if candidate is not None
            and any(candidate.find(f"a:{tag}", _NS) is not None for tag in _FILL_CHOICES)
        ),
        None,
    )
    solid_fill = fill_owner.find("a:solidFill", _NS) if fill_owner is not None else None
    color = Rgba(r=0, g=0, b=0)
    if fill_owner is not None and fill_owner.find("a:noFill", _NS) is not None:
        color = Rgba(r=0, g=0, b=0, a=0.0)
    if solid_fill is not None:
        scheme = solid_fill.find("a:schemeClr", _NS)
        resolved = (
            resolve_scheme_color(scheme, colors) if scheme is not None and theme_ctx else None
        )
        if resolved is not None:
            red, green, blue, alpha = resolved
            color = Rgba(r=red, g=green, b=blue, a=alpha)
        else:
            color = rgba(solid_fill, colors) or color

    gradient_fill = fill_owner.find("a:gradFill", _NS) if fill_owner is not None else None
    gradient = gradient_fill_for(gradient_fill, colors) if gradient_fill is not None else None
    if gradient is not None:
        color = gradient.stops[0].color
    outline = _outline(child("a:ln"), colors)
    shadow = _text_shadow(child("a:effectLst"), colors)

    hyperlink_source = slide_rpr if slide_rpr is not None else properties
    lift = int(attribute("baseline", "0") or "0")
    return TextRun(
        text=text,
        font_family=family or "sans-serif",
        size_pt=size_pt * (2 / 3 if lift else 1.0),
        baseline=lift,
        bold=attribute("b") == "1",
        italic=attribute("i") == "1",
        underline=_underline(attribute("u")),
        underline_color=_underline_fill(child("a:uFill"), colors),
        strike=attribute("strike", "noStrike") not in {"noStrike", None},
        caps=_caps(attribute("cap")),
        letter_spacing_pt=int(attribute("spc", "0") or "0") / 100,
        color=color,
        hyperlink=hyperlink_for(hyperlink_source),
        gradient=gradient,
        outline=outline,
        shadow=shadow,
    )


_MIRRORED_ALIGN: dict[
    Literal["left", "center", "right", "justify"], Literal["left", "center", "right", "justify"]
] = {
    "left": "right",
    "right": "left",
}


def _vertical(body: Element) -> Literal["horz", "vert", "vert270"]:
    """``bodyPr vert`` as a text direction; stacked and East-Asian variants read as ``vert``."""
    properties = body.find("a:bodyPr", _NS)
    value = properties.get("vert", "horz") if properties is not None else "horz"
    if value == "vert270":
        return "vert270"
    return "vert" if value in {"vert", "eaVert", "wordArtVert"} else "horz"


def _wrap(body: Element) -> Literal["square", "none"]:
    properties = body.find("a:bodyPr", _NS)
    return "none" if properties is not None and properties.get("wrap") == "none" else "square"


def _text_is_mirrored(body: Element) -> bool:
    """Whether ``bodyPr`` turns the text 180 degrees about the vertical axis (mirrored text)."""
    rotation = body.find("a:bodyPr/a:scene3d/a:camera/a:rot", _NS)
    if rotation is None:
        return False
    longitude = int(rotation.get("lon", "0")) % 21600000
    return abs(longitude - 10800000) < 60000


def read_text_body_properties(
    body: Element,
    ph_ctx: PlaceholderContext | None = None,
) -> tuple[
    Literal["top", "middle", "bottom"],
    Literal["none", "normal", "shape"],
    int,
    int,
    tuple[int, int, int, int],
]:
    """Return vertical anchor, autofit, columns, gap, and text-body insets."""
    chain = [body.find("a:bodyPr", _NS)]
    if ph_ctx is not None:
        chain.extend((ph_ctx.layout_ph_body_pr, ph_ctx.master_ph_body_pr))
    properties = [item for item in chain if item is not None]

    def attribute(name: str, default: str) -> str:
        return next(
            (value for item in properties if (value := item.get(name)) is not None),
            default,
        )

    anchor = _ANCHOR_FROM_OOXML.get(attribute("anchor", "t"), "top")
    autofit: Literal["none", "normal", "shape"] = "normal"
    for item in properties:
        if item.find("a:spAutoFit", _NS) is not None:
            autofit = "shape"
            break
        if item.find("a:noAutofit", _NS) is not None:
            autofit = "none"
            break
        if item.find("a:normAutofit", _NS) is not None:
            break
    return (
        anchor,
        autofit,
        max(1, int(attribute("numCol", "1"))),
        max(0, int(attribute("spcCol", "0"))),
        (
            max(0, int(attribute("lIns", "91440"))),
            max(0, int(attribute("tIns", "45720"))),
            max(0, int(attribute("rIns", "91440"))),
            max(0, int(attribute("bIns", "45720"))),
        ),
    )


def read_text_body(
    shape: Element,
    colors: ThemeColors,
    hyperlink_for: HyperlinkResolver,
    *,
    ph_ctx: PlaceholderContext | None = None,
    theme_ctx: ThemeContext | None = None,
) -> TextBody | None:
    """Parse a shape text body with paragraph and placeholder inheritance."""
    body = shape.find("p:txBody", _NS)
    if body is None:
        return None
    anchor, autofit, columns, column_gap_emu, margins = read_text_body_properties(body, ph_ctx)
    mirrored = _text_is_mirrored(body)
    if mirrored:
        margins = (margins[2], margins[1], margins[0], margins[3])
    paragraphs: list[TextParagraph] = []
    for paragraph in body.findall("a:p", _NS):
        slide_properties = paragraph.find("a:pPr", _NS)
        level = 0
        if slide_properties is not None and (raw_level := slide_properties.get("lvl")) is not None:
            with contextlib.suppress(ValueError):
                level = max(0, int(raw_level))
        properties = resolve_ppr(slide_properties, level, ph_ctx)
        alignment = _ALIGN_FROM_OOXML.get(
            properties.get("algn", "l") if properties is not None else "l", "left"
        )
        if mirrored:
            alignment = _MIRRORED_ALIGN.get(alignment, alignment)
        line_spacing: LineSpacing | None = None
        space_before_pt: float | None = None
        space_after_pt: float | None = None
        indent_pt = 0.0
        left_margin_pt = 0.0
        bullet = None
        if properties is not None:
            if (raw_margin := properties.get("marL")) is not None:
                with contextlib.suppress(ValueError):
                    left_margin_pt = emu_to_pt(int(raw_margin))
            if (raw_indent := properties.get("indent")) is not None:
                with contextlib.suppress(ValueError):
                    indent_pt = emu_to_pt(int(raw_indent))
            line_spacing_element = properties.find("a:lnSpc", _NS)
            if line_spacing_element is not None:
                percent = line_spacing_element.find("a:spcPct", _NS)
                points = line_spacing_element.find("a:spcPts", _NS)
                if percent is not None:
                    line_spacing = LineSpacing(percent=_int_attr(percent, "val", 100_000) / 100_000)
                elif points is not None and (value := _int_attr(points, "val")) > 0:
                    line_spacing = LineSpacing(points=value / 100)
            before = properties.find("a:spcBef/a:spcPts", _NS)
            after = properties.find("a:spcAft/a:spcPts", _NS)
            if before is not None and (value := _int_attr(before, "val")) > 0:
                space_before_pt = value / 100
            if after is not None and (value := _int_attr(after, "val")) > 0:
                space_after_pt = value / 100
            character_bullet = properties.find("a:buChar", _NS)
            auto_bullet = properties.find("a:buAutoNum", _NS)
            if character_bullet is not None:
                bullet = CharBullet(char=character_bullet.get("char", "•"))
            elif auto_bullet is not None:
                bullet = AutoNumberBullet(
                    scheme=auto_bullet.get("type", "arabicPeriod"),
                    start_at=_int_attr(auto_bullet, "startAt", 1),
                )

        fallback_rpr = resolve_run_rpr(
            None,
            level,
            ph_ctx,
            own_list_style=body.find("a:lstStyle", _NS),
            default_style=theme_ctx.default_text_style if theme_ctx is not None else None,
        )
        runs = tuple(
            run
            for element in paragraph
            if element.tag in {f"{{{_A}}}r", f"{{{_A}}}fld"}
            and (
                run := read_text_run(
                    element,
                    colors,
                    hyperlink_for,
                    fallback_rpr=fallback_rpr,
                    theme_ctx=theme_ctx,
                )
            )
            is not None
        )
        paragraphs.append(
            TextParagraph(
                runs=runs,
                align=alignment,
                line_spacing=line_spacing,
                space_before_pt=space_before_pt,
                space_after_pt=space_after_pt,
                indent_pt=indent_pt,
                left_margin_pt=left_margin_pt,
                level=level,
                bullet=bullet,
            )
        )
    if not paragraphs:
        return None
    return TextBody(
        paragraphs=tuple(paragraphs),
        anchor=anchor,
        autofit=autofit,
        columns=columns,
        column_gap_emu=column_gap_emu,
        margins=margins,
        mirror_x=mirrored,
        vertical=_vertical(body),
        wrap=_wrap(body),
    )
