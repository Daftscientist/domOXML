"""``a:lum`` brightness and contrast, applied to the pixels as PowerPoint does."""

from __future__ import annotations

import io
from xml.etree.ElementTree import fromstring

from PIL import Image

from domoxml.slides.appearance_read import _with_luminance  # pyright: ignore[reportPrivateUsage]

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _png(pixel: tuple[int, int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (2, 2), pixel).save(buffer, "PNG")
    return buffer.getvalue()


def _adjusted(pixel: tuple[int, int, int, int], lum: str) -> tuple[int, int, int, int]:
    blip = fromstring(f'<a:blip xmlns:a="{_A}">{lum}</a:blip>')
    result = _with_luminance(_png(pixel), blip)
    assert result is not None
    with Image.open(io.BytesIO(result[0])) as image:
        return image.convert("RGBA").getpixel((0, 0))  # type: ignore[return-value]


def test_brightness_adds_a_fraction_of_the_range() -> None:
    # Measured in real PowerPoint: brightness 40% adds about 102 to each channel.
    assert _adjusted((138, 122, 63, 255), '<a:lum bright="40000"/>') == (240, 224, 165, 255)


def test_contrast_scales_about_mid_grey_after_the_brightness() -> None:
    # bright -20%, contrast +40%: 1.4 * (in - 51 - 127.5) + 127.5, clamped (measured: 226/124/0).
    red, green, blue, alpha = _adjusted(
        (247, 175, 77, 255), '<a:lum bright="-20000" contrast="40000"/>'
    )
    assert abs(red - 226) <= 6 and abs(green - 124) <= 6 and blue == 0 and alpha == 255


def test_alpha_is_left_alone_and_a_plain_blip_is_not_touched() -> None:
    assert _adjusted((10, 20, 30, 77), '<a:lum bright="10000"/>')[3] == 77
    plain = fromstring(f'<a:blip xmlns:a="{_A}"><a:lum/></a:blip>')
    assert _with_luminance(_png((1, 2, 3, 255)), plain) is None
    assert _with_luminance(_png((1, 2, 3, 255)), fromstring(f'<a:blip xmlns:a="{_A}"/>')) is None
