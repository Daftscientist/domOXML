"""A chart graphic frame as a vector picture, so the reverse path needs no renderer pixels."""

from __future__ import annotations

import re
from collections.abc import Mapping

from domoxml.core.chart_svg import chart_to_svg
from domoxml.core.ir.model import Box, PictureFill, PreservationPayload
from domoxml.core.units import emu_to_px

# A transparent 1x1 PNG: the picture slot needs raster bytes, but the vector is what is drawn.
_BLANK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
)
_CHART_PART = re.compile(r"(?:^|/)charts?/chart\d*\.xml$")


def chart_picture(
    payload: PreservationPayload, box: Box, theme: Mapping[str, str] | None
) -> PictureFill | None:
    """The attached chart part drawn as an SVG picture of ``box``'s size, or ``None``."""
    part = next((p for p in payload.parts if _CHART_PART.search(p.name)), None)
    if part is None:
        return None
    svg = chart_to_svg(
        part.data,
        width_px=emu_to_px(box.width),
        height_px=emu_to_px(box.height),
        theme=theme,
    )
    if svg is None:
        return None
    return PictureFill(data=_BLANK_PNG, ext="png", svg_data=svg.encode())
