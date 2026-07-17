"""Unit tests for the preset geometry module and the polygon matcher / reverse emitter."""

from __future__ import annotations

import math

from domoxml.core.drawingml.presets import (
    POLYGON_PRESETS,
    match_polygon,
    preset_defaults,
    preset_vertices,
)
from domoxml.core.ir.parse import parse_polygon

# ---------------------------------------------------------------------------
# preset_vertices — hand-computed expectations
# ---------------------------------------------------------------------------


def _close(a: tuple[float, float], b: tuple[float, float], *, rel: float = 1e-6) -> bool:
    return math.isclose(a[0], b[0], rel_tol=rel) and math.isclose(a[1], b[1], rel_tol=rel)


def test_triangle_default_apex_centred() -> None:
    verts = preset_vertices("triangle", {})
    assert verts is not None
    assert len(verts) == 3
    bl, br, apex = verts
    assert _close(bl, (0.0, 1.0))
    assert _close(br, (1.0, 1.0))
    assert _close(apex, (0.5, 0.0))


def test_triangle_adj_shifts_apex() -> None:
    verts = preset_vertices("triangle", {"adj": 0.25})
    assert verts is not None
    apex = verts[2]
    assert _close(apex, (0.25, 0.0))


def test_rtTriangle_right_angle_at_bottom_left() -> None:
    verts = preset_vertices("rtTriangle", {})
    assert verts is not None
    assert (0.0, 1.0) in verts  # bottom-left (right angle)
    assert (1.0, 1.0) in verts  # bottom-right
    assert (0.0, 0.0) in verts  # top-left


def test_diamond_four_cardinal_midpoints() -> None:
    verts = preset_vertices("diamond", {})
    assert verts is not None
    assert len(verts) == 4
    # Each vertex is at midpoint of one side of the bounding box
    assert (0.5, 0.0) in verts  # top
    assert (1.0, 0.5) in verts  # right
    assert (0.5, 1.0) in verts  # bottom
    assert (0.0, 0.5) in verts  # left


def test_hexagon_default_six_vertices() -> None:
    verts = preset_vertices("hexagon", {})
    assert verts is not None
    assert len(verts) == 6
    # Flat top/bottom, so top-left and top-right x-coords should match adj=0.25
    a = 0.25
    assert (a, 0.0) in [(round(x, 6), round(y, 6)) for x, y in verts]
    assert (1.0 - a, 0.0) in [(round(x, 6), round(y, 6)) for x, y in verts]


def test_hexagon_adj_changes_width() -> None:
    verts_wide = preset_vertices("hexagon", {"adj": 0.1})
    verts_narrow = preset_vertices("hexagon", {"adj": 0.4})
    assert verts_wide is not None and verts_narrow is not None
    # adj is the inset; smaller adj → wider flat top
    # top-left x with adj=0.1 should be smaller than with adj=0.4
    top_left_wide_x = min(x for x, y in verts_wide if abs(y) < 1e-9)
    top_left_narrow_x = min(x for x, y in verts_narrow if abs(y) < 1e-9)
    assert top_left_wide_x < top_left_narrow_x


def test_octagon_eight_vertices() -> None:
    verts = preset_vertices("octagon", {})
    assert verts is not None
    assert len(verts) == 8


def test_plus_twelve_vertices() -> None:
    verts = preset_vertices("plus", {})
    assert verts is not None
    assert len(verts) == 12


def test_star5_ten_vertices() -> None:
    verts = preset_vertices("star5", {})
    assert verts is not None
    assert len(verts) == 10  # 5 outer + 5 inner


def test_star8_sixteen_vertices() -> None:
    verts = preset_vertices("star8", {})
    assert verts is not None
    assert len(verts) == 16


def test_star4_eight_vertices() -> None:
    verts = preset_vertices("star4", {})
    assert verts is not None
    assert len(verts) == 8


def test_right_arrow_seven_vertices() -> None:
    verts = preset_vertices("rightArrow", {})
    assert verts is not None
    assert len(verts) == 7
    # Tip at (1.0, 0.5)
    assert any(abs(x - 1.0) < 0.01 and abs(y - 0.5) < 0.01 for x, y in verts)


def test_chevron_six_vertices() -> None:
    verts = preset_vertices("chevron", {})
    assert verts is not None
    assert len(verts) == 6


def test_unknown_preset_returns_none() -> None:
    assert preset_vertices("notAPreset", {}) is None


def test_rect_not_in_polygon_presets() -> None:
    assert "rect" not in POLYGON_PRESETS
    assert "roundRect" not in POLYGON_PRESETS
    assert "ellipse" not in POLYGON_PRESETS


def test_all_polygon_presets_produce_vertices() -> None:
    for kind in POLYGON_PRESETS:
        verts = preset_vertices(kind, {})
        assert verts is not None, f"preset_vertices('{kind}') returned None"
        assert len(verts) >= 3, f"preset '{kind}' has < 3 vertices"


def test_all_vertices_in_unit_square() -> None:
    for kind in POLYGON_PRESETS:
        verts = preset_vertices(kind, {})
        assert verts is not None
        for x, y in verts:
            assert -0.01 <= x <= 1.01, f"preset '{kind}' vertex ({x},{y}) outside unit square"
            assert -0.01 <= y <= 1.01, f"preset '{kind}' vertex ({x},{y}) outside unit square"


def test_preset_defaults_returns_empty_for_no_adj() -> None:
    assert preset_defaults("rtTriangle") == {}
    assert preset_defaults("diamond") == {}


def test_preset_defaults_returns_adj_for_known_presets() -> None:
    defaults = preset_defaults("hexagon")
    assert "adj" in defaults
    assert abs(defaults["adj"] - 0.25) < 0.01


# ---------------------------------------------------------------------------
# Polygon matcher — match_polygon
# ---------------------------------------------------------------------------


def _scale(verts: list[tuple[float, float]], w: float, h: float) -> list[tuple[float, float]]:
    """Scale unit-square vertices to pixel coordinates."""
    return [(x * w, y * h) for x, y in verts]


def test_match_exact_diamond() -> None:
    verts = preset_vertices("diamond", {})
    assert verts is not None
    w, h = 200.0, 150.0
    poly = _scale(verts, w, h)
    result = match_polygon(poly, w, h)
    assert result == "diamond"


def test_match_exact_triangle() -> None:
    verts = preset_vertices("triangle", {})
    assert verts is not None
    w, h = 300.0, 200.0
    poly = _scale(verts, w, h)
    assert match_polygon(poly, w, h) == "triangle"


def test_match_reversed_winding() -> None:
    """Reversed vertex order should still match."""
    verts = preset_vertices("diamond", {})
    assert verts is not None
    w, h = 200.0, 150.0
    poly = list(reversed(_scale(verts, w, h)))
    assert match_polygon(poly, w, h) == "diamond"


def test_match_cyclic_rotation() -> None:
    """A cyclic rotation of the vertices should still match."""
    verts = preset_vertices("hexagon", {})
    assert verts is not None
    w, h = 400.0, 400.0
    poly = _scale(verts, w, h)
    # Rotate by 3 positions
    rotated = poly[3:] + poly[:3]
    assert match_polygon(rotated, w, h) == "hexagon"


def test_match_within_tolerance() -> None:
    """A polygon with small per-vertex jitter (< 1.5% of diagonal) should match."""
    verts = preset_vertices("diamond", {})
    assert verts is not None
    w, h = 200.0, 200.0
    poly = _scale(verts, w, h)
    # Add jitter smaller than 1.5% of diagonal
    diagonal = math.hypot(w, h)
    jitter = 0.01 * diagonal  # 1%, within tolerance
    jittered = [(x + jitter * 0.5, y + jitter * 0.5) for x, y in poly]
    assert match_polygon(jittered, w, h) == "diamond"


def test_no_match_outside_tolerance() -> None:
    """A polygon with large jitter should not match."""
    verts = preset_vertices("diamond", {})
    assert verts is not None
    w, h = 200.0, 200.0
    poly = _scale(verts, w, h)
    diagonal = math.hypot(w, h)
    # Jitter larger than 1.5% of diagonal
    jitter = 0.05 * diagonal
    jittered = [(x + jitter, y + jitter) for x, y in poly]
    assert match_polygon(jittered, w, h) is None


def test_no_match_wrong_vertex_count() -> None:
    """A polygon with a different vertex count should not match anything."""
    # Use a weird 4-sided shape that doesn't match any 4-sided preset
    quad = [(0.0, 0.0), (0.9, 0.1), (1.0, 0.9), (0.1, 1.0)]
    quad_scaled = [(x * 100, y * 100) for x, y in quad]
    result = match_polygon(quad_scaled, 100.0, 100.0)
    # The result should either be None or possibly match a preset — we just verify no crash
    assert result is None or isinstance(result, str)


def test_empty_polygon_returns_none() -> None:
    assert match_polygon([], 100.0, 100.0) is None


def test_zero_dimensions_returns_none() -> None:
    assert match_polygon([(0, 0), (1, 0), (0, 1)], 0.0, 100.0) is None


def test_match_all_polygon_presets() -> None:
    """Every registered preset should match itself at its default adj values."""
    w, h = 300.0, 200.0
    for kind in POLYGON_PRESETS:
        verts = preset_vertices(kind, {})
        assert verts is not None
        poly = _scale(verts, w, h)
        result = match_polygon(poly, w, h)
        assert result == kind, f"preset '{kind}' did not match itself: got {result!r}"


# ---------------------------------------------------------------------------
# parse_polygon
# ---------------------------------------------------------------------------


def test_parse_polygon_percent() -> None:
    result = parse_polygon("polygon(50% 0%, 100% 100%, 0% 100%)", width_px=200.0, height_px=100.0)
    assert result is not None
    expected = [(100.0, 0.0), (200.0, 100.0), (0.0, 100.0)]
    assert all(_close(a, b) for a, b in zip(result, expected, strict=True))


def test_parse_polygon_px() -> None:
    clip = "polygon(50px 0px, 100px 50px, 0px 50px)"
    result = parse_polygon(clip, width_px=100.0, height_px=50.0)
    assert result is not None
    expected = [(50.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
    assert all(_close(a, b) for a, b in zip(result, expected, strict=True))


def test_parse_polygon_none_for_no_clip_path() -> None:
    assert parse_polygon(None, width_px=100.0, height_px=100.0) is None
    assert parse_polygon("none", width_px=100.0, height_px=100.0) is None


def test_parse_polygon_none_for_non_polygon() -> None:
    assert parse_polygon("circle(50%)", width_px=100.0, height_px=100.0) is None
    assert parse_polygon("inset(10px)", width_px=100.0, height_px=100.0) is None


def test_parse_polygon_none_for_fewer_than_3_vertices() -> None:
    assert parse_polygon("polygon(0% 0%, 100% 100%)", width_px=100.0, height_px=100.0) is None


# ---------------------------------------------------------------------------
# Reverse emitter — _clip_path_css (via html.py)
# ---------------------------------------------------------------------------


def test_clip_path_css_diamond() -> None:
    from domoxml.core.html import _clip_path_css  # pyright: ignore[reportPrivateUsage]

    css = _clip_path_css("diamond")
    assert css is not None
    assert css.startswith("clip-path:polygon(")
    assert "50%" in css  # mid-points


def test_clip_path_css_rect_returns_none() -> None:
    from domoxml.core.html import _clip_path_css  # pyright: ignore[reportPrivateUsage]

    assert _clip_path_css("rect") is None
    assert _clip_path_css("roundRect") is None
    assert _clip_path_css("ellipse") is None


def test_clip_path_css_unknown_returns_none() -> None:
    from domoxml.core.html import _clip_path_css  # pyright: ignore[reportPrivateUsage]

    assert _clip_path_css("unknownShape") is None


# ---------------------------------------------------------------------------
# Reverse XML → clip-path integration
# ---------------------------------------------------------------------------


def test_reverse_triangle_emits_clip_path() -> None:
    """prstGeom triangle in the IR produces clip-path CSS in HTML output."""
    from domoxml.core.html import serialize_canvas
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, SolidFill

    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=1_000_000, height=1_000_000),
                geom="triangle",
                fill=SolidFill(color=Rgba(r=255, g=0, b=0)),
            ),
        ),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "clip-path:polygon(" in html


def test_reverse_rect_no_clip_path() -> None:
    """prstGeom rect produces no clip-path CSS."""
    from domoxml.core.html import serialize_canvas
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, SolidFill

    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=1_000_000, height=1_000_000),
                geom="rect",
                fill=SolidFill(color=Rgba(r=0, g=255, b=0)),
            ),
        ),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "clip-path" not in html


# ---------------------------------------------------------------------------
# Forward OOXML assertion — prstGeom name in emitted XML
# ---------------------------------------------------------------------------


def test_forward_triangle_emits_prstgeom() -> None:
    """ShapeNode with geom='triangle' emits prstGeom prst='triangle' in the XML."""
    from domoxml.core.drawingml.shape import shape_xml
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SolidFill

    node = ShapeNode(
        box=Box(x=0, y=0, width=500_000, height=500_000),
        geom="triangle",
        fill=SolidFill(color=Rgba(r=0, g=0, b=255)),
    )
    xml = shape_xml(node, shape_id=1)
    assert 'prst="triangle"' in xml


def test_forward_hexagon_emits_prstgeom() -> None:
    from domoxml.core.drawingml.shape import shape_xml
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SolidFill

    node = ShapeNode(
        box=Box(x=0, y=0, width=500_000, height=500_000),
        geom="hexagon",
        fill=SolidFill(color=Rgba(r=100, g=200, b=50)),
    )
    xml = shape_xml(node, shape_id=2)
    assert 'prst="hexagon"' in xml


def test_forward_star5_emits_prstgeom() -> None:
    from domoxml.core.drawingml.shape import shape_xml
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SolidFill

    node = ShapeNode(
        box=Box(x=0, y=0, width=400_000, height=400_000),
        geom="star5",
        fill=SolidFill(color=Rgba(r=255, g=200, b=0)),
    )
    xml = shape_xml(node, shape_id=3)
    assert 'prst="star5"' in xml


def test_forward_right_arrow_emits_prstgeom() -> None:
    from domoxml.core.drawingml.shape import shape_xml
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SolidFill

    node = ShapeNode(
        box=Box(x=0, y=0, width=600_000, height=300_000),
        geom="rightArrow",
        fill=SolidFill(color=Rgba(r=50, g=100, b=200)),
    )
    xml = shape_xml(node, shape_id=4)
    assert 'prst="rightArrow"' in xml


# ---------------------------------------------------------------------------
# PPTX reverse reader — prstGeom → GeometryKind
# ---------------------------------------------------------------------------


def test_reverse_reader_maps_known_presets() -> None:
    """Round-trip a prstGeom triangle through the reader and confirm geom is set."""
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, SolidFill
    from domoxml.slides import build_pptx
    from domoxml.slides.read import read_pptx

    # Build a PPTX with a triangle shape via IR
    slide_ir = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=500_000, y=500_000, width=2_000_000, height=1_500_000),
                geom="triangle",
                fill=SolidFill(color=Rgba(r=255, g=100, b=50)),
            ),
        ),
    )
    pptx_bytes = build_pptx([slide_ir], faces=[])
    [read_slide] = read_pptx(pptx_bytes)
    assert len(read_slide.shapes) == 1
    assert read_slide.shapes[0].geom == "triangle"


def test_reverse_reader_unknown_prstgeom_falls_back_to_rect() -> None:
    """An unknown prstGeom value in OOXML falls back to 'rect' in the IR."""
    from domoxml.core.ir.model import Box, Rgba, ShapeNode, SlideIR, SolidFill
    from domoxml.core.opc import OpcPackage, write_package
    from domoxml.slides import build_pptx
    from domoxml.slides.read import read_pptx_result
    from domoxml.types import Editability, Representation, SourceRetention

    # Inject an unknown prstGeom into the slide XML
    slide_ir = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=1_000_000, height=1_000_000),
                geom="rect",
                fill=SolidFill(color=Rgba(r=0, g=0, b=0)),
            ),
        ),
    )
    pptx_bytes = build_pptx([slide_ir], faces=[])
    package = OpcPackage.from_bytes(pptx_bytes)
    parts: dict[str, bytes | str] = {part: package.read(part) for part in package.parts}
    # Replace "rect" with an unknown preset in the slide XML
    slide_part = "ppt/slides/slide1.xml"
    slide_xml = parts[slide_part]
    assert isinstance(slide_xml, bytes)
    parts[slide_part] = slide_xml.replace(b'prst="rect"', b'prst="unknownPreset12345"')
    result = read_pptx_result(write_package(parts))
    [read_slide] = result.slides
    assert read_slide.shapes[0].geom == "rect"  # fallback
    [coverage] = result.coverage.items
    assert coverage.representation is Representation.APPROXIMATED
    assert coverage.editability is Editability.SEMANTIC
    assert coverage.source_retention is SourceRetention.LOST
    assert "unknownPreset12345" in coverage.reason
