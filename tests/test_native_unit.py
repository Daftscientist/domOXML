"""Unit tests for native-first mapping: gradient/border/shadow parsing and the extractor's
native-vs-raster decision (no browser)."""
# tests legitimately probe internal helpers
# pyright: reportPrivateUsage=false

from __future__ import annotations

import io

from PIL import Image

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import Box, Connector, GradientFill, PictureFill, SolidFill
from domoxml.core.ir.parse import parse_border_side, parse_gradient, parse_shadow
from domoxml.core.render.browser import (
    RenderedNode,
    RenderedRaster,
    RenderedSlide,
    _needs_isolated_raster,
)
from domoxml.types import Editability, Representation, SourceRetention


def _png(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def _slide(*nodes: RenderedNode) -> RenderedSlide:
    return RenderedSlide(png=_png(), width=20, height=15, scale=2.0, nodes=nodes)


# --------------------------------------------------------------------------- gradient parsing


def test_parse_linear_gradient_angle_and_stops() -> None:
    gradient = parse_gradient("linear-gradient(135deg, rgb(255, 0, 0) 0%, rgb(0, 0, 255) 100%)")
    assert isinstance(gradient, GradientFill)
    assert gradient.radial is False
    assert gradient.angle_deg == 135.0
    assert len(gradient.stops) == 2
    assert gradient.stops[0].color.hex == "FF0000" and gradient.stops[0].pos == 0.0
    assert gradient.stops[1].color.hex == "0000FF" and gradient.stops[1].pos == 1.0


def test_parse_gradient_fills_missing_stop_positions_evenly() -> None:
    gradient = parse_gradient("linear-gradient(rgb(0,0,0), rgb(128,128,128), rgb(255,255,255))")
    assert gradient is not None
    assert [round(s.pos, 3) for s in gradient.stops] == [0.0, 0.5, 1.0]


def test_radial_and_keyword_gradients() -> None:
    radial = parse_gradient("radial-gradient(rgb(0,0,0) 0%, rgb(255,255,255) 100%)")
    assert radial is not None and radial.radial is True
    keyword = parse_gradient("linear-gradient(to right, rgb(0,0,0), rgb(255,255,255))")
    assert keyword is not None and keyword.angle_deg == 90.0


def test_unmappable_gradients_return_none() -> None:
    assert parse_gradient("conic-gradient(rgb(0,0,0), rgb(255,255,255))") is None
    assert parse_gradient("linear-gradient(red, blue), url(x.png)") is None
    assert parse_gradient("none") is None


# --------------------------------------------------------------------------- border / shadow


def test_parse_border_side() -> None:
    line, warn = parse_border_side("2px", "solid", "rgb(0, 0, 0)")
    assert line is not None and line.width_emu == 19050 and line.dash == "solid"
    assert warn is None
    assert parse_border_side("0px", "solid", "rgb(0,0,0)") == (None, None)
    assert parse_border_side("2px", "none", "rgb(0,0,0)") == (None, None)
    dashed, _ = parse_border_side("1px", "dashed", "rgb(0,0,0)")
    assert dashed is not None and dashed.dash == "dash"


def test_parse_shadow_offsets_and_inset() -> None:
    shadow = parse_shadow("rgba(0, 0, 0, 0.25) 0px 10px 30px 0px")
    assert shadow is not None
    assert shadow.distance_emu == 95250  # 10px straight down
    assert round(shadow.direction_deg) == 90  # downward
    assert shadow.inset is False
    inset = parse_shadow("rgb(0,0,0) 2px 2px 4px inset")
    assert inset is not None and inset.inset is True
    assert parse_shadow("none") is None


# --------------------------------------------------------------------------- native-vs-raster


def test_gradient_fill_is_native() -> None:
    gradient_node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={"backgroundImage": "linear-gradient(90deg, rgb(0,0,0), rgb(255,255,255))"},
    )
    result = extract_slide(_slide(gradient_node))
    assert isinstance(result.slide.shapes[0].fill, GradientFill)
    assert result.coverage[0].representation is Representation.NATIVE
    assert result.coverage[0].editability is Editability.SEMANTIC


def test_css_filter_rasterises_and_warns() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={"filter": "blur(4px)", "backgroundColor": "rgb(1,2,3)"},
    )
    result = extract_slide(_slide(node))
    assert isinstance(result.slide.shapes[0].fill, PictureFill)  # baked pixels, not dropped
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert result.coverage[0].editability is Editability.LAYERS
    assert result.coverage[0].raster_area_emu2 > 0
    assert result.warnings and "filter" in result.warnings[0].message


def test_empty_raster_region_is_recorded_as_failed_not_layered() -> None:
    node = RenderedNode(
        tag="div",
        x=100,
        y=100,
        width=10,
        height=10,
        index=0,
        styles={"filter": "blur(4px)", "backgroundColor": "rgb(1,2,3)"},
    )

    result = extract_slide(_slide(node))

    assert result.slide.shapes == ()
    assert result.coverage[0].representation is Representation.FAILED
    assert result.coverage[0].editability is Editability.NONE
    assert result.coverage[0].source_retention is SourceRetention.LOST
    assert result.coverage[0].output_count == 0


def test_unmappable_custom_svg_paint_uses_element_layer_instead_of_omitting_it() -> None:
    svg = RenderedNode(
        tag="svg",
        x=0,
        y=0,
        width=10,
        height=10,
        src="0 0 10 10",
        index=0,
        parent=-1,
    )
    path = RenderedNode(
        tag="path",
        x=0,
        y=0,
        width=10,
        height=10,
        src="M 0 0 L 10 0 L 10 10 Z",
        index=1,
        parent=0,
        styles={"fill": "url(#gradient)"},
    )

    result = extract_slide(_slide(svg, path))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert "SVG custom geometry paint" in result.coverage[0].reason


def test_custom_svg_solid_fill_and_stroke_map_to_native_shape_paint() -> None:
    svg = RenderedNode(
        tag="svg",
        x=0,
        y=0,
        width=100,
        height=50,
        src="0 0 100 50",
        index=0,
        parent=-1,
    )
    path = RenderedNode(
        tag="path",
        x=0,
        y=0,
        width=100,
        height=50,
        src="M 0 0 L 100 0 L 100 50 Z",
        index=1,
        parent=0,
        styles={
            "fill": "rgb(68, 114, 196)",
            "stroke": "rgb(31, 78, 121)",
            "strokeWidth": "4px",
            "strokeDasharray": "16px, 12px, 4px, 12px",
            "strokeLinecap": "round",
            "strokeLinejoin": "bevel",
        },
    )

    result = extract_slide(_slide(svg, path))

    shape = result.slide.shapes[0]
    assert isinstance(shape.fill, SolidFill)
    assert shape.fill.color.hex == "4472C4"
    assert shape.line is not None
    assert shape.line.color.hex == "1F4E79"
    assert shape.line.width_emu == 38100
    assert shape.line.dash == "dashDot"
    assert shape.line.cap == "round"
    assert shape.line.join == "bevel"
    assert result.coverage[0].representation is Representation.NATIVE


def test_hr_one_sided_border_becomes_connector_stroke() -> None:
    hr = RenderedNode(
        tag="hr",
        x=50,
        y=280,
        width=600,
        height=2,
        index=0,
        styles={
            "borderTopWidth": "2px",
            "borderTopStyle": "solid",
            "borderTopColor": "rgb(102, 102, 102)",
        },
    )

    result = extract_slide(_slide(hr))

    connector = result.slide.contents[0]
    assert isinstance(connector, Connector)
    assert connector.line.width_emu == 19050
    assert connector.line.color.hex == "666666"


def test_inset_css_shadow_rasterises_for_portable_fidelity() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "boxShadow": "rgba(0, 0, 0, 0.25) 4px 4px 12px 2px inset",
            "backgroundColor": "rgb(241,245,249)",
        },
    )

    result = extract_slide(_slide(node))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert result.coverage[0].editability is Editability.LAYERS
    assert "inset box-shadow" in (result.coverage[0].reason or "")


def test_browser_requests_isolated_raster_for_inset_shadow() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        styles={"boxShadow": "rgb(0, 0, 0) 2px 2px 4px inset"},
    )

    assert _needs_isolated_raster(node)


def test_css_filter_uses_isolated_raster_region_when_available() -> None:
    node = RenderedNode(
        tag="div",
        x=5,
        y=6,
        width=10,
        height=10,
        index=0,
        styles={"filter": "blur(4px)", "backgroundColor": "rgb(1,2,3)"},
    )
    # RenderedRaster coords are CSS px; slide scale only affects cropping,
    # extract._raster_shape converts CSS px via px_to_emu without applying rendered.scale.
    raster = RenderedRaster(png=_png(20, 20), x=1, y=2, width=18, height=18)
    rendered = _slide(node).model_copy(update={"rasters": {0: raster}})
    result = extract_slide(rendered)
    shape = result.slide.shapes[0]
    assert shape.box == Box(x=9525, y=19050, width=171450, height=171450)
    assert isinstance(shape.fill, PictureFill) and shape.fill.data == raster.png


def test_rasterised_parent_consumes_its_subtree() -> None:
    parent = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        parent=-1,
        styles={"mixBlendMode": "multiply"},
    )
    child = RenderedNode(
        tag="span",
        x=1,
        y=1,
        width=4,
        height=4,
        index=1,
        parent=0,
        text="hi",
        styles={"backgroundColor": "rgb(9,9,9)"},
    )
    result = extract_slide(_slide(parent, child))
    # Only the parent's raster shape — the child is baked into it, not emitted twice.
    assert len(result.slide.shapes) == 1
    assert isinstance(result.slide.shapes[0].fill, PictureFill)


def test_plain_background_stays_solid() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={"backgroundColor": "rgb(79, 70, 229)"},
    )
    result = extract_slide(_slide(node))
    assert isinstance(result.slide.shapes[0].fill, SolidFill)
