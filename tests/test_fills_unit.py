"""Unit tests for pattern-fill matching/emission and shape blipFill crop (fwd + rev)."""

# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

import warnings

import pytest

from domoxml.core.drawingml.shape import shape_xml
from domoxml.core.fillcrop import (
    contain_fill_fractions,
    cover_crop_fractions,
    explicit_fill_fractions,
    srcrect_to_background,
)
from domoxml.core.ir.model import Box, PatternFill, PictureFill, Rgba, ShapeNode, SrcRect
from domoxml.core.ir.pattern import match_pattern_fill, pattern_to_css


def _rlg(angle: int, fg: str, bg: str, width: int) -> str:
    return (
        f"repeating-linear-gradient({angle}deg,{fg} 0px,{fg} {width}px,"
        f"{bg} {width}px,{bg} {width * 2}px)"
    )


# --------------------------------------------------------------------------- forward matcher


@pytest.mark.parametrize(
    ("angle", "width", "preset"),
    [
        (0, 12, "horz"),
        (180, 12, "horz"),
        (90, 12, "vert"),
        (270, 12, "vert"),
        (45, 3, "ltUpDiag"),
        (45, 10, "wdUpDiag"),
        (135, 3, "ltDnDiag"),
        (135, 10, "dkUpDiag"),
    ],
)
def test_match_pattern_positive_by_angle_and_width(angle: int, width: int, preset: str) -> None:
    fill = match_pattern_fill(_rlg(angle, "rgb(10,10,10)", "rgb(240,240,240)", width))
    assert fill is not None
    assert fill.preset == preset
    assert fill.fg == Rgba(r=10, g=10, b=10)
    assert fill.bg == Rgba(r=240, g=240, b=240)


def test_thin_threshold_is_four_px() -> None:
    assert match_pattern_fill(_rlg(45, "rgb(0,0,0)", "rgb(1,1,1)", 4)).preset == "ltUpDiag"  # type: ignore[union-attr]
    assert match_pattern_fill(_rlg(45, "rgb(0,0,0)", "rgb(1,1,1)", 5)).preset == "wdUpDiag"  # type: ignore[union-attr]


def test_match_pattern_negative_three_colors() -> None:
    css = (
        "repeating-linear-gradient(45deg,rgb(1,1,1) 0px,rgb(1,1,1) 3px,"
        "rgb(2,2,2) 3px,rgb(2,2,2) 6px,rgb(3,3,3) 6px,rgb(3,3,3) 9px)"
    )
    assert match_pattern_fill(css) is None


def test_match_pattern_negative_soft_stops() -> None:
    # A plain two-colour gradient with no hard stops is not a stripe pattern.
    assert match_pattern_fill("repeating-linear-gradient(45deg,rgb(1,1,1),rgb(2,2,2))") is None


def test_match_pattern_negative_off_axis_angle() -> None:
    assert match_pattern_fill(_rlg(30, "rgb(1,1,1)", "rgb(2,2,2)", 3)) is None


def test_match_pattern_negative_unequal_bands() -> None:
    css = (
        "repeating-linear-gradient(0deg,rgb(1,1,1) 0px,rgb(1,1,1) 3px,"
        "rgb(2,2,2) 3px,rgb(2,2,2) 10px)"
    )
    assert match_pattern_fill(css) is None


def test_match_pattern_negative_not_repeating() -> None:
    assert match_pattern_fill("linear-gradient(45deg,rgb(1,1,1),rgb(2,2,2))") is None
    assert match_pattern_fill("none") is None
    assert match_pattern_fill(None) is None


# --------------------------------------------------------------------------- forward XML emission


def test_pattern_fill_xml_emission() -> None:
    node = ShapeNode(
        box=Box(x=0, y=0, width=100, height=100),
        fill=PatternFill(
            preset="ltUpDiag", fg=Rgba(r=17, g=17, b=17), bg=Rgba(r=238, g=238, b=238)
        ),
    )
    xml = shape_xml(node, shape_id=2)
    assert '<a:pattFill prst="ltUpDiag">' in xml
    assert '<a:fgClr><a:srgbClr val="111111">' in xml
    assert '<a:bgClr><a:srgbClr val="EEEEEE">' in xml
    assert "<a:noFill/>" not in xml


def test_pattern_fill_does_not_warn() -> None:
    # The historical stub warned; real emission must be silent.
    node = ShapeNode(
        box=Box(x=0, y=0, width=10, height=10),
        fill=PatternFill(preset="horz", fg=Rgba(r=0, g=0, b=0), bg=Rgba(r=255, g=255, b=255)),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        shape_xml(node, shape_id=2)


# ------------------------------------------------------------------------- reverse pattFill -> CSS


@pytest.mark.parametrize("preset", ["horz", "vert", "ltUpDiag", "wdUpDiag", "ltDnDiag", "dkUpDiag"])
def test_reverse_pattern_six_presets_round_trip(preset: str) -> None:
    prop, value, approximated = pattern_to_css("1E3A8A", "DBEAFE", preset)
    assert prop == "background"
    assert approximated is False
    # Round-trip: the emitted CSS must match back to the same preset and colours.
    matched = match_pattern_fill(value)
    assert matched is not None
    assert matched.preset == preset
    assert isinstance(matched.fg, Rgba)
    assert isinstance(matched.bg, Rgba)
    assert matched.fg.hex == "1E3A8A"
    assert matched.bg.hex == "DBEAFE"


@pytest.mark.parametrize("preset", ["diagCross", "pct50"])
def test_reverse_pattern_approximated_families_warn(preset: str) -> None:
    prop, value, approximated = pattern_to_css("000000", "FFFFFF", preset)
    assert prop == "background-image"
    assert value.startswith('url("data:image/svg+xml,')
    assert approximated is True


def test_reverse_pattern_tile_kinds_differ() -> None:
    # A dot-family and a grid-family preset must produce structurally different SVG tiles.
    _, dot_tile, _ = pattern_to_css("000000", "FFFFFF", "pct25")
    _, grid_tile, _ = pattern_to_css("000000", "FFFFFF", "cross")
    assert dot_tile != grid_tile


# --------------------------------------------------------------------------- crop fraction math


def test_cover_landscape_in_portrait() -> None:
    # 2000x1000 landscape into a 400x800 portrait box: cover scales by width (400/2000=0.2)
    # -> scaled 400x200... no: cover uses max ratio. box/img: 0.2 (w) vs 0.8 (h) -> scale 0.8.
    # scaled image = 1600x800; box shows 400 of 1600 wide -> 75% cropped horizontally, centred.
    left, top, right, bottom = cover_crop_fractions(2000, 1000, 400, 800)
    assert top == pytest.approx(0.0)
    assert bottom == pytest.approx(0.0)
    assert left == pytest.approx(0.375)
    assert right == pytest.approx(0.375)


def test_cover_portrait_in_landscape() -> None:
    # 1000x2000 portrait into 800x400 landscape: max(800/1000, 400/2000)=0.8 -> scaled 800x1600;
    # box shows 400 of 1600 tall -> 75% cropped vertically.
    left, top, right, bottom = cover_crop_fractions(1000, 2000, 800, 400)
    assert left == pytest.approx(0.0)
    assert right == pytest.approx(0.0)
    assert top == pytest.approx(0.375)
    assert bottom == pytest.approx(0.375)


def test_cover_square_in_square_no_crop() -> None:
    assert cover_crop_fractions(500, 500, 200, 200) == (0.0, 0.0, 0.0, 0.0)


def test_cover_position_left_top() -> None:
    # Same landscape-in-portrait but positioned top-left: all overflow goes to right/bottom.
    left, _top, right, _bottom = cover_crop_fractions(2000, 1000, 400, 800, pos_x=0.0, pos_y=0.0)
    assert left == pytest.approx(0.0)
    assert right == pytest.approx(0.75)


def test_contain_letterbox_fractions() -> None:
    # 2000x1000 landscape into 400x400 square via contain: scale = min(0.2, 0.4)=0.2 ->
    # scaled 400x200; vertical gap = 1 - 200/400 = 0.5, split evenly.
    left, top, right, bottom = contain_fill_fractions(2000, 1000, 400, 400)
    assert left == pytest.approx(0.0)
    assert right == pytest.approx(0.0)
    assert top == pytest.approx(0.25)
    assert bottom == pytest.approx(0.25)


def test_explicit_fill_larger_than_box_is_negative() -> None:
    # Painted 800px wide into a 400px box -> negative (outset) horizontal insets.
    left, _top, right, _bottom = explicit_fill_fractions(800, 400, 400, 400)
    assert left == pytest.approx(-0.5)
    assert right == pytest.approx(-0.5)


# --------------------------------------------------------------------------- srcRect inversion


@pytest.mark.parametrize(
    ("img_w", "img_h", "box_w", "box_h", "pos_x", "pos_y"),
    [
        (2000, 1000, 400, 400, 0.5, 0.5),
        (1000, 2000, 800, 400, 0.5, 0.5),
        (2000, 1000, 400, 800, 0.25, 0.75),
        (1600, 900, 320, 240, 0.5, 0.5),
    ],
)
def test_srcrect_inverse_is_consistent(
    img_w: int, img_h: int, box_w: int, box_h: int, pos_x: float, pos_y: float
) -> None:
    # srcrect_to_background must invert cover_crop_fractions: re-deriving the visible window from
    # the emitted background-size returns the original visible fraction.
    insets = cover_crop_fractions(img_w, img_h, box_w, box_h, pos_x=pos_x, pos_y=pos_y)
    size, _position = srcrect_to_background(insets)
    size_x, size_y = (float(token.rstrip("%")) for token in size.split())
    visible_w = 1.0 - insets[0] - insets[2]
    visible_h = 1.0 - insets[1] - insets[3]
    assert size_x == pytest.approx(100.0 / visible_w, rel=1e-3)
    assert size_y == pytest.approx(100.0 / visible_h, rel=1e-3)


def test_srcrect_no_crop_centres() -> None:
    size, position = srcrect_to_background((0.0, 0.0, 0.0, 0.0))
    assert size == "100% 100%"
    assert position == "50% 50%"


# --------------------------------------------------------------------------- blipFill crop XML


def test_blip_fill_emits_src_rect() -> None:
    node = ShapeNode(
        box=Box(x=0, y=0, width=100, height=100),
        fill=PictureFill(data=b"x", crop=SrcRect(left=0.25, right=0.25)),
    )
    xml = shape_xml(node, shape_id=3, blip_rid="rId2")
    assert '<a:srcRect l="25000" r="25000"/>' in xml
    assert "<a:stretch><a:fillRect/></a:stretch>" in xml


def test_blip_fill_without_crop_has_no_src_rect() -> None:
    node = ShapeNode(box=Box(x=0, y=0, width=100, height=100), fill=PictureFill(data=b"x"))
    xml = shape_xml(node, shape_id=3, blip_rid="rId2")
    assert "<a:srcRect" not in xml


# --------------------------------------------------------------------------- reverse read + html


def _png_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (40, 20), (100, 150, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def test_reverse_reads_pattfill_and_crop_from_pptx() -> None:
    from domoxml.core.html import serialize_canvas
    from domoxml.core.ir.model import SlideIR
    from domoxml.slides import build_pptx
    from domoxml.slides.read import read_pptx_result

    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=1_000_000, height=1_000_000),
                fill=PatternFill(
                    preset="ltUpDiag", fg=Rgba(r=30, g=58, b=138), bg=Rgba(r=219, g=234, b=254)
                ),
            ),
            ShapeNode(
                box=Box(x=2_000_000, y=0, width=1_000_000, height=1_000_000),
                fill=PatternFill(
                    preset="diagCross", fg=Rgba(r=0, g=0, b=0), bg=Rgba(r=255, g=255, b=255)
                ),
            ),
            ShapeNode(
                box=Box(x=4_000_000, y=0, width=1_000_000, height=1_000_000),
                fill=PictureFill(data=_png_bytes(), ext="png", crop=SrcRect(left=0.25, right=0.25)),
            ),
        ),
    )
    result = read_pptx_result(build_pptx([slide]))
    fills = [shape.fill for shape in result.slides[0].shapes]
    patterns = [f for f in fills if isinstance(f, PatternFill)]
    pictures = [f for f in fills if isinstance(f, PictureFill)]
    assert {p.preset for p in patterns} == {"ltUpDiag", "diagCross"}
    assert pictures and pictures[0].crop is not None
    assert pictures[0].crop.left == pytest.approx(0.25)

    html = serialize_canvas(list(result.slides), warnings=result.warnings)
    slide_html = html.slides[0].html
    assert "repeating-linear-gradient" in slide_html  # exact preset
    assert "data:image/svg" in slide_html  # approximated preset
    assert "background-size:200% 100%" in slide_html  # inverted crop
    assert any("pattFill" in w.message and "diagCross" in w.message for w in html.warnings)
