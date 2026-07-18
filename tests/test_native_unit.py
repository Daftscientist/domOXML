"""Unit tests for native-first mapping: gradient/border/shadow parsing and the extractor's
native-vs-raster decision (no browser)."""
# tests legitimately probe internal helpers
# pyright: reportPrivateUsage=false

from __future__ import annotations

import io

from PIL import Image

from domoxml.core.ir import extract_slide
from domoxml.core.ir.effect_payload import encode_effects
from domoxml.core.ir.model import (
    Blur,
    Box,
    Connector,
    FillOverlay,
    Glow,
    GradientFill,
    PictureFill,
    Rgba,
    Shadow,
    SoftEdge,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.ir.parse import (
    parse_border_side,
    parse_box_reflection,
    parse_fill_overlay,
    parse_gradient,
    parse_shadow,
    parse_soft_edge_mask,
)
from domoxml.core.ir.text_payload import encode_text_body
from domoxml.core.render.browser import (
    RenderedNode,
    RenderedRaster,
    RenderedSlide,
    _needs_isolated_raster,
    _raster_bounds,
)
from domoxml.core.units import px_to_emu
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


def test_normalized_effect_payload_wins_over_renderer_css_inference() -> None:
    effects = (
        Shadow(
            color=Rgba(r=1, g=2, b=3, a=0.4),
            blur_emu=50_000,
            distance_emu=25_000,
            direction_deg=33,
            spread_emu=7_500,
        ),
        Glow(color=Rgba(r=4, g=5, b=6, a=0.5), radius_emu=60_000),
    )
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "backgroundColor": "rgb(255, 255, 255)",
            "boxShadow": "rgb(255, 0, 0) 1px 1px 1px 0px",
            "domoxmlEffects": encode_effects(effects),
        },
    )

    result = extract_slide(_slide(node))

    assert result.slide.shapes[0].effects == effects


def test_normalized_text_payload_wins_over_renderer_alignment_inference() -> None:
    text = TextBody(
        paragraphs=(
            TextParagraph(
                runs=(TextRun(text="Centered", font_family="Arial", size_pt=18),),
                align="center",
            ),
        )
    )
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=100,
        height=50,
        text="Centered",
        index=0,
        styles={
            "backgroundColor": "rgb(255, 255, 255)",
            "textAlign": "left",
            "domoxmlTextPayload": encode_text_body(text),
        },
    )

    result = extract_slide(_slide(node))

    assert result.slide.shapes[0].text == text


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


def test_css_blur_filter_is_native_and_editable() -> None:
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
    shape = result.slide.shapes[0]
    assert isinstance(shape.fill, SolidFill)
    assert shape.effects == (Blur(radius_emu=38100),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.picture.raster_role == "portable-blur-fallback"
    assert result.coverage[0].representation is Representation.HYBRID
    assert result.coverage[0].editability is Editability.COMPONENTS
    assert result.coverage[0].raster_area_emu2 > 0
    assert "isolated renderer fallback" in result.warnings[0].message


def test_css_box_reflection_is_native_with_paint_bound_fallback() -> None:
    reflection_css = (
        "below 4px linear-gradient(rgba(0, 0, 0, 0.75) 0%, "
        "rgba(0, 0, 0, 0) 100%) 0 fill / auto / 0 stretch"
    )
    node = RenderedNode(
        tag="div",
        x=5,
        y=6,
        width=10,
        height=10,
        index=0,
        styles={"webkitBoxReflect": reflection_css, "backgroundColor": "rgb(1,2,3)"},
    )
    raster = RenderedRaster(png=_png(20, 48), x=5, y=6, width=10, height=24)
    result = extract_slide(_slide(node).model_copy(update={"rasters": {0: raster}}))

    shape = result.slide.shapes[0]
    assert shape.effects == (parse_box_reflection(reflection_css),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(5),
        y=px_to_emu(6),
        width=px_to_emu(10),
        height=px_to_emu(24),
    )
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert result.coverage[0].representation is Representation.HYBRID
    assert result.coverage[0].editability is Editability.COMPONENTS
    assert result.coverage[0].raster_area_emu2 == px_to_emu(10) * px_to_emu(24)
    assert "reflection" in (result.coverage[0].reason or "")


def test_css_soft_edge_is_native_with_shape_bound_fallback() -> None:
    mask = (
        "linear-gradient(to right, rgba(0,0,0,0) 0px, rgb(0,0,0) 4px, "
        "rgb(0,0,0) calc(100% - 4px), rgba(0,0,0,0) 100%),"
        "linear-gradient(rgba(0,0,0,0) 0px, rgb(0,0,0) 4px, "
        "rgb(0,0,0) calc(100% - 4px), rgba(0,0,0,0) 100%)"
    )
    node = RenderedNode(
        tag="div",
        x=5,
        y=6,
        width=10,
        height=10,
        index=0,
        styles={
            "maskImage": mask,
            "maskComposite": "intersect, intersect",
            "backgroundColor": "rgb(1,2,3)",
        },
    )
    raster = RenderedRaster(png=_png(20, 20), x=5, y=6, width=10, height=10)
    result = extract_slide(_slide(node).model_copy(update={"rasters": {0: raster}}))

    shape = result.slide.shapes[0]
    assert shape.effects == (parse_soft_edge_mask(mask, "intersect, intersect"),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(5),
        y=px_to_emu(6),
        width=px_to_emu(10),
        height=px_to_emu(10),
    )
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert result.coverage[0].representation is Representation.HYBRID
    assert result.coverage[0].editability is Editability.COMPONENTS
    assert result.coverage[0].raster_area_emu2 == px_to_emu(10) * px_to_emu(10)
    assert "softEdge" in (result.coverage[0].reason or "")


def test_zero_radius_soft_edge_stays_native_without_fallback() -> None:
    effect = SoftEdge(radius_emu=0)
    node = RenderedNode(
        tag="div",
        x=5,
        y=6,
        width=10,
        height=10,
        index=0,
        styles={
            "domoxmlEffects": encode_effects((effect,)),
            "backgroundColor": "rgb(1,2,3)",
        },
    )

    result = extract_slide(_slide(node))

    shape = result.slide.shapes[0]
    assert shape.effects == (effect,)
    assert shape.portable_fallback is None
    assert result.coverage[0].representation is Representation.NATIVE


def test_css_fill_overlay_is_native_with_shape_bound_fallback() -> None:
    background_image = "linear-gradient(rgb(255, 40, 80), rgb(255, 40, 80))"
    node = RenderedNode(
        tag="div",
        x=5,
        y=4,
        width=10,
        height=8,
        index=0,
        styles={
            "backgroundImage": background_image,
            "backgroundColor": "rgb(20, 60, 140)",
            "backgroundBlendMode": "multiply",
        },
    )

    result = extract_slide(_slide(node))

    shape = result.slide.shapes[0]
    parsed = parse_fill_overlay(
        background_image,
        "rgb(20, 60, 140)",
        "multiply",
    )
    assert parsed is not None
    assert shape.fill == parsed[0]
    assert shape.effects == (parsed[1],)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(5),
        y=px_to_emu(4),
        width=px_to_emu(10),
        height=px_to_emu(8),
    )
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert result.coverage[0].representation is Representation.HYBRID
    assert result.coverage[0].editability is Editability.COMPONENTS
    assert result.coverage[0].raster_area_emu2 == px_to_emu(10) * px_to_emu(8)
    assert "fillOverlay" in (result.coverage[0].reason or "")


def test_encoded_transparent_fill_overlay_recovers_base_fill_without_fallback() -> None:
    effect = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.0)),
        blend="screen",
    )
    node = RenderedNode(
        tag="div",
        x=5,
        y=4,
        width=10,
        height=8,
        index=0,
        styles={
            "domoxmlEffects": encode_effects((effect,)),
            "backgroundImage": "linear-gradient(rgba(255, 40, 80, 0), rgba(255, 40, 80, 0))",
            "backgroundColor": "rgb(20, 60, 140)",
            "backgroundBlendMode": "screen",
        },
    )

    result = extract_slide(_slide(node))

    shape = result.slide.shapes[0]
    assert shape.fill == SolidFill(color=Rgba(r=20, g=60, b=140))
    assert shape.effects == (effect,)
    assert shape.portable_fallback is None
    assert result.coverage[0].representation is Representation.NATIVE


def test_encoded_fill_overlay_recovers_stacked_gradient_base() -> None:
    effect = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.72157)),
        blend="mult",
    )
    node = RenderedNode(
        tag="div",
        x=5,
        y=4,
        width=10,
        height=8,
        index=0,
        styles={
            "domoxmlEffects": encode_effects((effect,)),
            "backgroundImage": (
                "linear-gradient(rgba(255, 40, 80, 0.72), rgba(255, 40, 80, 0.72)), "
                "linear-gradient(90deg, rgb(10, 20, 30), rgb(40, 50, 60))"
            ),
            "backgroundColor": "rgba(0, 0, 0, 0)",
            "backgroundBlendMode": "multiply, normal",
        },
    )

    result = extract_slide(_slide(node))

    shape = result.slide.shapes[0]
    assert isinstance(shape.fill, GradientFill)
    assert [stop.color for stop in shape.fill.stops] == [
        Rgba(r=10, g=20, b=30),
        Rgba(r=40, g=50, b=60),
    ]
    assert shape.effects == (effect,)
    assert shape.portable_fallback is not None
    assert result.coverage[0].representation is Representation.HYBRID


def test_nonuniform_background_blend_uses_visible_element_layer() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "backgroundImage": "linear-gradient(rgb(255, 0, 0), rgb(0, 0, 255))",
            "backgroundColor": "rgb(20, 60, 140)",
            "backgroundBlendMode": "multiply",
        },
    )

    result = extract_slide(_slide(node))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert "background-blend-mode" in (result.coverage[0].reason or "")


def test_partial_uniform_background_blend_uses_visible_element_layer() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "backgroundImage": "linear-gradient(rgb(255, 0, 0), rgb(255, 0, 0))",
            "backgroundColor": "rgb(20, 60, 140)",
            "backgroundBlendMode": "multiply",
            "backgroundSize": "50% 50%",
            "backgroundPosition": "100% 100%",
            "backgroundRepeat": "no-repeat",
        },
    )

    result = extract_slide(_slide(node))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert "background-blend-mode" in (result.coverage[0].reason or "")


def test_stale_encoded_fill_overlay_uses_visible_element_layer() -> None:
    effect = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "domoxmlEffects": encode_effects((effect,)),
            "backgroundImage": "linear-gradient(rgb(0, 255, 0), rgb(0, 255, 0))",
            "backgroundColor": "rgb(20, 60, 140)",
            "backgroundBlendMode": "multiply",
        },
    )

    result = extract_slide(_slide(node))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert "metadata does not match" in (result.coverage[0].reason or "")


def test_unmapped_css_mask_uses_visible_element_layer() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={
            "maskImage": "radial-gradient(rgb(0,0,0), rgba(0,0,0,0))",
            "maskComposite": "add",
            "backgroundColor": "rgb(1,2,3)",
        },
    )

    result = extract_slide(_slide(node))

    assert isinstance(result.slide.shapes[0].fill, PictureFill)
    assert result.coverage[0].representation is Representation.ELEMENT_LAYER
    assert result.coverage[0].editability is Editability.LAYERS
    assert "CSS mask" in (result.coverage[0].reason or "")


def test_unsupported_css_filter_rasterises_and_warns() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        index=0,
        styles={"filter": "brightness(0.8)", "backgroundColor": "rgb(1,2,3)"},
    )
    result = extract_slide(_slide(node))
    assert isinstance(result.slide.shapes[0].fill, PictureFill)
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
        styles={"filter": "brightness(0.8)", "backgroundColor": "rgb(1,2,3)"},
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


def test_unsupported_css_filter_uses_isolated_raster_region_when_available() -> None:
    node = RenderedNode(
        tag="div",
        x=5,
        y=6,
        width=10,
        height=10,
        index=0,
        styles={"filter": "brightness(0.8)", "backgroundColor": "rgb(1,2,3)"},
    )
    # RenderedRaster coords are CSS px; slide scale only affects cropping,
    # extract._raster_shape converts CSS px via px_to_emu without applying rendered.scale.
    raster = RenderedRaster(png=_png(20, 20), x=1, y=2, width=18, height=18)
    rendered = _slide(node).model_copy(update={"rasters": {0: raster}})
    result = extract_slide(rendered)
    shape = result.slide.shapes[0]
    assert shape.box == Box(x=9525, y=19050, width=171450, height=171450)
    assert isinstance(shape.fill, PictureFill) and shape.fill.data == raster.png


def test_browser_requests_isolated_renderer_fallback_for_native_css_blur() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        styles={"filter": "blur(4px)"},
    )

    assert _needs_isolated_raster(node)


def test_browser_requests_isolated_renderer_fallback_for_css_mask() -> None:
    node = RenderedNode(
        tag="div",
        x=0,
        y=0,
        width=10,
        height=10,
        styles={"maskImage": "linear-gradient(rgb(0,0,0), rgba(0,0,0,0))"},
    )

    assert _needs_isolated_raster(node)
    assert _raster_bounds(node, slide_width=20, slide_height=20) == (0, 0, 10, 10)


def test_browser_reflection_fallback_bounds_include_reflected_copy() -> None:
    node = RenderedNode(
        tag="div",
        x=20,
        y=30,
        width=80,
        height=40,
        styles={
            "webkitBoxReflect": ("below 6px linear-gradient(rgba(0, 0, 0, 0.8), rgba(0, 0, 0, 0))")
        },
    )

    assert _needs_isolated_raster(node)
    assert _raster_bounds(node, slide_width=200, slide_height=150) == (20, 30, 100, 116)


def test_browser_reflection_bounds_include_blur_around_reflected_copy() -> None:
    node = RenderedNode(
        tag="div",
        x=20,
        y=30,
        width=80,
        height=40,
        styles={
            "filter": "blur(2px)",
            "webkitBoxReflect": ("below 6px linear-gradient(rgba(0, 0, 0, 0.8), rgba(0, 0, 0, 0))"),
        },
    )

    assert _raster_bounds(node, slide_width=200, slide_height=150) == (14, 24, 106, 122)


def test_browser_reflection_bounds_follow_rotated_local_axis() -> None:
    node = RenderedNode(
        tag="div",
        x=100,
        y=30,
        width=40,
        height=80,
        styles={
            "transform": "matrix(0, 1, -1, 0, 0, 0)",
            "domoxmlLayoutWidth": "80",
            "domoxmlLayoutHeight": "40",
            "webkitBoxReflect": ("below 6px linear-gradient(rgba(0, 0, 0, 0.8), rgba(0, 0, 0, 0))"),
        },
    )

    assert _raster_bounds(node, slide_width=200, slide_height=150) == (54, 30, 140, 110)


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
