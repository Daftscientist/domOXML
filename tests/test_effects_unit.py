# pyright: reportPrivateUsage=false, reportUnknownParameterType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Unit tests for effects parity — forward (HTML/CSS → OOXML) and reverse (OOXML → HTML/CSS).

Forward tests verify:
- box-shadow spread → outerShdw sx/sy grow attributes (hand-computed formula)
- inset box-shadow spread → innerShdw with blurRad approximation + warning
- zero-offset box-shadow → a:glow (IR decision in extract)
- non-zero-offset box-shadow stays a:outerShdw

Reverse tests verify all 8 legacy effect kinds in effectLst plus typed solid fill overlay:
- a:outerShdw (with sx/sy grow → spread_emu)
- a:innerShdw → inset Shadow
- a:glow → Glow IR → box-shadow CSS
- a:blur → Blur IR → filter:blur() CSS + warning
- a:softEdge → SoftEdge IR → mask-image CSS
- a:reflection → Reflection IR → -webkit-box-reflect CSS + warning
- a:prstShdw → PreservedFragment + warning
- solid a:fillOverlay → FillOverlay IR; unsupported fill families stay preserved

Edge cases:
- Multiple effects on one shape (order preserved)
- spread > 25% of min dim → poor-approximation warning
"""

from __future__ import annotations

import math
import re
import warnings as warnings_module
from html import unescape
from xml.etree.ElementTree import Element, fromstring

import pytest

from domoxml.core.drawingml.identity import node_identity_xml
from domoxml.core.drawingml.shape import _effects_xml
from domoxml.core.html import serialize_canvas
from domoxml.core.ir.effect_calibration import BOX_SHADOW_BLUR_TO_DML
from domoxml.core.ir.effect_payload import decode_effect_payload, decode_effects, encode_effects
from domoxml.core.ir.extract import _shadow_to_effect
from domoxml.core.ir.model import (
    Blur,
    Box,
    FillOverlay,
    Glow,
    GradientFill,
    GradientStop,
    PatternFill,
    PictureFill,
    PortableFallback,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    SrcRect,
    ThemeColorRef,
)
from domoxml.core.ir.parse import (
    fill_overlay_base_styles,
    parse_blur_filter,
    parse_box_reflection,
    parse_drop_shadow_filter,
    parse_fill_overlay,
    parse_fill_overlay_effect,
    parse_shadow,
    parse_shadows,
    parse_soft_edge_mask,
    parse_svg_fill_overlay_filter,
    parse_svg_soft_edge_filter,
)
from domoxml.core.units import px_to_emu
from domoxml.slides.appearance_read import fill_overlay_gradient, pattern_fill, rgba
from domoxml.slides.effect_read import Effect, read_effects
from domoxml.types import ConversionWarning, PreservedFragment

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def parse_effects_xml(
    properties: Element,
    colors: dict[str, str],
    *,
    box: Box | None = None,
) -> tuple[tuple[Effect, ...], tuple[ConversionWarning, ...], tuple[PreservedFragment, ...]]:
    return read_effects(
        properties,
        lambda element: rgba(element, colors),
        box=box,
        gradient_for=lambda element: fill_overlay_gradient(element, colors),
        pattern_for=lambda element: pattern_fill(element, colors),
    )


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _shape_props(xml_inner: str) -> Element:
    """Wrap effect XML in a minimal spPr element for parsing."""
    return fromstring(f'<a:spPr xmlns:a="{_A}">{xml_inner}</a:spPr>')


def _node(
    effects: tuple[object, ...] = (),
    width: int = 9_525_000,  # 1000 px in EMU
    height: int = 4_762_500,  # 500 px in EMU
) -> ShapeNode:
    return ShapeNode(
        box=Box(x=0, y=0, width=width, height=height),
        fill=SolidFill(color=Rgba(r=255, g=0, b=0)),
        effects=effects,  # type: ignore[arg-type]
    )


# -----------------------------------------------------------------------
# Forward: parse_shadow (spread parsed correctly)
# -----------------------------------------------------------------------


def test_parse_lone_css_blur_filter() -> None:
    assert parse_blur_filter("blur(4.5px)") == Blur(radius_emu=px_to_emu(4.5))
    assert parse_blur_filter("none") is None
    assert parse_blur_filter("blur(4px) brightness(0.8)") is None
    assert parse_blur_filter("blur(0.25em)") is None


def test_parse_computed_css_box_reflection() -> None:
    reflection = parse_box_reflection(
        "below 12px linear-gradient(rgba(0, 0, 0, 0.8) 0%, "
        "rgba(0, 0, 0, 0) 100%) 0 fill / auto / 0 stretch"
    )

    assert reflection == Reflection(
        distance_emu=px_to_emu(12),
        start_alpha=0.8,
        end_alpha=0.0,
    )


def test_parse_computed_css_soft_edge_mask() -> None:
    mask = (
        "linear-gradient(to right, rgba(0, 0, 0, 0) 0px, rgb(0, 0, 0) 12px, "
        "rgb(0, 0, 0) calc(100% - 12px), rgba(0, 0, 0, 0) 100%), "
        "linear-gradient(rgba(0, 0, 0, 0) 0px, rgb(0, 0, 0) 12px, "
        "rgb(0, 0, 0) calc(100% - 12px), rgba(0, 0, 0, 0) 100%)"
    )

    assert parse_soft_edge_mask(
        mask,
        "intersect, intersect",
        repeat="repeat, repeat",
        position="0% 0%, 0% 0%",
        size="auto, auto",
        origin="border-box, border-box",
        clip="border-box, border-box",
        mode="match-source, match-source",
    ) == SoftEdge(radius_emu=px_to_emu(12))


def test_parse_computed_css_ellipse_soft_edge_mask() -> None:
    mask = "radial-gradient(closest-side, rgb(0, 0, 0) calc(100% - 12px), rgba(0, 0, 0, 0) 100%)"

    assert parse_soft_edge_mask(mask, "intersect", ellipse=True) == SoftEdge(
        radius_emu=px_to_emu(12)
    )
    assert parse_soft_edge_mask(mask, "intersect", ellipse=False) is None


def test_parse_strict_svg_soft_edge_filter() -> None:
    valid = """
    <filter id="soft-edge" x="0" y="0" width="100%" height="100%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="softBlur"/>
      <feComposite in="softBlur" in2="SourceAlpha" operator="in" result="softClip"/>
      <feComposite in="SourceGraphic" in2="softClip" operator="in"/>
    </filter>
    """

    assert parse_svg_soft_edge_filter(valid) == SoftEdge(radius_emu=px_to_emu(12))
    assert parse_svg_soft_edge_filter(valid.replace('operator="in"', 'operator="out"', 1)) is None
    assert (
        parse_svg_soft_edge_filter(valid.replace('stdDeviation="6"', 'stdDeviation="6 4"')) is None
    )
    assert parse_svg_soft_edge_filter(valid.replace('x="0"', 'x="-20%"')) is None
    assert (
        parse_svg_soft_edge_filter(
            valid.replace('result="softBlur"', 'edgeMode="wrap" result="softBlur"')
        )
        is None
    )
    assert parse_svg_soft_edge_filter(valid.replace('id="soft-edge"', 'id=""')) is None
    assert (
        parse_svg_soft_edge_filter(valid.replace('stdDeviation="6"', f'stdDeviation="{"9" * 400}"'))
        is None
    )
    assert (
        parse_svg_soft_edge_filter(
            '<!DOCTYPE filter [<!ENTITY injected SYSTEM "file:///etc/passwd">]>'
            + valid.replace('id="soft-edge"', 'id="&injected;"')
        )
        is None
    )
    assert parse_svg_soft_edge_filter(valid.replace("</filter>", "<feFlood/></filter>")) is None


def test_parse_strict_svg_fill_overlay_filter() -> None:
    valid = """
    <filter id="fill-overlay" x="0" y="0" width="100%" height="100%"
            color-interpolation-filters="sRGB">
      <feFlood flood-color="rgb(244,63,94)" flood-opacity=".72" result="overlay"/>
      <feComposite in="overlay" in2="SourceAlpha" operator="in" result="overlayClip"/>
      <feBlend in="SourceGraphic" in2="overlayClip" mode="multiply"/>
    </filter>
    """

    assert parse_svg_fill_overlay_filter(valid) == FillOverlay(
        fill=SolidFill(color=Rgba(r=244, g=63, b=94, a=0.72)),
        blend="mult",
    )
    assert parse_svg_fill_overlay_filter(valid.replace('mode="multiply"', 'mode="overlay"')) is None
    assert parse_svg_fill_overlay_filter(valid.replace('operator="in"', 'operator="out"')) is None
    assert parse_svg_fill_overlay_filter(valid.replace("sRGB", "linearRGB")) is None
    assert parse_svg_fill_overlay_filter(valid.replace("rgb(244,63,94)", "rgb(300,63,94)")) is None
    assert (
        parse_svg_fill_overlay_filter(valid.replace('flood-opacity=".72"', 'flood-opacity="0"'))
        is None
    )
    assert (
        parse_svg_fill_overlay_filter(
            valid.replace('result="overlay"', 'result="overlay" x="0"', 1)
        )
        is None
    )
    assert parse_svg_fill_overlay_filter(valid.replace("</filter>", "<feOffset/></filter>")) is None


def test_rejects_css_masks_that_are_not_exact_soft_edges() -> None:
    valid = (
        "linear-gradient(to right, rgba(0,0,0,0) 0px, rgb(0,0,0) 12px, "
        "rgb(0,0,0) calc(100% - 12px), rgba(0,0,0,0) 100%),"
        "linear-gradient(rgba(0,0,0,0) 0px, rgb(0,0,0) 12px, "
        "rgb(0,0,0) calc(100% - 12px), rgba(0,0,0,0) 100%)"
    )
    unequal_axes = valid.replace("12px", "8px", 2)
    intermediate_stop = valid.replace("rgb(0,0,0) 12px", "rgb(0,0,0) 6px,rgb(0,0,0) 12px", 1)

    assert parse_soft_edge_mask(valid, "add, add") is None
    assert parse_soft_edge_mask(unequal_axes, "intersect, intersect") is None
    assert parse_soft_edge_mask(intermediate_stop, "intersect, intersect") is None
    assert parse_soft_edge_mask("radial-gradient(black,transparent)", "intersect") is None
    assert parse_soft_edge_mask(valid, "intersect, intersect", size="50% 50%, 50% 50%") is None


def test_rejects_malformed_css_soft_edge_lengths_without_raising() -> None:
    linear = (
        "linear-gradient(to right, transparent 0px, black {radius}px, "
        "black calc(100% - {radius}px), transparent 100%),"
        "linear-gradient(transparent 0px, black {radius}px, "
        "black calc(100% - {radius}px), transparent 100%)"
    )
    radial = "radial-gradient(closest-side, black calc(100% - {radius}px), transparent 100%)"

    for malformed in (".", "1..2"):
        assert parse_soft_edge_mask(linear.format(radius=malformed), "intersect, intersect") is None
        assert (
            parse_soft_edge_mask(radial.format(radius=malformed), "intersect", ellipse=True) is None
        )


def test_parse_solid_css_fill_overlay() -> None:
    assert parse_fill_overlay(
        "linear-gradient(rgb(255, 40, 80), rgb(255, 40, 80))",
        "rgb(20, 60, 140)",
        "multiply",
    ) == (
        SolidFill(color=Rgba(r=20, g=60, b=140)),
        FillOverlay(
            fill=SolidFill(color=Rgba(r=255, g=40, b=80)),
            blend="mult",
        ),
    )


def test_rejects_css_that_is_not_an_exact_solid_fill_overlay() -> None:
    constant = "linear-gradient(rgb(255, 40, 80), rgb(255, 40, 80))"

    assert parse_fill_overlay(constant, "rgb(20, 60, 140)", "normal") is None
    assert (
        parse_fill_overlay(
            "linear-gradient(rgb(255, 40, 80), rgb(0, 0, 0))",
            "rgb(20, 60, 140)",
            "multiply",
        )
        is None
    )
    assert parse_fill_overlay(constant, "transparent", "multiply") is None
    assert parse_fill_overlay(constant, "rgb(20, 60, 140)", "color-burn") is None
    assert (
        parse_fill_overlay(
            constant,
            "rgb(20, 60, 140)",
            "multiply",
            background_size="50% 50%",
            background_repeat="no-repeat",
        )
        is None
    )
    assert (
        parse_fill_overlay(
            constant,
            "rgb(20, 60, 140)",
            "multiply",
            background_size="100% 100%",
            background_position="10px 10px",
        )
        is None
    )
    assert (
        parse_fill_overlay(
            constant,
            "rgb(20, 60, 140)",
            "multiply",
            background_origin="content-box",
        )
        is None
    )


def test_normalized_fill_overlay_peels_per_layer_background_geometry() -> None:
    effect = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )

    base = fill_overlay_base_styles(
        "linear-gradient(rgba(255, 40, 80, .75), rgba(255, 40, 80, .75)),url(asset.png)",
        "multiply,normal",
        effect,
        background_size="auto,200% 100%",
        background_position="0% 0%,50% 50%",
        background_repeat="repeat,no-repeat",
    )

    assert base is not None
    assert base["backgroundImage"] == "url(asset.png)"
    assert base["backgroundSize"] == "200% 100%"
    assert base["backgroundPosition"] == "50% 50%"
    assert base["backgroundRepeat"] == "no-repeat"


def test_parse_picture_fill_overlay_peels_one_uniform_top_layer() -> None:
    image = "linear-gradient(rgba(255, 40, 80, .75), rgba(255, 40, 80, .75)),url(asset.png)"

    effect = parse_fill_overlay_effect(
        image,
        "multiply,normal",
        background_size="auto,cover",
        background_position="0% 0%,50% 50%",
        background_repeat="repeat,no-repeat",
    )

    assert effect is not None
    assert effect == FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )
    assert (
        parse_fill_overlay_effect(
            image,
            "multiply,normal",
            background_color="rgb(20,60,140)",
        )
        is None
    )
    assert parse_fill_overlay(image, "rgb(20,60,140)", "multiply,normal") is None
    assert (
        parse_fill_overlay_effect(
            image,
            "multiply,screen",
            background_size="auto,cover",
            background_position="0% 0%,50% 50%",
            background_repeat="repeat,no-repeat",
        )
        is None
    )
    assert (
        parse_fill_overlay_effect(
            "linear-gradient(red,red),linear-gradient(blue,blue)",
            "multiply,normal",
        )
        is None
    )
    assert (
        parse_fill_overlay_effect(
            "linear-gradient(red,red),url(asset.png),url(second.png)",
            "multiply,normal,normal",
        )
        is None
    )
    assert (
        parse_fill_overlay_effect(
            image,
            "multiply,normal",
            background_size="50% 50%,cover",
            background_position="100% 100%,50% 50%",
            background_repeat="no-repeat,no-repeat",
        )
        is None
    )


def test_parse_gradient_fill_overlay_preserves_stops_and_angle() -> None:
    effect = parse_fill_overlay_effect(
        ("linear-gradient(90deg,rgba(244,63,94,.8) 0%,rgba(37,99,235,.35) 100%),url(asset.png)"),
        "screen,normal",
        background_color="rgba(0,0,0,0)",
        background_size="auto,cover",
        background_position="0% 0%,50% 50%",
        background_repeat="repeat,no-repeat",
    )

    assert effect is not None
    assert effect == FillOverlay(
        fill=GradientFill(
            stops=(
                GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
            ),
            angle_deg=90.0,
        ),
        blend="screen",
    )
    assert fill_overlay_base_styles(
        ("linear-gradient(90deg,rgba(244,63,94,.8) 0%,rgba(37,99,235,.35) 100%),url(asset.png)"),
        "screen,normal",
        effect,
        background_size="auto,cover",
        background_position="0% 0%,50% 50%",
        background_repeat="repeat,no-repeat",
    ) == {
        "backgroundImage": "url(asset.png)",
        "backgroundBlendMode": "normal",
        "backgroundSize": "cover",
        "backgroundPosition": "50% 50%",
        "backgroundRepeat": "no-repeat",
        "backgroundOrigin": "padding-box",
        "backgroundClip": "border-box",
    }


def test_parse_pattern_fill_overlay_preserves_preset_and_colours() -> None:
    pattern = (
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px)"
    )
    effect = parse_fill_overlay_effect(
        pattern,
        "multiply",
        background_color="rgb(20,60,140)",
    )

    expected = FillOverlay(
        fill=PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        blend="mult",
    )
    assert effect == expected
    assert fill_overlay_base_styles(pattern, "multiply", expected) == {
        "backgroundImage": "none",
        "backgroundBlendMode": "normal",
        "backgroundSize": "auto",
        "backgroundPosition": "0% 0%",
        "backgroundRepeat": "repeat",
        "backgroundOrigin": "padding-box",
        "backgroundClip": "border-box",
    }


@pytest.mark.parametrize(
    "pattern",
    (
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 2px,"
        "rgb(254,226,226) 2px,rgb(254,226,226) 5px)",
        "repeating-linear-gradient(0.5deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px)",
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgba(244,63,94,0.2) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px)",
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px,"
        "transparent 4px)",
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px,"
        "color(display-p3 1 0 0) 4px)",
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0.0000005px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px)",
        "repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1.0000005px,rgb(254,226,226) 4px)",
    ),
)
def test_rejects_noncanonical_repeating_gradient_fill_overlay(pattern: str) -> None:
    assert (
        parse_fill_overlay_effect(
            pattern,
            "multiply",
            background_color="rgb(20,60,140)",
        )
        is None
    )


@pytest.mark.parametrize(
    ("pattern", "blend"),
    (
        (
            "repeating-linear-gradient(90deg,"
            "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
            "rgb(254,226,226) 1px,rgb(254,226,226) 4px)",
            "multiply",
        ),
        (
            "repeating-linear-gradient(0deg,"
            "rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
            "rgb(254,226,226) 1px,rgb(254,226,226) 4px)",
            "screen",
        ),
    ),
)
def test_rejects_renderer_unproven_pattern_fill_overlay(pattern: str, blend: str) -> None:
    assert (
        parse_fill_overlay_effect(
            pattern,
            blend,
            background_color="rgb(20,60,140)",
        )
        is None
    )


def test_rejects_css_reflection_that_cannot_map_to_current_ir() -> None:
    assert parse_box_reflection("above 12px linear-gradient(black, transparent)") is None
    assert parse_box_reflection("below 1em linear-gradient(black, transparent)") is None
    assert parse_box_reflection("below 12px none") is None
    assert (
        parse_box_reflection(
            "below 12px linear-gradient(to right, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%)"
        )
        is None
    )
    assert (
        parse_box_reflection("below 12px linear-gradient(rgba(0,0,0,0.8) 10%, rgba(0,0,0,0) 90%)")
        is None
    )
    assert (
        parse_box_reflection(
            "below 12px linear-gradient(rgba(0,0,0,0.8) 0%, "
            "rgba(0,0,0,0.4) 50%, rgba(0,0,0,0) 100%)"
        )
        is None
    )


def test_parse_shadow_captures_spread() -> None:
    shadow = parse_shadow("5px 10px 8px 3px rgba(0,0,0,0.5)")
    assert shadow is not None
    assert shadow.spread_emu == px_to_emu(3)
    assert shadow.blur_emu == px_to_emu(8)
    assert shadow.distance_emu == pytest.approx(px_to_emu(math.hypot(5, 10)), abs=1)


def test_parse_shadow_captures_negative_spread() -> None:
    shadow = parse_shadow("18px 22px 26px -10px rgba(0,0,0,0.5)")
    assert shadow is not None
    assert shadow.spread_emu == px_to_emu(-10)
    assert shadow.blur_emu == px_to_emu(26)
    assert shadow.distance_emu == pytest.approx(px_to_emu(math.hypot(18, 22)), abs=1)


def test_parse_shadow_zero_spread_when_absent() -> None:
    shadow = parse_shadow("5px 10px 8px rgba(0,0,0,0.5)")
    assert shadow is not None
    assert shadow.spread_emu == 0


def test_parse_shadow_inset_flag() -> None:
    shadow = parse_shadow("inset 2px 2px 4px 1px rgba(0,0,0,0.4)")
    assert shadow is not None
    assert shadow.inset is True
    assert shadow.spread_emu == px_to_emu(1)


def test_parse_shadows_retains_every_css_layer_in_paint_order() -> None:
    shadows = parse_shadows(
        "18px 22px 24px 0 rgba(15,23,42,.55), -28px 30px 32px 3px rgba(225,29,72,.65)"
    )

    assert len(shadows) == 2
    assert [shadow.color.hex for shadow in shadows] == ["0F172A", "E11D48"]
    assert shadows[0].distance_emu == px_to_emu(math.hypot(18, 22))
    assert shadows[1].spread_emu == px_to_emu(3)


def test_parse_single_drop_shadow_filter() -> None:
    shadow = parse_drop_shadow_filter("drop-shadow(rgba(10, 20, 30, 0.4) 6px 8px 12px)")

    assert shadow is not None
    assert shadow.color == Rgba(r=10, g=20, b=30, a=0.4)
    assert shadow.distance_emu == px_to_emu(10)
    assert shadow.direction_deg == pytest.approx(53.130102)
    assert shadow.blur_emu == px_to_emu(12)
    assert parse_drop_shadow_filter("drop-shadow(1px 2px 3px) blur(2px)") is None
    assert parse_drop_shadow_filter("brightness(0.8)") is None


# -----------------------------------------------------------------------
# Forward: glow-vs-shadow decision
# -----------------------------------------------------------------------


def test_zero_offset_shadow_becomes_glow() -> None:
    # box-shadow: 0 0 20px 5px color → should become Glow, not Shadow
    shadow = parse_shadow("0px 0px 20px 5px rgba(100,200,50,0.8)")
    assert shadow is not None
    dummy_warnings: list[ConversionWarning] = []
    box = Box(x=0, y=0, width=9_525_000, height=4_762_500)
    effect = _shadow_to_effect(shadow, box, dummy_warnings)
    assert isinstance(effect, Glow)
    assert effect.radius_emu == round((shadow.blur_emu + shadow.spread_emu) * 0.85)
    assert effect.color == shadow.color.model_copy(update={"a": shadow.color.a * 0.6})


def test_zero_offset_negative_spread_stays_outer_shadow() -> None:
    shadow = parse_shadow("0px 0px 30px -8px rgba(100,200,50,0.8)")
    assert shadow is not None
    effect = _shadow_to_effect(
        shadow,
        Box(x=0, y=0, width=9_525_000, height=4_762_500),
        [],
    )
    assert isinstance(effect, Shadow)
    assert effect.inset is False
    assert effect.distance_emu == 0
    assert effect.blur_emu == round(px_to_emu(30) * BOX_SHADOW_BLUR_TO_DML)
    assert effect.spread_emu == px_to_emu(-8)


def test_nonzero_offset_shadow_stays_shadow() -> None:
    # box-shadow: 5px 3px 10px 2px color → stays Shadow
    shadow = parse_shadow("5px 3px 10px 2px rgba(100,200,50,0.8)")
    assert shadow is not None
    dummy_warnings: list[ConversionWarning] = []
    box = Box(x=0, y=0, width=9_525_000, height=4_762_500)
    effect = _shadow_to_effect(shadow, box, dummy_warnings)
    assert isinstance(effect, Shadow)
    assert effect.blur_emu == round(shadow.blur_emu * BOX_SHADOW_BLUR_TO_DML)
    assert effect.distance_emu == shadow.distance_emu
    assert effect.spread_emu == shadow.spread_emu


def test_inset_shadow_stays_shadow_not_glow() -> None:
    shadow = parse_shadow("inset 0px 0px 10px 0px rgba(0,0,0,0.5)")
    assert shadow is not None
    dummy_warnings: list[ConversionWarning] = []
    box = Box(x=0, y=0, width=9_525_000, height=4_762_500)
    effect = _shadow_to_effect(shadow, box, dummy_warnings)
    assert isinstance(effect, Shadow)
    assert effect.inset is True


def test_inset_spread_intent_serializes_without_preassigned_node_id() -> None:
    shape = ShapeNode(
        box=Box(x=0, y=0, width=100_000, height=100_000),
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.4),
                blur_emu=40_000,
                distance_emu=20_000,
                spread_emu=10_000,
                inset=True,
            ),
        ),
    )

    xml = node_identity_xml(shape)

    assert "effectIntent=" in xml
    assert 'id="' not in xml


# -----------------------------------------------------------------------
# Forward: outerShdw XML with spread → sx/sy
# -----------------------------------------------------------------------


def test_outer_shadow_xml_has_sx_sy_for_spread() -> None:
    # Shape: width=10000 EMU, height=5000 EMU; spread=2000 EMU
    # sx = round((10000 + 2*2000) / 10000 * 100000) = round(1.4 * 100000) = 140000
    # sy = round((5000 + 2*2000) / 5000 * 100000) = round(1.8 * 100000) = 180000
    w, h, s = 10_000, 5_000, 2_000
    node = _node(
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.5),
                blur_emu=1_000,
                distance_emu=500,
                direction_deg=45,
                spread_emu=s,
            ),
        ),
        width=w,
        height=h,
    )
    xml = _effects_xml(node)
    expected_sx = round((w + 2 * s) / w * 100_000)
    expected_sy = round((h + 2 * s) / h * 100_000)
    assert f'sx="{expected_sx}"' in xml
    assert f'sy="{expected_sy}"' in xml
    assert "outerShdw" in xml


def test_outer_shadow_xml_has_sub_100_percent_scale_for_negative_spread() -> None:
    node = _node(
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.5),
                blur_emu=1_000,
                distance_emu=500,
                direction_deg=45,
                spread_emu=-1_000,
            ),
        ),
        width=10_000,
        height=5_000,
    )

    xml = _effects_xml(node)

    assert 'sx="80000"' in xml
    assert 'sy="60000"' in xml
    assert "outerShdw" in xml


def test_outer_shadow_xml_no_sx_sy_without_spread() -> None:
    node = _node(
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.5),
                blur_emu=1_000,
                distance_emu=500,
                direction_deg=45,
                spread_emu=0,
            ),
        ),
    )
    xml = _effects_xml(node)
    assert "sx=" not in xml
    assert "sy=" not in xml


def test_outer_shadow_spread_warning_when_large() -> None:
    # spread > 25% of min dim triggers a warning
    w, h, s = 10_000, 5_000, 2_000  # s/h = 40% > 25%
    node = _node(
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.5),
                blur_emu=0,
                distance_emu=0,
                direction_deg=0,
                spread_emu=s,
            ),
        ),
        width=w,
        height=h,
    )
    with warnings_module.catch_warnings(record=True) as caught:
        warnings_module.simplefilter("always")
        _effects_xml(node)
    assert any(
        "spread" in str(w.message).lower() and "approximation" in str(w.message).lower()
        for w in caught
    )


# -----------------------------------------------------------------------
# Forward: innerShdw with spread → blurRad approximation + warning
# -----------------------------------------------------------------------


def test_inner_shadow_spread_approximates_blur_and_warns() -> None:
    node = _node(
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0, a=0.5),
                blur_emu=2_000,
                distance_emu=500,
                direction_deg=135,
                inset=True,
                spread_emu=1_000,
            ),
        ),
    )
    with warnings_module.catch_warnings(record=True) as caught:
        warnings_module.simplefilter("always")
        xml = _effects_xml(node)
    assert "innerShdw" in xml
    assert 'blurRad="3000"' in xml  # blur + spread = 2000 + 1000
    assert any("spread" in str(w.message).lower() for w in caught)


# -----------------------------------------------------------------------
# Forward: Glow XML
# -----------------------------------------------------------------------


def test_glow_xml_emitted() -> None:
    node = _node(
        effects=(Glow(color=Rgba(r=255, g=200, b=0, a=0.8), radius_emu=5_000),),
    )
    xml = _effects_xml(node)
    assert "<a:glow" in xml
    assert 'rad="5000"' in xml


def test_fill_overlay_xml_emitted() -> None:
    overlay = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )

    xml = _effects_xml(_node(effects=(overlay,)))

    assert (
        '<a:fillOverlay blend="mult"><a:solidFill><a:srgbClr val="FF2850">'
        '<a:alpha val="75000"/></a:srgbClr></a:solidFill></a:fillOverlay>' in xml
    )


def test_gradient_fill_overlay_xml_is_aspect_projected_and_subdivided() -> None:
    overlay = FillOverlay(
        fill=GradientFill(
            stops=(
                GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
            ),
            angle_deg=90.0,
        ),
        blend="screen",
    )

    xml = _effects_xml(_node(effects=(overlay,)))

    assert '<a:fillOverlay blend="screen"><a:gradFill>' in xml
    assert xml.count("<a:gs pos=") == 9
    assert '<a:gs pos="0"><a:srgbClr val="F43F5E"><a:alpha val="80000"/>' in xml
    assert '<a:gs pos="100000"><a:srgbClr val="2563EB"><a:alpha val="35000"/>' in xml
    assert '<a:lin ang="0" scaled="1"/></a:gradFill></a:fillOverlay>' in xml


def test_pattern_fill_overlay_xml_is_native_and_editable() -> None:
    overlay = FillOverlay(
        fill=PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        blend="mult",
    )

    xml = _effects_xml(_node(effects=(overlay,)))

    assert (
        '<a:fillOverlay blend="mult"><a:pattFill prst="horz">'
        '<a:fgClr><a:srgbClr val="F43F5E"></a:srgbClr></a:fgClr>'
        '<a:bgClr><a:srgbClr val="FEE2E2"></a:srgbClr></a:bgClr>'
        "</a:pattFill></a:fillOverlay>" in xml
    )


@pytest.mark.parametrize(
    "pattern",
    (
        PatternFill(
            preset="vert",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        PatternFill(
            preset="diagCross",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94, a=0.5),
            bg=Rgba(r=254, g=226, b=226),
        ),
        PatternFill(
            preset="horz",
            fg=ThemeColorRef(slot="accent1"),
            bg=Rgba(r=254, g=226, b=226),
        ),
        PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=244, g=63, b=94),
        ),
    ),
)
def test_pattern_fill_overlay_rejects_unproven_direct_ir(pattern: PatternFill) -> None:
    with pytest.raises(
        ValueError,
        match="pattern fill overlays require the renderer-proven horizontal multiply pattern",
    ):
        FillOverlay(fill=pattern, blend="mult")


def test_pattern_fill_overlay_rejects_unproven_direct_ir_blend() -> None:
    pattern = PatternFill(
        preset="horz",
        fg=Rgba(r=244, g=63, b=94),
        bg=Rgba(r=254, g=226, b=226),
    )

    with pytest.raises(
        ValueError,
        match="pattern fill overlays require the renderer-proven horizontal multiply pattern",
    ):
        FillOverlay(fill=pattern, blend="screen")


def test_effect_list_xml_uses_schema_order_instead_of_ir_tuple_order() -> None:
    effects = (
        SoftEdge(radius_emu=8_000),
        Reflection(distance_emu=7_000),
        Shadow(
            color=Rgba(r=0, g=0, b=0, a=0.4),
            blur_emu=6_000,
            distance_emu=5_000,
        ),
        Glow(color=Rgba(r=0, g=128, b=255, a=0.6), radius_emu=4_000),
        FillOverlay(
            fill=SolidFill(color=Rgba(r=255, g=255, b=255, a=0.2)),
            blend="screen",
        ),
        Blur(radius_emu=3_000),
    )

    xml = _effects_xml(_node(effects=effects))

    positions = [
        xml.index(f"<a:{tag}")
        for tag in ("blur", "fillOverlay", "glow", "outerShdw", "reflection", "softEdge")
    ]
    assert positions == sorted(positions)


def test_mixed_shadow_effect_list_uses_schema_order_without_losing_ir_order() -> None:
    outer = Shadow(
        color=Rgba(r=15, g=23, b=42, a=0.55),
        blur_emu=76_200,
        distance_emu=148_827,
        direction_deg=50.19442890773481,
        spread_emu=-19_050,
    )
    inner = Shadow(
        color=Rgba(r=255, g=255, b=255, a=0.7),
        blur_emu=66_675,
        distance_emu=47_625,
        direction_deg=53.13010235415598,
        spread_emu=9_525,
        inset=True,
    )
    node = _node(effects=(outer, inner))

    xml = _effects_xml(node)

    assert xml.count("<a:innerShdw") == 1
    assert xml.count("<a:outerShdw") == 1
    assert xml.index("<a:innerShdw") < xml.index("<a:outerShdw")
    assert node.effects == (outer, inner)


def test_duplicate_effect_list_children_require_effect_dag() -> None:
    node = _node(
        effects=(
            Blur(radius_emu=3_000),
            Blur(radius_emu=4_000),
        )
    )

    with pytest.raises(ValueError, match="require an effectDag representation"):
        _effects_xml(node)


def test_schema_subset_projection_emits_one_child_per_effect_list_slot() -> None:
    front_outer = Shadow(
        color=Rgba(r=15, g=23, b=42, a=0.55),
        blur_emu=190_500,
        distance_emu=260_000,
        direction_deg=45,
    )
    inner = Shadow(
        color=Rgba(r=255, g=255, b=255, a=0.7),
        blur_emu=95_250,
        distance_emu=47_625,
        direction_deg=45,
        inset=True,
    )
    back_outer = Shadow(
        color=Rgba(r=225, g=29, b=72, a=0.65),
        blur_emu=285_750,
        distance_emu=430_000,
        direction_deg=135,
    )
    node = ShapeNode(
        box=Box(x=0, y=0, width=9_525_000, height=4_762_500),
        fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
        effects=(front_outer, inner, back_outer),
        native_effect_projection="schema_subset",
        portable_fallback=PortableFallback(
            box=Box(x=0, y=0, width=9_525_000, height=4_762_500),
            picture=PictureFill(data=b"exact-effect-layer", ext="png"),
        ),
    )

    xml = _effects_xml(node)

    assert xml.startswith("<a:effectLst>")
    assert xml.count("<a:outerShdw") == 1
    assert xml.count("<a:innerShdw") == 1
    assert 'val="0F172A"' in xml
    assert 'val="E11D48"' not in xml
    assert xml.index("<a:innerShdw") < xml.index("<a:outerShdw")


def test_sibling_shadow_container_emits_effect_dag_back_to_front() -> None:
    front = Shadow(
        color=Rgba(r=15, g=23, b=42, a=0.55),
        blur_emu=190_500,
        distance_emu=260_000,
        direction_deg=45,
    )
    back = Shadow(
        color=Rgba(r=225, g=29, b=72, a=0.65),
        blur_emu=285_750,
        distance_emu=430_000,
        direction_deg=135,
    )
    node = ShapeNode(
        box=Box(x=0, y=0, width=9_525_000, height=4_762_500),
        fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
        effects=(front, back),
        effect_container="sibling",
    )

    xml = _effects_xml(node)

    assert xml.startswith('<a:effectDag type="sib">')
    assert xml.index('val="E11D48"') < xml.index('val="0F172A"')
    assert xml.endswith('<a:effect ref="fill"/></a:effectDag>')


def test_shape_rejects_inset_shadow_in_sibling_effect_graph() -> None:
    with pytest.raises(ValueError, match="requires multiple outer shadows"):
        ShapeNode(
            box=Box(x=0, y=0, width=100_000, height=100_000),
            effects=(
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.4),
                    blur_emu=40_000,
                    distance_emu=20_000,
                    inset=True,
                ),
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.3),
                    blur_emu=30_000,
                    distance_emu=10_000,
                ),
            ),
            effect_container="sibling",
        )


def test_shape_rejects_schema_subset_projection_for_sibling_graph() -> None:
    with pytest.raises(ValueError, match="only supported for effect lists"):
        ShapeNode(
            box=Box(x=0, y=0, width=100_000, height=100_000),
            effects=(
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.4),
                    blur_emu=40_000,
                    distance_emu=20_000,
                ),
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.3),
                    blur_emu=30_000,
                    distance_emu=10_000,
                ),
            ),
            effect_container="sibling",
            native_effect_projection="schema_subset",
        )


def test_shape_rejects_schema_subset_projection_without_portable_fallback() -> None:
    with pytest.raises(ValueError, match="requires a portable fallback"):
        ShapeNode(
            box=Box(x=0, y=0, width=100_000, height=100_000),
            effects=(
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.4),
                    blur_emu=40_000,
                    distance_emu=20_000,
                ),
                Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.3),
                    blur_emu=30_000,
                    distance_emu=10_000,
                ),
            ),
            native_effect_projection="schema_subset",
        )


# -----------------------------------------------------------------------
# Reverse: parse_effects_xml — all 8 effect kinds
# -----------------------------------------------------------------------


def test_reverse_outer_shadow() -> None:
    props = _shape_props(
        "<a:effectLst>"
        '<a:outerShdw blurRad="50000" dist="30000" dir="2700000">'
        '<a:srgbClr val="FF0000"><a:alpha val="80000"/></a:srgbClr>'
        "</a:outerShdw>"
        "</a:effectLst>"
    )
    effects, warns, preserved = parse_effects_xml(props, {})
    assert len(effects) == 1
    shadow = effects[0]
    assert isinstance(shadow, Shadow)
    assert shadow.inset is False
    assert shadow.blur_emu == 50_000
    assert shadow.distance_emu == 30_000
    assert abs(shadow.direction_deg - 45.0) < 0.01  # 2700000 / 60000 = 45°
    assert shadow.color == Rgba(r=255, g=0, b=0, a=0.8)
    assert not warns
    assert not preserved


def test_reverse_outer_shadow_with_sx_sy_recovers_spread_from_shape_size() -> None:
    box = Box(x=0, y=0, width=100_000, height=50_000)
    props = _shape_props(
        "<a:effectLst>"
        '<a:outerShdw blurRad="0" dist="10000" dir="0" sx="120000" sy="140000">'
        '<a:srgbClr val="000000"/>'
        "</a:outerShdw>"
        "</a:effectLst>"
    )
    effects, _warns, _preserved = parse_effects_xml(props, {}, box=box)
    shadow = effects[0]
    assert isinstance(shadow, Shadow)
    assert shadow.spread_emu == 10_000


def test_reverse_outer_shadow_with_sub_100_percent_scale_recovers_negative_spread() -> None:
    box = Box(x=0, y=0, width=100_000, height=50_000)
    props = _shape_props(
        "<a:effectLst>"
        '<a:outerShdw blurRad="0" dist="0" dir="0" sx="80000" sy="60000">'
        '<a:srgbClr val="000000"/>'
        "</a:outerShdw>"
        "</a:effectLst>"
    )

    effects, _warns, _preserved = parse_effects_xml(props, {}, box=box)

    shadow = effects[0]
    assert isinstance(shadow, Shadow)
    assert shadow.spread_emu == -10_000


def test_reverse_outer_shadow_invalid_scale_uses_neutral_default() -> None:
    box = Box(x=0, y=0, width=100_000, height=50_000)
    props = _shape_props(
        "<a:effectLst>"
        '<a:outerShdw blurRad="0" dist="10000" dir="0" sx="invalid" sy="invalid">'
        '<a:srgbClr val="000000"/>'
        "</a:outerShdw>"
        "</a:effectLst>"
    )

    effects, _warns, _preserved = parse_effects_xml(props, {}, box=box)

    shadow = effects[0]
    assert isinstance(shadow, Shadow)
    assert shadow.spread_emu == 0


def test_reverse_inner_shadow() -> None:
    props = _shape_props(
        "<a:effectLst>"
        '<a:innerShdw blurRad="20000" dist="10000" dir="5400000">'
        '<a:srgbClr val="0000FF"/>'
        "</a:innerShdw>"
        "</a:effectLst>"
    )
    effects, _warns, _preserved = parse_effects_xml(props, {})
    shadow = effects[0]
    assert isinstance(shadow, Shadow)
    assert shadow.inset is True
    assert shadow.blur_emu == 20_000
    assert abs(shadow.direction_deg - 90.0) < 0.01


def test_reverse_glow() -> None:
    props = _shape_props(
        "<a:effectLst>"
        '<a:glow rad="30000">'
        '<a:srgbClr val="00FF00"><a:alpha val="60000"/></a:srgbClr>'
        "</a:glow>"
        "</a:effectLst>"
    )
    effects, warns, _preserved = parse_effects_xml(props, {})
    glow = effects[0]
    assert isinstance(glow, Glow)
    assert glow.radius_emu == 30_000
    assert glow.color == Rgba(r=0, g=255, b=0, a=0.6)
    assert not warns


def test_reverse_blur_produces_warning() -> None:
    props = _shape_props('<a:effectLst><a:blur rad="25000" grow="1"/></a:effectLst>')
    effects, warns, _preserved = parse_effects_xml(props, {})
    blur = effects[0]
    assert isinstance(blur, Blur)
    assert blur.radius_emu == 25_000
    assert len(warns) == 1
    assert "renderer fallback" in warns[0].message


def test_reverse_soft_edge() -> None:
    props = _shape_props('<a:effectLst><a:softEdge rad="15000"/></a:effectLst>')
    effects, warns, _preserved = parse_effects_xml(props, {})
    soft = effects[0]
    assert isinstance(soft, SoftEdge)
    assert soft.radius_emu == 15_000
    assert len(warns) == 1
    assert "renderer fallback" in warns[0].message


def test_reverse_zero_radius_soft_edge_does_not_claim_fallback() -> None:
    props = _shape_props('<a:effectLst><a:softEdge rad="0"/></a:effectLst>')

    effects, warns, _preserved = parse_effects_xml(props, {})

    assert effects == (SoftEdge(radius_emu=0),)
    assert not warns


def test_reverse_reflection() -> None:
    props = _shape_props(
        '<a:effectLst><a:reflection blurRad="5000" dist="0" stA="100000" endA="0"/></a:effectLst>'
    )
    effects, warns, _preserved = parse_effects_xml(props, {})
    refl = effects[0]
    assert isinstance(refl, Reflection)
    assert refl.blur_emu == 5_000
    assert refl.start_alpha == pytest.approx(1.0)
    assert refl.end_alpha == pytest.approx(0.0)
    assert len(warns) == 1
    assert "reflect" in warns[0].message.lower()


def test_reverse_reflection_tolerates_legacy_start_alpha_attribute() -> None:
    props = _shape_props('<a:effectLst><a:reflection startA="42000" endA="0"/></a:effectLst>')

    effects, _warns, _preserved = parse_effects_xml(props, {})

    assert isinstance(effects[0], Reflection)
    assert effects[0].start_alpha == pytest.approx(0.42)


def test_reverse_prst_shadow_preserved() -> None:
    props = _shape_props(
        "<a:effectLst>"
        '<a:prstShdw prst="shdw1" blurRad="0" dist="0" dir="0">'
        '<a:srgbClr val="000000"/>'
        "</a:prstShdw>"
        "</a:effectLst>"
    )
    effects, warns, preserved = parse_effects_xml(props, {})
    assert len(effects) == 0
    assert len(preserved) == 1
    assert preserved[0].kind == "prstShdw"
    assert len(warns) == 1
    assert "preserved" in warns[0].message


def test_reverse_solid_fill_overlay_is_typed() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="screen">'
        '<a:solidFill><a:srgbClr val="FF0000"><a:alpha val="65000"/></a:srgbClr></a:solidFill>'
        "</a:fillOverlay>"
    )
    props = _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>")
    effects, warns, preserved = parse_effects_xml(props, {})

    assert effects == (
        FillOverlay(
            fill=SolidFill(color=Rgba(r=255, g=0, b=0, a=0.65)),
            blend="screen",
        ),
    )
    assert preserved == ()
    assert "renderer fallback" in warns[0].message


def test_reverse_gradient_fill_overlay_is_typed() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="screen"><a:gradFill><a:gsLst>'
        '<a:gs pos="0"><a:srgbClr val="F43F5E"><a:alpha val="80000"/></a:srgbClr></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="2563EB"><a:alpha val="35000"/></a:srgbClr></a:gs>'
        '</a:gsLst><a:lin ang="0" scaled="1"/></a:gradFill></a:fillOverlay>'
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == (
        FillOverlay(
            fill=GradientFill(
                stops=(
                    GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                    GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
                ),
                angle_deg=90.0,
            ),
            blend="screen",
        ),
    )
    assert preserved == ()
    assert "renderer fallback" in warns[0].message


def test_reverse_pattern_fill_overlay_is_typed() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="mult"><a:pattFill prst="horz">'
        '<a:fgClr><a:srgbClr val="F43F5E"/></a:fgClr>'
        '<a:bgClr><a:srgbClr val="FEE2E2"/></a:bgClr>'
        "</a:pattFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == (
        FillOverlay(
            fill=PatternFill(
                preset="horz",
                fg=Rgba(r=244, g=63, b=94),
                bg=Rgba(r=254, g=226, b=226),
            ),
            blend="mult",
        ),
    )
    assert preserved == ()
    assert "renderer fallback" in warns[0].message


@pytest.mark.parametrize(
    ("preset", "blend"),
    (("diagCross", "mult"), ("vert", "mult"), ("horz", "screen")),
)
def test_reverse_unproven_pattern_fill_overlay_stays_preserved(preset: str, blend: str) -> None:
    fill_overlay = (
        f'<a:fillOverlay blend="{blend}"><a:pattFill prst="{preset}">'
        '<a:fgClr><a:srgbClr val="F43F5E"/></a:fgClr>'
        '<a:bgClr><a:srgbClr val="FEE2E2"/></a:bgClr>'
        "</a:pattFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_translucent_pattern_fill_overlay_stays_preserved() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="mult"><a:pattFill prst="horz">'
        '<a:fgClr><a:srgbClr val="F43F5E"><a:alpha val="50000"/></a:srgbClr></a:fgClr>'
        '<a:bgClr><a:srgbClr val="FEE2E2"/></a:bgClr>'
        "</a:pattFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_single_colour_pattern_fill_overlay_stays_preserved() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="mult"><a:pattFill prst="horz">'
        '<a:fgClr><a:srgbClr val="F43F5E"/></a:fgClr>'
        '<a:bgClr><a:srgbClr val="F43F5E"/></a:bgClr>'
        "</a:pattFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_radial_gradient_fill_overlay_is_typed() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="mult"><a:gradFill><a:gsLst>'
        '<a:gs pos="0"><a:srgbClr val="F43F5E"><a:alpha val="80000"/></a:srgbClr></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="2563EB"><a:alpha val="35000"/></a:srgbClr></a:gs>'
        '</a:gsLst><a:path path="circle"><a:fillToRect l="50000" t="50000" '
        'r="50000" b="50000"/></a:path></a:gradFill></a:fillOverlay>'
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == (
        FillOverlay(
            fill=GradientFill(
                stops=(
                    GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                    GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
                ),
                radial=True,
            ),
            blend="mult",
        ),
    )
    assert preserved == ()
    assert "renderer fallback" in warns[0].message


@pytest.mark.parametrize(
    "path",
    [
        '<a:path path="rect"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path>',
        '<a:path path="circle"><a:fillToRect l="40000" t="50000" r="50000" b="50000"/></a:path>',
        '<a:path path="circle"><a:fillToRect l="invalid" t="50000" r="50000" b="50000"/></a:path>',
        '<a:path path="circle"/>',
    ],
)
def test_reverse_unproven_radial_fill_overlay_geometry_stays_preserved(path: str) -> None:
    fill_overlay = (
        '<a:fillOverlay blend="mult"><a:gradFill><a:gsLst>'
        '<a:gs pos="0"><a:srgbClr val="F43F5E"><a:alpha val="80000"/></a:srgbClr></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="2563EB"><a:alpha val="35000"/></a:srgbClr></a:gs>'
        f"</a:gsLst>{path}</a:gradFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_ambiguous_fill_overlay_stays_preserved() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="screen">'
        '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>'
        "<a:gradFill><a:gsLst>"
        '<a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="0000FF"/></a:gs>'
        "</a:gsLst></a:gradFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_unsupported_fill_overlay_stays_preserved() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="over"><a:gradFill><a:gsLst>'
        '<a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="0000FF"/></a:gs>'
        "</a:gsLst></a:gradFill></a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


def test_reverse_over_fill_overlay_stays_preserved_until_css_semantics_are_proven() -> None:
    fill_overlay = (
        '<a:fillOverlay blend="over">'
        '<a:solidFill><a:srgbClr val="FF0000"><a:alpha val="65000"/></a:srgbClr></a:solidFill>'
        "</a:fillOverlay>"
    )

    effects, warns, preserved = parse_effects_xml(
        _shape_props(f"<a:effectLst>{fill_overlay}</a:effectLst>"), {}
    )

    assert effects == ()
    assert preserved[0].kind == "fillOverlay"
    assert "preserved" in warns[0].message


# -----------------------------------------------------------------------
# Reverse: multiple effects ordered correctly
# -----------------------------------------------------------------------


def test_reverse_multiple_effects_ordered() -> None:
    props = _shape_props(
        "<a:effectLst>"
        '<a:outerShdw blurRad="10000" dist="5000" dir="0">'
        '<a:srgbClr val="000000"/>'
        "</a:outerShdw>"
        '<a:glow rad="20000"><a:srgbClr val="FF0000"/></a:glow>'
        '<a:blur rad="5000"/>'
        "</a:effectLst>"
    )
    effects, _warns, _preserved = parse_effects_xml(props, {})
    assert len(effects) == 3
    assert isinstance(effects[0], Shadow)
    assert isinstance(effects[1], Glow)
    assert isinstance(effects[2], Blur)


def test_reverse_sibling_shadow_graph_restores_css_paint_order() -> None:
    props = _shape_props(
        '<a:effectDag type="sib">'
        '<a:outerShdw blurRad="285750" dist="430000" dir="8100000">'
        '<a:srgbClr val="E11D48"><a:alpha val="65000"/></a:srgbClr>'
        "</a:outerShdw>"
        '<a:outerShdw blurRad="190500" dist="260000" dir="2700000">'
        '<a:srgbClr val="0F172A"><a:alpha val="55000"/></a:srgbClr>'
        "</a:outerShdw>"
        '<a:effect ref="fill"/>'
        "</a:effectDag>"
    )

    effects, warnings, preserved = parse_effects_xml(props, {})

    assert [effect.color.hex for effect in effects if isinstance(effect, Shadow)] == [
        "0F172A",
        "E11D48",
    ]
    assert warnings == ()
    assert preserved == ()


def test_reverse_nested_effect_graph_is_preserved_whole() -> None:
    props = _shape_props(
        '<a:effectDag type="tree" name="unsupported">'
        '<a:cont type="sib"><a:blur rad="95250"/></a:cont>'
        "</a:effectDag>"
    )

    effects, warnings, preserved = parse_effects_xml(props, {})

    assert effects == ()
    assert len(warnings) == 1
    assert "effectDag" in warnings[0].message
    assert len(preserved) == 1
    assert preserved[0].kind == "effectDag"
    assert "<" in preserved[0].xml and "effectDag" in preserved[0].xml


# -----------------------------------------------------------------------
# Reverse → HTML CSS emission
# -----------------------------------------------------------------------


def _slide_with(*effects: object) -> SlideIR:
    return SlideIR(
        width=9_525_000,
        height=4_762_500,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=9_525_000, height=4_762_500),
                fill=SolidFill(color=Rgba(r=0, g=128, b=255)),
                effects=tuple(effects),  # type: ignore[arg-type]
            ),
        ),
    )


def test_html_shadow_includes_spread() -> None:
    slide = _slide_with(
        Shadow(
            color=Rgba(r=0, g=0, b=0, a=0.5),
            blur_emu=px_to_emu(10),
            distance_emu=px_to_emu(5),
            direction_deg=90,
            spread_emu=px_to_emu(3),
        )
    )
    html = serialize_canvas([slide])
    assert "box-shadow" in html.slides[0].html
    # spread 3px should appear in the box-shadow value
    assert "3" in html.slides[0].html


def test_html_shadow_includes_negative_spread() -> None:
    slide = _slide_with(
        Shadow(
            color=Rgba(r=0, g=0, b=0, a=0.5),
            blur_emu=round(px_to_emu(30) * BOX_SHADOW_BLUR_TO_DML),
            distance_emu=0,
            direction_deg=0,
            spread_emu=px_to_emu(-8),
        )
    )

    html = serialize_canvas([slide])

    match = re.search(r"box-shadow:0px 0px ([\d.]+)px -8px", html.slides[0].html)
    assert match is not None
    assert float(match.group(1)) == pytest.approx(30, abs=0.001)


def test_html_glow_emits_box_shadow() -> None:
    slide = _slide_with(Glow(color=Rgba(r=255, g=200, b=0, a=0.8), radius_emu=px_to_emu(20)))
    html = serialize_canvas([slide])
    assert "box-shadow" in html.slides[0].html
    # Centered: offset should be 0
    assert "0px 0px" in html.slides[0].html


def test_html_blur_emits_filter_and_warning() -> None:
    slide = _slide_with(Blur(radius_emu=px_to_emu(8)))
    html = serialize_canvas([slide])
    assert "filter" in html.slides[0].html
    assert "blur" in html.slides[0].html
    assert any("renderer fallback" in w.message for w in html.warnings)


def test_html_soft_edge_emits_mask() -> None:
    slide = _slide_with(SoftEdge(radius_emu=px_to_emu(10)))
    html = serialize_canvas([slide])
    assert "mask-image" in html.slides[0].html
    assert "linear-gradient(to right" in html.slides[0].html
    assert "linear-gradient(to bottom" in html.slides[0].html
    assert "mask-composite:intersect" in html.slides[0].html
    assert any("renderer fallback" in warning.message for warning in html.warnings)


def test_html_ellipse_soft_edge_emits_boundary_following_radial_mask() -> None:
    slide = _slide_with(SoftEdge(radius_emu=px_to_emu(10)))
    ellipse = slide.shapes[0].model_copy(update={"geom": "ellipse"})

    html = serialize_canvas([slide.model_copy(update={"contents": (ellipse,)})])

    assert "radial-gradient(ellipse closest-side" in html.slides[0].html
    assert "linear-gradient(to right" not in html.slides[0].html


def test_zero_radius_soft_edge_retains_payload_without_needless_mask() -> None:
    html = serialize_canvas([_slide_with(SoftEdge(radius_emu=0))])

    assert "data-domoxml-effects=" in html.slides[0].html
    assert "mask-image" not in html.slides[0].html
    assert not html.warnings


def test_html_reflection_emits_webkit_reflect_and_warning() -> None:
    slide = _slide_with(Reflection(distance_emu=px_to_emu(2), start_alpha=1.0, end_alpha=0.0))
    html = serialize_canvas([slide])
    assert "-webkit-box-reflect" in html.slides[0].html
    assert "background-color:rgba(0,128,255,1)" in html.slides[0].html
    assert any("renderer fallback" in w.message for w in html.warnings)


def test_html_fill_overlay_emits_composited_background_and_warning() -> None:
    overlay = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )

    html = serialize_canvas([_slide_with(overlay)])
    markup = html.slides[0].html

    assert "background-color:rgba(0,128,255,1)" in markup
    assert "background-image:linear-gradient(rgba(255,40,80,0.75),rgba(255,40,80,0.75))" in markup
    assert "background-blend-mode:multiply" in markup
    assert any("renderer fallback" in warning.message for warning in html.warnings)


def test_html_gradient_fill_overlay_emits_exact_gradient_and_payload() -> None:
    overlay = FillOverlay(
        fill=GradientFill(
            stops=(
                GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
            ),
            angle_deg=90.0,
        ),
        blend="screen",
    )

    html = serialize_canvas([_slide_with(overlay)])
    markup = html.slides[0].html

    assert (
        "background-image:linear-gradient(90deg,rgba(244,63,94,0.8) 0%,"
        "rgba(37,99,235,0.35) 100%)" in markup
    )
    assert "background-blend-mode:screen" in markup
    assert "&quot;fill&quot;:{&quot;kind&quot;:&quot;gradient&quot;" in markup
    assert any("renderer fallback" in warning.message for warning in html.warnings)


def test_html_pattern_fill_overlay_emits_exact_pattern_and_payload() -> None:
    overlay = FillOverlay(
        fill=PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        blend="mult",
    )

    html = serialize_canvas([_slide_with(overlay)])
    markup = html.slides[0].html

    assert (
        "background-image:repeating-linear-gradient(0deg,"
        "rgb(244,63,94) 0,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px)" in markup
    )
    assert "background-blend-mode:multiply" in markup
    assert "&quot;fill&quot;:{&quot;kind&quot;:&quot;pattern&quot;" in markup
    assert any("renderer fallback" in warning.message for warning in html.warnings)


def test_html_fill_overlay_keeps_picture_crop_geometry_on_the_base_layer() -> None:
    overlay = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
        blend="mult",
    )
    slide = _slide_with(overlay)
    shape = slide.shapes[0].model_copy(
        update={
            "fill": PictureFill(
                data=b"picture-bytes",
                ext="png",
                crop=SrcRect(left=0.25, right=0.25),
            )
        }
    )

    markup = serialize_canvas([slide.model_copy(update={"contents": (shape,)})]).slides[0].html

    assert "background-size:auto,200% 100%" in markup
    assert "background-position:0% 0%,50% 50%" in markup
    assert "background-repeat:repeat,no-repeat" in markup


def test_transparent_fill_overlay_retains_payload_without_needless_warning() -> None:
    overlay = FillOverlay(
        fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.0)),
        blend="screen",
    )

    html = serialize_canvas([_slide_with(overlay)])

    assert "data-domoxml-effects=" in html.slides[0].html
    assert "background-blend-mode:screen" in html.slides[0].html
    assert not html.warnings


def test_html_blurred_reflection_uses_owned_render_layer() -> None:
    slide = _slide_with(
        Reflection(
            blur_emu=px_to_emu(5),
            distance_emu=px_to_emu(2),
            start_alpha=1.0,
            end_alpha=0.0,
        )
    )

    html = serialize_canvas([slide])
    markup = html.slides[0].html

    assert "-webkit-box-reflect" not in markup
    assert 'data-domoxml-reflection-distance="2"' in markup
    assert 'data-domoxml-reflection-blur="5"' in markup
    assert 'data-domoxml-render-layer="true"' in markup
    assert "filter:blur(5px)" in markup
    assert "background-color:rgba(0,128,255,1)" in markup


def test_html_inset_shadow_has_inset_keyword() -> None:
    slide = _slide_with(
        Shadow(
            color=Rgba(r=0, g=0, b=0, a=0.5),
            blur_emu=px_to_emu(5),
            distance_emu=px_to_emu(2),
            direction_deg=45,
            inset=True,
        )
    )
    html = serialize_canvas([slide])
    assert "inset" in html.slides[0].html


def test_normalized_html_carries_exact_versioned_effect_payload() -> None:
    effects = (
        Shadow(
            color=Rgba(r=12, g=34, b=56, a=0.7),
            blur_emu=px_to_emu(9),
            distance_emu=px_to_emu(7),
            direction_deg=123,
            spread_emu=px_to_emu(2),
        ),
        Glow(color=Rgba(r=90, g=80, b=70, a=0.6), radius_emu=px_to_emu(11)),
    )

    html = serialize_canvas([_slide_with(*effects)])
    payload = encode_effects(effects)

    assert "data-domoxml-effects=" in html.slides[0].html
    assert decode_effects(payload) == effects
    assert decode_effects("not-json") is None


def test_normalized_html_retains_sibling_effect_container_metadata() -> None:
    effects = (
        Shadow(
            color=Rgba(r=15, g=23, b=42, a=0.55),
            blur_emu=px_to_emu(20),
            distance_emu=px_to_emu(24),
            direction_deg=45,
        ),
        Shadow(
            color=Rgba(r=225, g=29, b=72, a=0.65),
            blur_emu=px_to_emu(30),
            distance_emu=px_to_emu(36),
            direction_deg=135,
        ),
    )
    slide = _slide_with(*effects)
    shape = slide.shapes[0].model_copy(update={"effect_container": "sibling"})

    html = serialize_canvas([slide.model_copy(update={"contents": (shape,)})])
    match = re.search(r'data-domoxml-effects="([^"]+)"', html.slides[0].html)
    decoded = decode_effect_payload(unescape(match.group(1)) if match is not None else None)

    assert decoded is not None and decoded.container == "sibling"
    assert decoded.source_ref == "fill"
    assert decoded.effects == effects
    assert html.slides[0].html.count("rgba(") >= 3


def test_normalized_html_retains_schema_subset_native_projection() -> None:
    effects = (
        Shadow(
            color=Rgba(r=15, g=23, b=42, a=0.55),
            blur_emu=px_to_emu(20),
            distance_emu=px_to_emu(24),
            direction_deg=45,
        ),
        Shadow(
            color=Rgba(r=255, g=255, b=255, a=0.7),
            blur_emu=px_to_emu(10),
            distance_emu=px_to_emu(5),
            direction_deg=45,
            inset=True,
        ),
        Shadow(
            color=Rgba(r=225, g=29, b=72, a=0.65),
            blur_emu=px_to_emu(30),
            distance_emu=px_to_emu(36),
            direction_deg=135,
        ),
    )
    slide = _slide_with(*effects)
    shape = slide.shapes[0].model_copy(
        update={
            "native_effect_projection": "schema_subset",
            "portable_fallback": PortableFallback(
                box=slide.shapes[0].box,
                picture=PictureFill(data=b"exact-effect-layer", ext="png"),
            ),
        }
    )

    html = serialize_canvas([slide.model_copy(update={"contents": (shape,)})])
    match = re.search(r'data-domoxml-effects="([^"]+)"', html.slides[0].html)
    decoded = decode_effect_payload(unescape(match.group(1)) if match is not None else None)

    assert decoded is not None
    assert decoded.effects == effects
    assert decoded.container == "list"
    assert decoded.native_projection == "schema_subset"


def test_effect_payload_rejects_unsupported_sibling_graphs() -> None:
    outer = Shadow(
        color=Rgba(r=15, g=23, b=42, a=0.55),
        blur_emu=px_to_emu(20),
        distance_emu=px_to_emu(24),
        direction_deg=45,
    )
    invalid_effect_sets = (
        (),
        (outer,),
        (outer, outer.model_copy(update={"inset": True})),
        (outer, Glow(color=Rgba(r=225, g=29, b=72), radius_emu=px_to_emu(12))),
    )

    for effects in invalid_effect_sets:
        list_payload = encode_effects(effects)
        sibling_payload = list_payload.replace('"container":"list"', '"container":"sibling"')
        assert decode_effect_payload(sibling_payload) is None
