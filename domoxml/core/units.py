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


_EMU_PER_PX = EMU_PER_INCH / PX_PER_INCH  # 9525.0


def px_to_emu(px: float) -> int:
    """Convert CSS pixels to EMUs."""
    return round(px * _EMU_PER_PX)


def emu_to_px(emu: int) -> float:
    """Convert EMUs to CSS pixels."""
    return emu / _EMU_PER_PX


def px_to_pt(px: float) -> float:
    """Convert CSS pixels to typographic points (1pt = 1/72in)."""
    return px * 72.0 / PX_PER_INCH


_EMU_PER_PT = EMU_PER_INCH / 72.0  # 12700.0


def pt_to_emu(pt: float) -> int:
    """Convert typographic points to EMUs."""
    return round(pt * _EMU_PER_PT)


def emu_to_pt(emu: int) -> float:
    """Convert EMUs to typographic points."""
    return emu / _EMU_PER_PT


# PowerPoint's ``a:blur rad`` is 3x the CSS blur standard deviation. Measured against Chrome in real
# PowerPoint with ``grow="0"`` blurs of a sharp test picture: at sigma 4, 8 and 16 px the best scale
# was 3 each time (error 6.6, 4.2 and 1.5 against 14-54 for 1x and 2x), and on the showcase glass
# 3x scored within noise of the browser's own pixels.
DRAWINGML_BLUR_RADIUS_PER_CSS_SIGMA = 3.0
