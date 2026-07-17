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
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.units import emu_to_pt
from domoxml.slides.appearance_read import ThemeColors, rgba
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


def _underline(value: str | None) -> bool | str:
    if value is None or value == "none":
        return False
    return True if value == "sng" else value


def _caps(value: str | None) -> Literal["all", "small"] | None:
    if value == "all":
        return "all"
    return "small" if value == "small" else None


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

    if properties is None:
        return TextRun(text=text, font_family="sans-serif", size_pt=12.0)
    latin = child("a:latin")
    raw_typeface = latin.get("typeface", "sans-serif") if latin is not None else "sans-serif"
    family = resolve_typeface(raw_typeface, theme_ctx) if theme_ctx is not None else raw_typeface
    raw_size = attribute("sz", "1200")
    size_pt = int(raw_size) / 100 if raw_size is not None else 12.0

    solid_fill = child("a:solidFill")
    color = Rgba(r=0, g=0, b=0)
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

    hyperlink_source = slide_rpr if slide_rpr is not None else properties
    return TextRun(
        text=text,
        font_family=family or "sans-serif",
        size_pt=size_pt,
        bold=attribute("b") == "1",
        italic=attribute("i") == "1",
        underline=_underline(attribute("u")),
        strike=attribute("strike", "noStrike") not in {"noStrike", None},
        caps=_caps(attribute("cap")),
        letter_spacing_pt=int(attribute("spc", "0") or "0") / 100,
        color=color,
        hyperlink=hyperlink_for(hyperlink_source),
    )


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

        fallback_rpr = resolve_run_rpr(None, level, ph_ctx) if ph_ctx is not None else None
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
    )
