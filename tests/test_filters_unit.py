"""CSS filter colour functions as plain colour maths."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from domoxml.core.ir.filters import (
    apply_to_color,
    apply_to_image,
    is_lowerable,
    parse_filters,
)
from domoxml.core.ir.model import Rgba

RED = Rgba(r=200, g=40, b=20)


def lowered(css: str, color: Rgba = RED) -> Rgba:
    functions = parse_filters(css)
    assert functions is not None
    return apply_to_color(color, functions)


def test_parse_reads_functions_in_order_and_refuses_unknown_ones() -> None:
    functions = parse_filters("brightness(1.4) hue-rotate(90deg) opacity(50%)")

    assert functions is not None
    assert [(f.name, f.amount) for f in functions] == [
        ("brightness", 1.4),
        ("hue-rotate", 90.0),
        ("opacity", 0.5),
    ]
    assert parse_filters("brightness(1.2) url(#f)") is None
    assert parse_filters("none") == ()
    assert parse_filters("blur(2px) nonsense(3)") is None


def test_brightness_scales_each_channel_and_clamps() -> None:
    assert lowered("brightness(0.5)") == Rgba(r=100, g=20, b=10)
    assert lowered("brightness(2)").r == 255


def test_grayscale_is_the_spec_luminance_and_zero_leaves_the_colour() -> None:
    gray = lowered("grayscale(1)")
    expected = round(0.2126 * 200 + 0.7152 * 40 + 0.0722 * 20)
    assert (gray.r, gray.g, gray.b) == (expected, expected, expected)
    assert lowered("grayscale(0)") == RED


def test_invert_flips_and_half_inversion_is_flat_grey() -> None:
    assert lowered("invert(1)") == Rgba(r=55, g=215, b=235)
    half = lowered("invert(0.5)")
    assert (half.r, half.g, half.b) == (128, 128, 128)


def test_saturate_zero_matches_grayscale_and_hue_rotate_360_is_identity() -> None:
    assert lowered("saturate(0)") == lowered("grayscale(1)")
    turned = lowered("hue-rotate(360deg)")
    assert max(abs(turned.r - RED.r), abs(turned.g - RED.g), abs(turned.b - RED.b)) <= 1


def test_hue_rotate_moves_red_toward_blue_and_green() -> None:
    green_ish = lowered("hue-rotate(120deg)", Rgba(r=255, g=0, b=0))
    blue_ish = lowered("hue-rotate(240deg)", Rgba(r=255, g=0, b=0))
    assert green_ish.g > green_ish.r and blue_ish.b > blue_ish.r


def test_contrast_pivots_about_mid_grey_and_opacity_only_touches_alpha() -> None:
    assert lowered("contrast(0)", RED) == Rgba(r=128, g=128, b=128)
    faded = lowered("opacity(40%)")
    assert (faded.r, faded.g, faded.b) == (RED.r, RED.g, RED.b)
    assert abs(faded.a - 0.4) < 1e-9


def test_functions_compose_in_order() -> None:
    assert lowered("brightness(0.5) invert(1)") != lowered("invert(1) brightness(0.5)")


def test_only_colour_functions_and_drop_shadows_are_lowerable() -> None:
    assert is_lowerable(parse_filters("brightness(1.2) drop-shadow(1px 1px 2px red)") or ())
    assert not is_lowerable(parse_filters("blur(2px)") or ())
    assert not is_lowerable(())


def test_the_same_maths_applies_to_image_pixels() -> None:
    buffer = BytesIO()
    Image.new("RGBA", (2, 2), (200, 40, 20, 255)).save(buffer, "PNG")
    functions = parse_filters("grayscale(1)")
    assert functions is not None

    out = apply_to_image(buffer.getvalue(), functions)

    assert out is not None
    with Image.open(BytesIO(out)) as image:
        pixel = image.convert("RGBA").tobytes()[:4]
    expected = round(0.2126 * 200 + 0.7152 * 40 + 0.0722 * 20)
    assert tuple(pixel[:3]) == (expected,) * 3 and pixel[3] == 255
