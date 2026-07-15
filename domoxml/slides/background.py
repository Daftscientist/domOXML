"""PresentationML slide-background serialization and parsing."""

from __future__ import annotations

from collections.abc import Callable
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import (
    Fill,
    GradientFill,
    GradientStop,
    PictureFill,
    Rgba,
    SlideBackground,
    SolidFill,
)

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"p": _P}


def _srgb(color: Rgba) -> str:
    return f"{color.r:02X}{color.g:02X}{color.b:02X}"


def _solid_fill_xml(color: Rgba) -> str:
    alpha_xml = f'<a:alpha val="{round(color.a * 100_000)}"/>' if color.a < 1.0 else ""
    return f'<a:solidFill><a:srgbClr val="{_srgb(color)}">{alpha_xml}</a:srgbClr></a:solidFill>'


def _gradient_stop_xml(stop: GradientStop) -> str:
    alpha_xml = f'<a:alpha val="{round(stop.color.a * 100_000)}"/>' if stop.color.a < 1.0 else ""
    return (
        f'<a:gs pos="{round(stop.pos * 100_000)}"><a:srgbClr val="{_srgb(stop.color)}">'
        f"{alpha_xml}</a:srgbClr></a:gs>"
    )


def _gradient_fill_xml(gradient: GradientFill) -> str:
    stops = "".join(_gradient_stop_xml(stop) for stop in gradient.stops)
    if gradient.radial:
        path = (
            '<a:path path="circle">'
            '<a:fillToRect l="100000" t="100000" r="100000" b="100000"/>'
            "</a:path>"
        )
        return f"<a:gradFill><a:gsLst>{stops}</a:gsLst>{path}</a:gradFill>"
    angle = round(((270 + gradient.angle_deg) % 360) * 60_000)
    return f'<a:gradFill><a:gsLst>{stops}</a:gsLst><a:lin ang="{angle}" scaled="0"/></a:gradFill>'


def background_xml(background: SlideBackground, blip_rid: str | None = None) -> str:
    """Serialize a native slide background into its ``p:bg`` element."""
    fill = background.fill
    if isinstance(fill, SolidFill):
        fill_xml = _solid_fill_xml(fill.color)
    elif isinstance(fill, GradientFill):
        fill_xml = _gradient_fill_xml(fill)
    elif isinstance(fill, PictureFill):
        fill_xml = (
            f'<a:blipFill><a:blip r:embed="{blip_rid}"/>'
            "<a:stretch><a:fillRect/></a:stretch></a:blipFill>"
            if blip_rid is not None
            else "<a:noFill/>"
        )
    else:
        foreground = _srgb(fill.fg) if isinstance(fill.fg, Rgba) else "000000"
        background_color = _srgb(fill.bg) if isinstance(fill.bg, Rgba) else "FFFFFF"
        fill_xml = (
            f'<a:pattFill prst="{fill.preset}">'
            f'<a:fgClr><a:srgbClr val="{foreground}"/></a:fgClr>'
            f'<a:bgClr><a:srgbClr val="{background_color}"/></a:bgClr>'
            "</a:pattFill>"
        )
    return f"<p:bg><p:bgPr>{fill_xml}<a:effectLst/></p:bgPr></p:bg>"


def parse_background(
    slide: Element, fill_parser: Callable[[Element], Fill | None]
) -> SlideBackground | None:
    """Parse the slide background using the caller's general DrawingML fill parser."""
    properties = slide.find("./p:cSld/p:bg/p:bgPr", _NS)
    if properties is None:
        return None
    fill = fill_parser(properties)
    return SlideBackground(fill=fill) if fill is not None else None
