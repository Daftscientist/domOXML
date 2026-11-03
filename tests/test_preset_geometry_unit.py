"""Preset outlines evaluated from the ECMA-376 shape definitions."""

from __future__ import annotations

import io
import re
import zipfile

from domoxml.core.drawingml.preset_geometry import preset_geometry, preset_names
from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    ArcTo,
    Box,
    GeometryKind,
    GradientFill,
    GradientStop,
    Line,
    LineTo,
    MoveTo,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_UNIT = 9525


def test_every_one_of_the_187_presets_has_an_outline() -> None:
    names = preset_names()

    assert len(names) == 187
    assert [n for n in names if preset_geometry(n, 2_000_000, 1_000_000)[0] is None] == []


def test_donut_is_two_rings_of_arcs_and_adjust_changes_the_hole() -> None:
    thin, _ = preset_geometry("donut", 1_000_000, 1_000_000, {"adj": 10_000})
    thick, _ = preset_geometry("donut", 1_000_000, 1_000_000, {"adj": 40_000})

    assert thin is not None and thick is not None
    assert sum(isinstance(c, MoveTo) for c in thin.path) == 2
    thin_inner = [c for c in thin.path if isinstance(c, ArcTo)][-1].width_radius
    thick_inner = [c for c in thick.path if isinstance(c, ArcTo)][-1].width_radius
    assert thin_inner > thick_inner  # a thicker ring leaves a smaller hole


def test_a_line_has_one_stroke_segment_even_with_no_height() -> None:
    geometry, complete = preset_geometry("line", 1_000_000, 0)

    assert complete and geometry is not None
    assert [type(c) for c in geometry.path] == [MoveTo, LineTo]


def test_zero_radius_corners_draw_a_sharp_corner() -> None:
    geometry, _ = preset_geometry("round2SameRect", 1_000_000, 500_000, {"adj1": 0, "adj2": 0})

    assert geometry is not None
    assert not any(isinstance(c, ArcTo) for c in geometry.path)


def test_presets_the_ir_cannot_name_read_back_as_native_outlines_and_reach_html() -> None:
    valid = set(GeometryKind.__args__)  # type: ignore[attr-defined]
    assert "donut" not in valid
    shape = ShapeNode(
        box=Box(x=100 * _UNIT, y=100 * _UNIT, width=200 * _UNIT, height=120 * _UNIT),
        geom="rect",
        fill=SolidFill(color=Rgba(r=40, g=100, b=200)),
        line=Line(color=Rgba(r=10, g=30, b=80), width_emu=19_050),
    )
    source = build_pptx(
        [SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(shape,))], faces=[]
    )
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = re.sub(rb'prst="rect"', b'prst="donut"', data)
            zout.writestr(item, data)

    result = read_pptx_result(patched.getvalue())

    [read_shape] = result.slides[0].contents
    assert isinstance(read_shape, ShapeNode) and read_shape.custom_geom is not None
    [item] = result.coverage.items
    assert item.representation.value == "native"
    html = pptx_to_html(patched.getvalue()).slides[0].html
    assert "clip-path" in html or "<svg" in html or "<path" in html
    assert serialize_canvas(list(result.slides)).slides[0].html


def _preset_deck(prst: str, **shape_fields: object) -> bytes:
    shape = ShapeNode(
        box=Box(x=100 * _UNIT, y=100 * _UNIT, width=200 * _UNIT, height=120 * _UNIT),
        geom="rect",
        **shape_fields,  # type: ignore[arg-type]
    )
    source = build_pptx(
        [SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(shape,))], faces=[]
    )
    patched = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                data = re.sub(rb'prst="rect"', f'prst="{prst}"'.encode(), data)
            zout.writestr(item, data)
    return patched.getvalue()


_BLUE = SolidFill(color=Rgba(r=40, g=100, b=200))
_GRADIENT = GradientFill(
    stops=(
        GradientStop(pos=0, color=Rgba(r=40, g=100, b=200)),
        GradientStop(pos=1, color=Rgba(r=200, g=40, b=100)),
    ),
    angle_deg=90,
)
_WORDS = TextBody(
    paragraphs=(
        TextParagraph(
            runs=(
                TextRun(
                    text="Label", font_family="Arial", size_pt=18, color=Rgba(r=255, g=255, b=255)
                ),
            )
        ),
    )
)


def test_a_preset_with_text_keeps_its_text_instead_of_an_svg_outline() -> None:
    deck = _preset_deck("flowChartPunchedTape", fill=_BLUE, text=_WORDS)

    result = read_pptx_result(deck)

    [shape] = result.slides[0].contents
    assert isinstance(shape, ShapeNode) and shape.custom_geom is None
    assert "Label" in pptx_to_html(deck).slides[0].html


def test_a_rotated_stroked_preset_keeps_its_rotation_in_html() -> None:
    deck = _preset_deck(
        "donut",
        fill=_BLUE,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        transform=Transform(rotation_deg=30),
    )

    html = pptx_to_html(deck).slides[0].html

    assert "rotate(30deg)" in html and "<svg" in html


async def test_a_curved_preset_clip_survives_chrome_and_extracts_without_a_raster() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.ir.model import PictureFill
    from domoxml.core.render import BrowserSession

    html = pptx_to_html(_preset_deck("flowChartPunchedTape", fill=_GRADIENT))
    page = f"<body style='margin:0'>{html.slides[0].html}</body>"
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    result = extract_slide(rendered)

    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    assert any(s.custom_geom is not None for s in result.slide.shapes)
