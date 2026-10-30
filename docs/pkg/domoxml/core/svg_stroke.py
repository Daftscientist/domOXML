"""Bidirectional mappings between IR line presets and SVG stroke attributes."""

from __future__ import annotations

import math
import re

from domoxml.core.ir.model import DashStyle

_DASH_TOKEN = r"(?:\d+(?:\.\d*)?|\.\d+)(?:px)?"
_DASH_ARRAY_RE = re.compile(rf"\s*({_DASH_TOKEN}(?:[\s,]+{_DASH_TOKEN})*)\s*", re.IGNORECASE)

# Ratios are relative to stroke width. They keep each OOXML preset visually distinct while
# remaining stable when Chromium returns the computed SVG dash array in absolute pixels.
_SVG_DASH_RATIOS: dict[DashStyle, tuple[float, ...]] = {
    "solid": (),
    "dash": (4.0, 3.0),
    "dot": (1.0, 1.0),
    "dashDot": (4.0, 3.0, 1.0, 3.0),
    "lgDash": (8.0, 3.0),
    "sysDash": (3.0, 1.0),
}


def svg_dash_lengths(dash: DashStyle, width_px: float) -> tuple[float, ...]:
    """Return the SVG dash lengths for an IR preset at a physical stroke width."""
    return tuple(ratio * width_px for ratio in _SVG_DASH_RATIOS[dash])


def parse_svg_dasharray(value: str, width_px: float) -> DashStyle | None:
    """Map one of our SVG dash arrays back to its IR preset; reject arbitrary arrays."""
    match = _DASH_ARRAY_RE.fullmatch(value)
    if match is None or width_px <= 0:
        return None
    lengths = tuple(
        float(token.removesuffix("px")) for token in re.findall(_DASH_TOKEN, value.lower())
    )
    ratios = tuple(length / width_px for length in lengths)
    for dash, expected in _SVG_DASH_RATIOS.items():
        if (
            expected
            and len(ratios) == len(expected)
            and all(
                math.isclose(actual, target, rel_tol=0.0, abs_tol=0.01)
                for actual, target in zip(ratios, expected, strict=True)
            )
        ):
            return dash
    return None
