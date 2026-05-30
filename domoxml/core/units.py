"""Unit conversions for the render pipeline.

CSS lays out at 96px per inch; OOXML positions in EMUs (914400 per inch). The render
layer works in CSS pixels; later backends convert the captured geometry to EMUs.
"""

from __future__ import annotations

from domoxml.types import SizeSpec, SlideSize

PX_PER_INCH = 96.0
EMU_PER_INCH = 914_400


def dimensions_in(size: SizeSpec) -> tuple[float, float]:
    """Resolve a size spec to ``(width, height)`` in inches."""
    if isinstance(size, SlideSize):
        return size.dimensions_in
    return (size.width_in, size.height_in)


def pixels(size: SizeSpec) -> tuple[int, int]:
    """Resolve a size spec to integer ``(width, height)`` in CSS pixels."""
    width_in, height_in = dimensions_in(size)
    return round(width_in * PX_PER_INCH), round(height_in * PX_PER_INCH)


def px_to_emu(px: float) -> int:
    """Convert CSS pixels to EMUs."""
    return round(px / PX_PER_INCH * EMU_PER_INCH)
