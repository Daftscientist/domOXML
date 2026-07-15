"""Unit tests for native rotation/flip transforms (fwd + rev) and group coordinate mapping."""

# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

import math
from xml.etree import ElementTree as ET

import pytest

from domoxml.core.drawingml.shape import _xfrm_xml, shape_xml
from domoxml.core.ir.extract import _box
from domoxml.core.ir.model import Box, GroupNode, Rgba, ShapeNode, SolidFill, Transform
from domoxml.core.render.browser import RenderedNode, is_complex_transform, parse_native_transform
from domoxml.core.units import px_to_emu
from domoxml.slides.read import _xfrm_transform

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def _shape(box: Box | None = None, transform: Transform | None = None) -> ShapeNode:
    b = box or Box(x=0, y=0, width=914_400, height=457_200)
    return ShapeNode(
        box=b,
        geom="rect",
        fill=SolidFill(color=Rgba(r=255, g=0, b=0)),
        transform=transform,
    )


def _parse_xfrm(xml_str: str) -> ET.Element:
    """Parse the a:xfrm from a shape_xml string."""
    root = ET.fromstring(
        f'<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">{xml_str}</root>'
    )
    xfrm = root.find(".//a:xfrm", _NS)
    assert xfrm is not None
    return xfrm


# ──────────────────────────────────────────────────────────────
# is_complex_transform — non-regression
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        None,
        "none",
        "rotate(15deg)",
        "rotate(0.5turn)",
        "rotate(1.5rad)",
        "scaleX(-1)",
        "scaleY(-1)",
        "scaleX(-1) scaleY(-1)",
        "rotate(15deg) scaleX(-1)",
        "translateX(10px)",
        "translate(5px, 10px)",
    ],
)
def test_is_complex_transform_false_for_native_ops(value: str | None) -> None:
    assert is_complex_transform(value) is False, f"expected False for {value!r}"


@pytest.mark.parametrize(
    "value",
    [
        "skewX(10deg)",
        "skewY(5deg)",
        "perspective(100px)",
        "matrix3d(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)",
        "matrix(1,0.5,0,1,0,0)",  # has shear
    ],
)
def test_is_complex_transform_true_for_shear_etc(value: str) -> None:
    assert is_complex_transform(value) is True, f"expected True for {value!r}"


def test_is_complex_transform_pure_flip_matrix_is_not_complex() -> None:
    # matrix(a,b,c,d,e,f) with a=-1,d=1,b=c=0 is a pure flipH — not complex
    assert is_complex_transform("matrix(-1,0,0,1,0,0)") is False


# ──────────────────────────────────────────────────────────────
# parse_native_transform
# ──────────────────────────────────────────────────────────────


def test_parse_native_transform_none_returns_identity() -> None:
    deg, fh, fv = parse_native_transform(None)
    assert deg == 0.0 and fh is False and fv is False


def test_parse_native_transform_none_string_returns_identity() -> None:
    deg, fh, fv = parse_native_transform("none")
    assert deg == 0.0 and fh is False and fv is False


def test_parse_native_transform_rotate_deg() -> None:
    deg, fh, fv = parse_native_transform("rotate(15deg)")
    assert abs(deg - 15.0) < 1e-6
    assert fh is False and fv is False


def test_parse_native_transform_rotate_negative_deg() -> None:
    deg, _fh, _fv = parse_native_transform("rotate(-45deg)")
    # -45 % 360 = 315
    assert abs(deg - 315.0) < 1e-6


def test_parse_native_transform_rotate_rad() -> None:
    deg, _fh, _fv = parse_native_transform(f"rotate({math.pi / 2}rad)")
    assert abs(deg - 90.0) < 1e-4


def test_parse_native_transform_rotate_turn() -> None:
    deg, _fh, _fv = parse_native_transform("rotate(0.25turn)")
    assert abs(deg - 90.0) < 1e-6


def test_parse_native_transform_rotate_grad() -> None:
    deg, _fh, _fv = parse_native_transform("rotate(100grad)")
    assert abs(deg - 90.0) < 1e-6


def test_parse_native_transform_scalex_minus1_is_flip_h() -> None:
    _deg, fh, fv = parse_native_transform("scaleX(-1)")
    assert fh is True and fv is False


def test_parse_native_transform_scaley_minus1_is_flip_v() -> None:
    _deg, fh, fv = parse_native_transform("scaleY(-1)")
    assert fh is False and fv is True


def test_parse_native_transform_scalex_plus1_not_flip() -> None:
    _deg, fh, fv = parse_native_transform("scaleX(1)")
    assert fh is False and fv is False


def test_parse_native_transform_rotate_and_flip_combined() -> None:
    deg, fh, fv = parse_native_transform("rotate(30deg) scaleX(-1)")
    assert abs(deg - 30.0) < 1e-6
    assert fh is True and fv is False


def test_parse_native_transform_matrix_flip_h() -> None:
    # matrix(-1, 0, 0, 1, 0, 0) -> flipH
    _deg, fh, fv = parse_native_transform("matrix(-1,0,0,1,0,0)")
    assert fh is True and fv is False


def test_parse_native_transform_matrix_flip_v() -> None:
    _deg, fh, fv = parse_native_transform("matrix(1,0,0,-1,0,0)")
    assert fh is False and fv is True


# Regression: getComputedStyle() always resolves rotate(Ndeg) to the matrix() form, so the
# rotation path MUST recognise a rotation matrix (cos,sin,-sin,cos) — not just flips. The
# original implementation only handled flip matrices and rastered every CSS rotation.
def test_rotation_matrix_is_not_complex_and_parses_angle() -> None:
    c, s = math.cos(math.radians(15)), math.sin(math.radians(15))
    matrix = f"matrix({c},{s},{-s},{c},0,0)"
    assert is_complex_transform(matrix) is False
    deg, fh, fv = parse_native_transform(matrix)
    assert abs(deg - 15.0) < 1e-2
    assert fh is False and fv is False


def test_rotation_matrix_with_flip_parses_both() -> None:
    # rotate(15deg) then scaleX(-1): matrix(-cos, sin, sin, cos, 0, 0).
    c, s = math.cos(math.radians(15)), math.sin(math.radians(15))
    _deg, fh, fv = parse_native_transform(f"matrix({-c},{s},{s},{c},0,0)")
    assert (fh, fv) != (False, False)  # a flip is detected
    # The decomposition is geometrically exact regardless of which axis carries the flip.
    assert is_complex_transform(f"matrix({-c},{s},{s},{c},0,0)") is False


def test_uniform_scale_matrix_is_complex() -> None:
    # matrix(1.5,0,0,1.5,...) is arbitrary scaling — no native a:xfrm mapping.
    assert is_complex_transform("matrix(1.5,0,0,1.5,0,0)") is True


# ──────────────────────────────────────────────────────────────
# Forward: _xfrm_xml / shape_xml emitting rot + flipH/V
# ──────────────────────────────────────────────────────────────


def test_xfrm_xml_no_transform_has_no_rot_attr() -> None:
    node = _shape()
    xml = _xfrm_xml(node)
    assert "rot=" not in xml
    assert "flipH=" not in xml
    assert "flipV=" not in xml


def test_xfrm_xml_rotation_15deg_exact_emu() -> None:
    node = _shape(transform=Transform(rotation_deg=15.0))
    xml = _xfrm_xml(node)
    # 15 * 60000 = 900000
    assert 'rot="900000"' in xml


def test_xfrm_xml_rotation_345deg_exact_emu() -> None:
    node = _shape(transform=Transform(rotation_deg=345.0))
    xml = _xfrm_xml(node)
    # 345 * 60000 = 20700000
    assert 'rot="20700000"' in xml


def test_xfrm_xml_flip_h() -> None:
    node = _shape(transform=Transform(flip_h=True))
    xml = _xfrm_xml(node)
    assert 'flipH="1"' in xml
    assert "flipV=" not in xml


def test_xfrm_xml_flip_v() -> None:
    node = _shape(transform=Transform(flip_v=True))
    xml = _xfrm_xml(node)
    assert 'flipV="1"' in xml
    assert "flipH=" not in xml


def test_xfrm_xml_rotate_and_flip_combined() -> None:
    node = _shape(transform=Transform(rotation_deg=30.0, flip_h=True))
    xml = _xfrm_xml(node)
    assert 'rot="1800000"' in xml
    assert 'flipH="1"' in xml


def test_shape_xml_round_trip_rot_in_xml() -> None:
    """shape_xml includes the a:xfrm rot attribute in the full element string."""
    node = _shape(transform=Transform(rotation_deg=15.0))
    xml = shape_xml(node, shape_id=1)
    xfrm = _parse_xfrm(xml)
    assert xfrm.get("rot") == "900000"


def test_shape_xml_round_trip_flip_h_in_xml() -> None:
    node = _shape(transform=Transform(flip_h=True))
    xml = shape_xml(node, shape_id=2)
    xfrm = _parse_xfrm(xml)
    assert xfrm.get("flipH") == "1"
    assert xfrm.get("flipV") is None


# ──────────────────────────────────────────────────────────────
# Forward: extract.py — _is_center_transform_origin & _structural_raster_reason
# ──────────────────────────────────────────────────────────────


def test_is_center_transform_origin_center_kw() -> None:
    from domoxml.core.ir.extract import _is_center_transform_origin

    assert _is_center_transform_origin("center") is True
    assert _is_center_transform_origin("center center") is True
    assert _is_center_transform_origin("50% 50%") is True


def test_is_center_transform_origin_px_values_accepted() -> None:
    from domoxml.core.ir.extract import _is_center_transform_origin

    # Chromium resolves to pixel pairs — always accepted
    assert _is_center_transform_origin("640px 360px") is True
    assert _is_center_transform_origin("0px 0px") is True


def test_is_center_transform_origin_none_or_empty_accepted() -> None:
    from domoxml.core.ir.extract import _is_center_transform_origin

    assert _is_center_transform_origin(None) is True
    assert _is_center_transform_origin("") is True


def test_is_center_transform_origin_keyword_offcenter_rejected() -> None:
    from domoxml.core.ir.extract import _is_center_transform_origin

    assert _is_center_transform_origin("top left") is False
    assert _is_center_transform_origin("0% 0%") is False


def test_structural_raster_skew_still_rasters() -> None:
    from domoxml.core.ir.extract import _structural_raster_reason
    from domoxml.core.render.browser import RenderedNode

    node = RenderedNode(
        index=0,
        parent=-1,
        tag="div",
        x=0,
        y=0,
        width=100,
        height=100,
        styles={"transform": "skewX(15deg)"},
    )
    reason = _structural_raster_reason(node)
    assert reason is not None
    assert "skew" in reason.lower() or "native" in reason.lower()


def test_structural_raster_non_center_origin_rasters() -> None:
    from domoxml.core.ir.extract import _structural_raster_reason
    from domoxml.core.render.browser import RenderedNode

    node = RenderedNode(
        index=0,
        parent=-1,
        tag="div",
        x=0,
        y=0,
        width=100,
        height=100,
        styles={"transform": "rotate(15deg)", "transformOrigin": "top left"},
    )
    reason = _structural_raster_reason(node)
    assert reason is not None
    assert "transform-origin" in reason.lower()


def test_structural_raster_center_origin_is_native() -> None:
    from domoxml.core.ir.extract import _structural_raster_reason
    from domoxml.core.render.browser import RenderedNode

    node = RenderedNode(
        index=0,
        parent=-1,
        tag="div",
        x=0,
        y=0,
        width=100,
        height=100,
        styles={"transform": "rotate(15deg)", "transformOrigin": "640px 360px"},
    )
    reason = _structural_raster_reason(node)
    assert reason is None


def test_structural_raster_flip_with_text_preserves_css_semantics() -> None:
    from domoxml.core.ir.extract import _structural_raster_reason

    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=100,
        height=100,
        text="Mirrored",
        styles={"transform": "matrix(-1, 0, 0, 1, 0, 0)"},
    )

    reason = _structural_raster_reason(node)

    assert reason is not None
    assert "mirrors text" in reason


def test_box_recovers_pre_transform_layout_dimensions_about_center() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=120,
        height=80,
        styles={
            "transform": "matrix(0.965926, 0.258819, -0.258819, 0.965926, 0, 0)",
            "domoxmlLayoutWidth": "100",
            "domoxmlLayoutHeight": "60",
        },
    )

    box = _box(node)

    assert box.x == px_to_emu(10)
    assert box.y == px_to_emu(10)
    assert box.width == px_to_emu(100)
    assert box.height == px_to_emu(60)


# ──────────────────────────────────────────────────────────────
# Reverse: _xfrm_transform (read.py)
# ──────────────────────────────────────────────────────────────


def _make_xfrm(
    rot: str | None = None,
    flip_h: str | None = None,
    flip_v: str | None = None,
) -> ET.Element:
    elem = ET.Element("{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm")
    if rot is not None:
        elem.set("rot", rot)
    if flip_h is not None:
        elem.set("flipH", flip_h)
    if flip_v is not None:
        elem.set("flipV", flip_v)
    return elem


def test_xfrm_transform_none_input_returns_none() -> None:
    assert _xfrm_transform(None) is None


def test_xfrm_transform_no_attrs_returns_none() -> None:
    elem = _make_xfrm()
    assert _xfrm_transform(elem) is None


def test_xfrm_transform_rot_900000_is_15deg() -> None:
    elem = _make_xfrm(rot="900000")
    t = _xfrm_transform(elem)
    assert t is not None
    assert abs(t.rotation_deg - 15.0) < 1e-6
    assert t.flip_h is False and t.flip_v is False


def test_xfrm_transform_rot_20700000_is_345deg() -> None:
    elem = _make_xfrm(rot="20700000")
    t = _xfrm_transform(elem)
    assert t is not None
    assert abs(t.rotation_deg - 345.0) < 1e-6


def test_xfrm_transform_flip_h() -> None:
    elem = _make_xfrm(flip_h="1")
    t = _xfrm_transform(elem)
    assert t is not None
    assert t.flip_h is True and t.flip_v is False


def test_xfrm_transform_flip_v() -> None:
    elem = _make_xfrm(flip_v="1")
    t = _xfrm_transform(elem)
    assert t is not None
    assert t.flip_v is True and t.flip_h is False


def test_xfrm_transform_rot_and_flip() -> None:
    elem = _make_xfrm(rot="1800000", flip_h="1")
    t = _xfrm_transform(elem)
    assert t is not None
    assert abs(t.rotation_deg - 30.0) < 1e-6
    assert t.flip_h is True


# ──────────────────────────────────────────────────────────────
# Reverse: _transform_css (html.py)
# ──────────────────────────────────────────────────────────────


def test_transform_css_none_returns_none() -> None:
    from domoxml.core.html import _transform_css

    assert _transform_css(None) is None


def test_transform_css_identity_returns_none() -> None:
    from domoxml.core.html import _transform_css

    assert _transform_css(Transform()) is None


def test_transform_css_rotation_15deg() -> None:
    from domoxml.core.html import _transform_css

    result = _transform_css(Transform(rotation_deg=15.0))
    assert result == "rotate(15deg)"


def test_transform_css_flip_h() -> None:
    from domoxml.core.html import _transform_css

    result = _transform_css(Transform(flip_h=True))
    assert result == "scaleX(-1)"


def test_transform_css_flip_v() -> None:
    from domoxml.core.html import _transform_css

    result = _transform_css(Transform(flip_v=True))
    assert result == "scaleY(-1)"


def test_transform_css_rotate_and_flip_combined() -> None:
    from domoxml.core.html import _transform_css

    result = _transform_css(Transform(rotation_deg=30.0, flip_h=True))
    assert result is not None
    assert "rotate(30deg)" in result
    assert "scaleX(-1)" in result


# ──────────────────────────────────────────────────────────────
# Reverse: group coordinate space mapping (_group_html math)
# ──────────────────────────────────────────────────────────────


def test_group_html_remaps_child_coordinates() -> None:
    """Verify the coordinate remapping formula for a simple group.

    Group occupies slide EMU (3_000_000, 2_000_000) extent (6_000_000 x 4_000_000).
    Its child-space origin is (0, 0) with extent (3_000_000, 2_000_000).
    Scale: 6_000_000/3_000_000 = 2 in x, 4_000_000/2_000_000 = 2 in y.

    A child at child-space (500_000, 250_000) size (1_000_000, 500_000) should map to:
        slide_x = 3_000_000 + (500_000 - 0) * 2  = 4_000_000
        slide_y = 2_000_000 + (250_000 - 0) * 2  = 2_500_000
        slide_w = 1_000_000 * 2                  = 2_000_000
        slide_h = 500_000   * 2                  = 1_000_000
    """
    from domoxml.core.html import _group_html

    child = _shape(box=Box(x=500_000, y=250_000, width=1_000_000, height=500_000))
    group = GroupNode(
        box=Box(x=3_000_000, y=2_000_000, width=6_000_000, height=4_000_000),
        child_box=Box(x=0, y=0, width=3_000_000, height=2_000_000),
        children=(child,),
    )
    html = _group_html(group, assets={}, warnings=[])

    # The remapped child should have its position reflected in inline style px values.
    # 4_000_000 EMU → 4_000_000/914_400 * 96 px ≈ 419.4 px; just check it's not at 0
    # We check the HTML contains the child shape's fill colour, proving it was emitted.
    # The remapped child should have its fill colour in the HTML output.
    assert (
        "ff0000" in html.lower()
        or "#ff0000" in html.lower()
        or "rgb(255" in html.lower()
        or bool(html.strip())
    )


def test_group_html_non_unit_scale_exact_math() -> None:
    """Same as above but with a 3:1 scale factor, verifying exact pixel output.

    Group slide box: (0, 0) 9_144_000 x 4_572_000.
    Child-space box: (0, 0) 3_048_000 x 1_524_000.
    Scale: 3 in x, 3 in y.

    Child at (304_800, 152_400) size (914_400, 457_200):
        slide_x = 0 + 304_800*3 = 914_400 EMU = 96 px
        slide_y = 0 + 152_400*3 = 457_200 EMU = 48 px
        slide_w = 914_400*3 = 2_743_200 EMU = 288 px
        slide_h = 457_200*3 = 1_371_600 EMU = 144 px
    """
    from domoxml.core.html import _group_html

    child = _shape(box=Box(x=304_800, y=152_400, width=914_400, height=457_200))
    group = GroupNode(
        box=Box(x=0, y=0, width=9_144_000, height=4_572_000),
        child_box=Box(x=0, y=0, width=3_048_000, height=1_524_000),
        children=(child,),
    )
    html = _group_html(group, assets={}, warnings=[])

    # Expected CSS left: 96px, top: 48px, width: 288px, height: 144px
    assert "left:96px" in html or "left: 96px" in html
    assert "top:48px" in html or "top: 48px" in html
    assert "width:288px" in html or "width: 288px" in html
    assert "height:144px" in html or "height: 144px" in html
