"""Unit tests for IR parsing + extraction (no browser)."""

from __future__ import annotations

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import Rgba, SolidFill
from domoxml.core.ir.parse import is_bold, parse_color, parse_length_px
from domoxml.core.render.browser import RenderedNode, RenderedSlide


def test_parse_color_rgb_and_rgba() -> None:
    assert parse_color("rgb(255, 0, 0)") == Rgba(r=255, g=0, b=0, a=1.0)
    assert parse_color("rgba(0, 128, 255, 0.5)") == Rgba(r=0, g=128, b=255, a=0.5)
    assert parse_color("transparent") is None
    assert parse_color(None) is None


def test_color_hex() -> None:
    color = parse_color("rgb(79, 70, 229)")
    assert color is not None and color.hex == "4F46E5"


def test_parse_length_takes_first_px() -> None:
    assert parse_length_px("8px") == 8.0
    assert parse_length_px("12px 4px 4px 12px") == 12.0
    assert parse_length_px("") == 0.0


def test_is_bold() -> None:
    assert is_bold("700")
    assert is_bold("bold")
    assert is_bold("bolder")
    assert not is_bold("400")
    assert not is_bold("normal")
    assert not is_bold(None)


def test_extract_normalizes_logical_text_align() -> None:
    node = RenderedNode(
        tag="p", x=0, y=0, width=10, height=10, text="x", styles={"textAlign": "start"}
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=100, nodes=(node,))).slide
    assert ir.shapes[0].text is not None
    assert ir.shapes[0].text.paragraphs[0].align == "left"  # 'start' → 'left'


def test_extract_maps_box_fill_and_text() -> None:
    node = RenderedNode(
        tag="div",
        x=96,  # 1in -> 914400 EMU
        y=0,
        width=192,  # 2in
        height=96,
        text="Hello",
        styles={
            "backgroundColor": "rgb(79, 70, 229)",
            "color": "rgb(255, 255, 255)",
            "fontSize": "24px",
            "fontWeight": "700",
            "fontFamily": "'Inter', sans-serif",
            "borderRadius": "8px",
            "textAlign": "center",
            "opacity": "1",
        },
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=1280, height=720, nodes=(node,))).slide

    assert ir.width == 12_192_000  # 1280px -> EMU
    shape = ir.shapes[0]
    assert shape.box.x == 914_400 and shape.box.width == 1_828_800
    assert isinstance(shape.fill, SolidFill) and shape.fill.color.hex == "4F46E5"
    assert shape.corner_radius_emu == 76_200  # 8px
    assert shape.text is not None
    paragraph = shape.text.paragraphs[0]
    [run] = paragraph.runs
    assert run.text == "Hello"
    assert run.size_pt == 18.0  # 24px -> 18pt
    assert run.bold is True
    assert run.font_family == "Inter"
    assert paragraph.align == "center"


def test_transparent_background_is_no_fill() -> None:
    node = RenderedNode(
        tag="span", x=0, y=0, width=10, height=10, styles={"backgroundColor": "rgba(0, 0, 0, 0)"}
    )
    ir = extract_slide(RenderedSlide(png=b"x", width=100, height=100, nodes=(node,))).slide
    assert ir.shapes[0].fill is None
