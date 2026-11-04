"""Line and text gradients are written with subdivided stops, as fills are."""

from __future__ import annotations

import io
import zipfile

from domoxml.core.ir.model import (
    Box,
    GradientFill,
    GradientStop,
    Line,
    Rgba,
    ShapeNode,
    SlideIR,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides.pptx import build_pptx

_PX = 9525
_PINK_TO_GREEN = GradientFill(
    angle_deg=90,
    stops=(
        GradientStop(pos=0, color=Rgba(r=250, g=30, b=200)),
        GradientStop(pos=1, color=Rgba(r=10, g=240, b=40)),
    ),
)


def _xml(shape: ShapeNode) -> str:
    deck = build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(shape,))], faces=[])
    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        return package.read("ppt/slides/slide1.xml").decode()


def test_a_gradient_line_is_written_with_subdivided_stops() -> None:
    shape = ShapeNode(
        box=Box(x=0, y=0, width=500 * _PX, height=250 * _PX),
        geom="rect",
        line=Line(color=Rgba(r=250, g=30, b=200), width_emu=24 * _PX, gradient=_PINK_TO_GREEN),
    )

    xml = _xml(shape)
    line = xml[xml.index("<a:ln") : xml.index("</a:ln>")]

    assert line.count("<a:gs ") == 9 and 'val="828778"' in line  # the exact midpoint


def test_gradient_text_is_written_with_subdivided_stops() -> None:
    run = TextRun(text="GRAD", font_family="Arial", size_pt=100.0, gradient=_PINK_TO_GREEN)
    shape = ShapeNode(
        box=Box(x=0, y=0, width=500 * _PX, height=250 * _PX),
        geom="rect",
        text=TextBody(paragraphs=(TextParagraph(runs=(run,)),)),
    )

    xml = _xml(shape)
    properties = xml[xml.index("<a:rPr") : xml.index("</a:rPr>")]

    assert properties.count("<a:gs ") == 9 and 'val="828778"' in properties
