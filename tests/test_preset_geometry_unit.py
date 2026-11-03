"""Preset outlines evaluated from the ECMA-376 shape definitions."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from PIL import Image

from domoxml.core.drawingml.preset_geometry import preset_geometry, preset_names
from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    ArcTo,
    Box,
    ClosePath,
    GeometryKind,
    GradientFill,
    GradientStop,
    Line,
    LineTo,
    MoveTo,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.core.roundtrip import inline_assets
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


def test_a_preset_with_text_keeps_both_its_outline_and_its_text_in_html() -> None:
    deck = _preset_deck(
        "flowChartPunchedTape",
        fill=_BLUE,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        text=_WORDS,
    )

    result = read_pptx_result(deck)

    [shape] = result.slides[0].contents
    assert isinstance(shape, ShapeNode) and shape.custom_geom is not None and shape.text
    html = pptx_to_html(deck).slides[0].html
    assert "Label" in html and "<svg" in html


def test_a_gradient_preset_with_a_stroke_and_text_keeps_gradient_outline_and_text() -> None:
    deck = _preset_deck(
        "flowChartPunchedTape",
        fill=_GRADIENT,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        text=_WORDS,
    )

    [shape] = read_pptx_result(deck).slides[0].contents
    html = pptx_to_html(deck).slides[0].html

    assert isinstance(shape, ShapeNode) and shape.custom_geom is not None
    assert isinstance(shape.fill, GradientFill)
    assert "<linearGradient" in html and "url(#grad-" in html and "Label" in html


@pytest.mark.integration
async def test_a_gradient_outline_extracts_back_to_a_gradient_shape() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.render import BrowserSession

    deck = _preset_deck(
        "flowChartPunchedTape",
        fill=_GRADIENT,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
    )
    page = f"<body style='margin:0'>{pptx_to_html(deck).slides[0].html}</body>"
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    shapes = extract_slide(rendered).slide.shapes

    assert any(isinstance(s.fill, GradientFill) and s.custom_geom is not None for s in shapes)


@pytest.mark.integration
async def test_a_preset_with_text_extracts_as_an_outline_beneath_its_text() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.render import BrowserSession

    deck = _preset_deck(
        "flowChartPunchedTape",
        fill=_BLUE,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        text=_WORDS,
    )
    page = f"<body style='margin:0'>{pptx_to_html(deck).slides[0].html}</body>"
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    shapes = extract_slide(rendered).slide.shapes

    outline = next(i for i, s in enumerate(shapes) if s.custom_geom is not None)
    words = next(i for i, s in enumerate(shapes) if s.text)
    assert outline < words


def test_a_rotated_stroked_preset_keeps_its_rotation_in_html() -> None:
    deck = _preset_deck(
        "donut",
        fill=_BLUE,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        transform=Transform(rotation_deg=30),
    )

    html = pptx_to_html(deck).slides[0].html

    assert "rotate(30deg)" in html and "<svg" in html


@pytest.mark.integration
async def test_a_curved_preset_clip_survives_chrome_and_extracts_without_a_raster() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.render import BrowserSession

    html = pptx_to_html(_preset_deck("flowChartPunchedTape", fill=_GRADIENT))
    page = f"<body style='margin:0'>{html.slides[0].html}</body>"
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    result = extract_slide(rendered)

    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    assert any(s.custom_geom is not None for s in result.slide.shapes)


def test_an_arc_with_one_zero_radius_is_a_straight_run_not_nothing() -> None:
    from xml.etree.ElementTree import fromstring

    from domoxml.core.drawingml.preset_geometry import _path_commands  # pyright: ignore

    path = fromstring(
        '<path><moveTo><pt x="0" y="0"/></moveTo>'
        '<arcTo wR="0" hR="1000" stAng="0" swAng="5400000"/><close/></path>'
    )

    commands = _path_commands(path, {}, (1.0, 1.0))

    assert [type(c) for c in commands] == [MoveTo, LineTo, ClosePath]
    assert isinstance(commands[1], LineTo) and commands[1].to.y == 1000


def test_a_flipped_preset_keeps_its_text_readable_in_html() -> None:
    deck = _preset_deck(
        "flowChartPunchedTape",
        fill=_BLUE,
        text=_WORDS,
        transform=Transform(flip_h=True),
    )

    html = pptx_to_html(deck).slides[0].html

    assert 'style="transform:scaleX(-1)"' in html


def test_a_faded_preset_with_text_is_not_faded_twice() -> None:
    deck = _preset_deck("flowChartPunchedTape", fill=_BLUE, text=_WORDS, opacity=0.5)

    html = pptx_to_html(deck).slides[0].html

    assert "opacity:0.5" not in html
    assert "rgba(40,100,200,0.5)" in html


def test_a_stroked_polygon_preset_is_an_svg_outline_so_its_stroke_is_drawn() -> None:
    stroked = ShapeNode(
        box=Box(x=100 * _UNIT, y=100 * _UNIT, width=200 * _UNIT, height=200 * _UNIT),
        geom="star5",
        fill=_BLUE,
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
    )
    plain = stroked.model_copy(update={"line": None})
    slide = SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(stroked,))

    html = serialize_canvas([slide]).slides[0].html
    unstroked = serialize_canvas([slide.model_copy(update={"contents": (plain,)})]).slides[0].html

    assert "<svg" in html and "stroke-width" in html and "clip-path" not in html
    assert "clip-path:polygon" in unstroked


def test_a_picture_filled_stroked_polygon_keeps_its_clipped_div() -> None:
    from domoxml.core.ir.model import PictureFill

    picture = ShapeNode(
        box=Box(x=100 * _UNIT, y=100 * _UNIT, width=200 * _UNIT, height=200 * _UNIT),
        geom="star5",
        fill=PictureFill(data=b"x", ext="png"),
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
    )

    html = (
        serialize_canvas([SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=(picture,))])
        .slides[0]
        .html
    )

    assert "clip-path:polygon" in html and "<svg" not in html


def test_gradients_that_differ_only_in_opacity_get_different_ids() -> None:
    outline, _ = preset_geometry("heart", 200 * _UNIT, 200 * _UNIT)
    box = Box(x=100 * _UNIT, y=100 * _UNIT, width=200 * _UNIT, height=200 * _UNIT)
    line = Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050)
    shapes = tuple(
        ShapeNode(
            box=box, geom="rect", custom_geom=outline, fill=_GRADIENT, line=line, opacity=opacity
        )
        for opacity in (1.0, 0.5)
    )

    html = (
        serialize_canvas([SlideIR(width=1280 * _UNIT, height=720 * _UNIT, contents=shapes)])
        .slides[0]
        .html
    )

    assert len(set(re.findall(r'<linearGradient id="(grad-[0-9a-f]+)"', html))) == 2


def _picture() -> PictureFill:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "#c20").save(out, "PNG")
    return PictureFill(data=out.getvalue(), ext="png")


def test_a_picture_filled_preset_with_stroke_and_text_is_three_layers_in_html() -> None:
    deck = _preset_deck(
        "heart",
        fill=_picture(),
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        text=_WORDS,
    )

    [shape] = read_pptx_result(deck).slides[0].contents
    html = pptx_to_html(deck).slides[0].html

    assert isinstance(shape, ShapeNode) and shape.custom_geom is not None
    assert html.count("clip-path:path(") == 1  # the picture, clipped to the outline
    assert "<svg" in html and "stroke-width" in html and 'fill="none"' in html
    assert "Label" in html


@pytest.mark.integration
async def test_picture_stroke_and_text_layers_extract_to_native_shapes() -> None:
    from domoxml.core.ir import extract_slide
    from domoxml.core.render import BrowserSession

    deck = _preset_deck(
        "heart",
        fill=_picture(),
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
        text=_WORDS,
    )
    html = inline_assets(pptx_to_html(deck)).slides[0].html
    async with BrowserSession() as session:
        rendered = await session.render(
            f"<body style='margin:0'>{html}</body>", width=1280, height=720
        )

    shapes = extract_slide(rendered).slide.shapes

    assert any(isinstance(s.fill, PictureFill) and s.custom_geom is not None for s in shapes)
    assert any(s.line is not None and s.custom_geom is not None for s in shapes)
    assert any(s.text for s in shapes)


def test_a_picture_outline_that_leaves_its_box_keeps_its_rectangle() -> None:
    deck = _preset_deck(
        "wedgeRoundRectCallout",
        fill=_picture(),
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=19_050),
    )

    result = read_pptx_result(deck)

    [shape] = result.slides[0].contents
    assert isinstance(shape, ShapeNode) and shape.custom_geom is None
    [item] = result.coverage.items
    assert item.representation.value == "approximated"
