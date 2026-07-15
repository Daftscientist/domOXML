"""Contract tests for slide-level PresentationML feature adapters."""

from __future__ import annotations

from xml.etree.ElementTree import Element, fromstring

from domoxml.core.ir.model import (
    PatternFill,
    PictureFill,
    Rgba,
    SlideBackground,
    SolidFill,
)
from domoxml.slides.background import background_xml, parse_background
from domoxml.slides.transition import parse_transition, transition_xml

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def test_pattern_background_serializes_its_native_colors() -> None:
    background = SlideBackground(
        fill=PatternFill(
            preset="horz",
            fg=Rgba(r=1, g=2, b=3),
            bg=Rgba(r=250, g=251, b=252),
        )
    )

    xml = background_xml(background)

    assert '<a:pattFill prst="horz">' in xml
    assert '<a:srgbClr val="010203"/>' in xml
    assert '<a:srgbClr val="FAFBFC"/>' in xml


def test_picture_background_uses_the_supplied_relationship() -> None:
    background = SlideBackground(fill=PictureFill(data=b"image", ext="png"))

    assert 'r:embed="rId7"' in background_xml(background, "rId7")
    assert "<a:noFill/>" in background_xml(background)


def test_background_parser_delegates_drawingml_fill_parsing() -> None:
    slide = fromstring(
        f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:bg><p:bgPr>'
        '<a:solidFill><a:srgbClr val="123456"/></a:solidFill>'
        "</p:bgPr></p:bg></p:cSld></p:sld>"
    )
    seen: list[Element] = []

    def parse_fill(properties: Element) -> SolidFill:
        seen.append(properties)
        return SolidFill(color=Rgba(r=0x12, g=0x34, b=0x56))

    background = parse_background(slide, parse_fill)

    assert background == SlideBackground(fill=SolidFill(color=Rgba(r=0x12, g=0x34, b=0x56)))
    assert len(seen) == 1
    assert seen[0].tag == f"{{{_P}}}bgPr"


def test_transition_adapter_normalizes_powerpoint_aliases() -> None:
    transition = fromstring(
        f'<p:transition xmlns:p="{_P}" dur="250"><p:fly dir="l"/></p:transition>'
    )

    parsed = parse_transition(transition)

    assert parsed.type == "push"
    assert parsed.direction == "l"
    assert parsed.duration_ms == 250
    assert transition_xml(parsed) == '<p:transition dur="250"><p:push dir="l"/></p:transition>'
