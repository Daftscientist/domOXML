"""Text inside a preset shape: PowerPoint lays it out in the preset's own text rectangle."""

from __future__ import annotations

import re

from domoxml.core.drawingml.preset_geometry import preset_text_insets
from domoxml.core.drawingml.shape import shape_xml
from domoxml.core.ir.model import Box, ShapeNode, SlideIR, TextBody, TextParagraph, TextRun
from domoxml.slides import build_pptx
from domoxml.slides.read import read_pptx

_BOX = Box(x=0, y=0, width=2_000_000, height=1_000_000)


def _text(margins: tuple[int, int, int, int]) -> TextBody:
    run = TextRun(text="hello", font_family="sans-serif", size_pt=12)
    return TextBody(paragraphs=(TextParagraph(runs=(run,)),), margins=margins)


def _shape(geom: str, margins: tuple[int, int, int, int]) -> ShapeNode:
    return ShapeNode(box=_BOX, geom=geom, text=_text(margins))  # type: ignore[arg-type]


def test_a_rectangle_text_fills_the_box_and_an_ellipse_text_is_inscribed() -> None:
    assert preset_text_insets("rect", 2_000_000, 1_000_000) == (0, 0, 0, 0)
    assert preset_text_insets("noSuchPreset", 2_000_000, 1_000_000) == (0, 0, 0, 0)
    left, top, right, bottom = preset_text_insets("ellipse", 2_000_000, 1_000_000)
    # The inscribed rectangle of an ellipse is inset by (1 - cos 45deg) / 2 = 14.64% a side.
    assert abs(left - 0.1464 * 2_000_000) < 2_000 and left == right
    assert abs(top - 0.1464 * 1_000_000) < 2_000 and top == bottom


def test_the_writer_takes_the_text_rectangle_out_of_the_insets() -> None:
    inset = preset_text_insets("ellipse", 2_000_000, 1_000_000)
    xml = shape_xml(_shape("ellipse", (100_000, 50_000, 100_000, 50_000)), shape_id=1)

    written = re.search(r'lIns="(-?\d+)" rIns="(-?\d+)" tIns="(-?\d+)" bIns="(-?\d+)"', xml)

    assert written is not None
    assert tuple(int(v) for v in written.groups()) == (
        100_000 - inset[0],
        100_000 - inset[2],
        50_000 - inset[1],
        50_000 - inset[3],
    )  # negative: the box padding is smaller than the rectangle's own inset
    assert 'lIns="100000"' in shape_xml(
        _shape("rect", (100_000, 50_000, 100_000, 50_000)), shape_id=1
    )


def test_margins_survive_a_round_trip_through_a_preset_shape() -> None:
    margins = (300_000, 150_000, 300_000, 150_000)
    for geom in ("ellipse", "triangle", "roundRect", "rightArrow"):
        slide = SlideIR(width=12_192_000, height=6_858_000, shapes=(_shape(geom, margins),))

        [back] = read_pptx(build_pptx([slide], faces=[]))

        text = back.shapes[0].text
        assert text is not None and text.margins == margins, geom
