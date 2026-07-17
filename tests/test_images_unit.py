"""Unit contracts for shared bitmap normalization and cropping helpers."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from domoxml.core.images import crop_slide_region


def _png() -> bytes:
    image = Image.new("RGB", (100, 50), "#2A7F62")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_slide_region_rounds_absolute_source_edges() -> None:
    crop = crop_slide_region(
        _png(),
        slide_width=1_000,
        slide_height=500,
        left=154,
        top=55,
        width=201,
        height=101,
    )

    assert crop is not None
    with Image.open(BytesIO(crop)) as image:
        assert image.size == (21, 10)


def test_slide_region_keeps_transparent_pixels_outside_viewport() -> None:
    crop = crop_slide_region(
        _png(),
        slide_width=1_000,
        slide_height=500,
        left=-100,
        top=-100,
        width=300,
        height=300,
    )

    assert crop is not None
    with Image.open(BytesIO(crop)) as image:
        assert image.size == (30, 30)
        transparent = image.convert("RGBA").getpixel((0, 0))
        painted = image.convert("RGBA").getpixel((15, 15))
        assert isinstance(transparent, tuple)
        assert isinstance(painted, tuple)
        assert transparent[3] == 0
        assert painted[:3] == (42, 127, 98)
