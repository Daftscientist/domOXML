"""A border sits inside the CSS box; the file centres its stroke, so the box is inset by half."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from domoxml.core.ir.model import (
    Box,
    Line,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_PX = 9525


def _shape(**fields: object) -> ShapeNode:
    base: dict[str, object] = {
        "box": Box(x=100 * _PX, y=60 * _PX, width=500 * _PX, height=250 * _PX),
        "geom": "rect",
        "fill": SolidFill(color=Rgba(r=255, g=238, b=136)),
        "line": Line(color=Rgba(r=0, g=102, b=204), width_emu=24 * _PX),
    }
    base.update(fields)
    return ShapeNode(**base)  # type: ignore[arg-type]


def _deck(shape: ShapeNode) -> bytes:
    return build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(shape,))], faces=[])


def _xfrm(deck: bytes) -> tuple[int, int, int, int]:
    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    match = re.search(r'<a:off x="(\d+)" y="(\d+)"/><a:ext cx="(\d+)" cy="(\d+)"/>', xml)
    assert match is not None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def test_the_file_box_is_inset_by_half_the_stroke_so_it_covers_the_css_border_band() -> None:
    x, y, width, height = _xfrm(_deck(_shape()))

    assert (x, y) == ((100 + 12) * _PX, (60 + 12) * _PX)
    assert (width, height) == ((500 - 24) * _PX, (250 - 24) * _PX)


def test_a_shape_without_a_stroke_keeps_its_box() -> None:
    assert _xfrm(_deck(_shape(line=None))) == (100 * _PX, 60 * _PX, 500 * _PX, 250 * _PX)


def test_a_shape_thinner_than_its_stroke_keeps_its_box() -> None:
    rule = _shape(box=Box(x=0, y=10 * _PX, width=400 * _PX, height=2 * _PX))

    assert _xfrm(_deck(rule)) == (0, 10 * _PX, 400 * _PX, 2 * _PX)


@pytest.mark.parametrize("geom", ["rect", "ellipse"])
def test_the_css_box_survives_a_write_and_read(geom: str) -> None:
    shape = _shape(geom=geom)

    [back] = read_pptx_result(_deck(shape)).slides[0].contents

    assert isinstance(back, ShapeNode) and back.box == shape.box


def test_a_corner_radius_is_inset_with_the_box_and_restored_on_reading() -> None:
    shape = _shape(geom="roundRect", corner_radius_emu=40 * _PX)

    deck = _deck(shape)
    [back] = read_pptx_result(deck).slides[0].contents

    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    # 28 px on the stroke's centre line over a 226 px short side.
    assert f'fmla="val {round(28 * _PX / (226 * _PX) * 100000)}"' in xml
    assert (
        isinstance(back, ShapeNode) and abs(back.corner_radius_emu - 40 * _PX) <= 100
    )  # adj is in 1/100000ths


def test_text_stays_where_it_was_when_the_box_moves_in() -> None:
    body = TextBody(
        paragraphs=(TextParagraph(runs=(TextRun(text="Hi", font_family="Arial", size_pt=20.0),)),),
        margins=(30 * _PX, 30 * _PX, 30 * _PX, 30 * _PX),
    )
    shape = _shape(text=body)

    deck = _deck(shape)
    [back] = read_pptx_result(deck).slides[0].contents

    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    assert f'lIns="{18 * _PX}"' in xml  # 30 px from the border box less the 12 px the box moved
    assert isinstance(back, ShapeNode) and back.text is not None
    assert back.text.margins == body.margins


def test_a_powerpoint_shape_is_boxed_out_to_its_strokes_outer_edge_in_html() -> None:
    html = pptx_to_html(_deck(_shape())).slides[0].html

    assert f"left:{100}px" in html.replace(".0", "") and f"width:{500}px" in html.replace(".0", "")


def test_a_bordered_shapes_html_padding_leaves_the_border_out() -> None:
    body = TextBody(
        paragraphs=(TextParagraph(runs=(TextRun(text="Hi", font_family="Arial", size_pt=20.0),)),),
        margins=(30 * _PX, 30 * _PX, 30 * _PX, 30 * _PX),
    )
    html = (
        pptx_to_html(
            _deck(_shape(text=body, line=Line(color=Rgba(r=0, g=0, b=0), width_emu=24 * _PX)))
        )
        .slides[0]
        .html
    )

    assert (
        "border:24px solid" in html and "padding:6px 6px 6px 6px" in html
    )  # 30 from the edge less the 24 px border


def test_a_corner_radius_the_inset_uses_up_is_written_as_an_explicit_zero() -> None:
    shape = _shape(geom="roundRect", corner_radius_emu=4 * _PX)  # less than half the 24 px stroke

    with zipfile.ZipFile(io.BytesIO(_deck(shape))) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()

    assert 'prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 0"/>' in xml


@pytest.mark.parametrize("height", [26, 40, 60, 72, 90])
def test_shapes_thicker_than_their_stroke_round_trip_to_their_own_box(height: int) -> None:
    shape = _shape(box=Box(x=100 * _PX, y=60 * _PX, width=500 * _PX, height=height * _PX))

    [back] = read_pptx_result(_deck(shape)).slides[0].contents

    assert isinstance(back, ShapeNode) and back.box == shape.box
