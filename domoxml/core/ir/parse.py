"""Parse the CSS computed-style strings Chromium reports into typed IR values.

Every parser is total and side-effect-free: it returns a typed value or ``None`` when the
CSS can't be mapped to a native OOXML construct, so the extractor can fall back to raster.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from domoxml.core.ir.model import GradientFill, GradientStop, Line, Rgba, Shadow
from domoxml.core.units import px_to_emu

_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)",
    re.IGNORECASE,
)
_LENGTH_RE = re.compile(r"(-?[\d.]+)\s*px", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(-?[\d.]+)\s*%")
_ANGLE_RE = re.compile(r"(-?[\d.]+)\s*deg", re.IGNORECASE)
_FUNC_RE = re.compile(r"\b(linear|radial|conic)-gradient\s*\(", re.IGNORECASE)


def parse_color(value: str | None) -> Rgba | None:
    """Parse a CSS ``rgb()/rgba()`` string into :class:`Rgba`, or ``None`` if unparseable."""
    if not value:
        return None
    match = _RGB_RE.search(value)
    if match is None:
        return None
    r, g, b = (round(float(match.group(i))) for i in (1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return Rgba(r=r, g=g, b=b, a=alpha)


def parse_length_px(value: str | None) -> float:
    """The first ``px`` length found in ``value`` (via ``_LENGTH_RE``), or 0.0 if there is none.

    Only the first match is returned, e.g. ``"12px 4px 4px 12px"`` → ``12.0``.
    """
    if not value:
        return 0.0
    match = _LENGTH_RE.search(value)
    return float(match.group(1)) if match else 0.0


def is_bold(font_weight: str | None) -> bool:
    """True for ``bold``/``bolder`` or a numeric weight >= 600."""
    if not font_weight:
        return False
    weight = font_weight.strip().lower()
    if weight in {"bold", "bolder"}:
        return True
    try:
        return int(weight) >= 600
    except ValueError:
        return False


# --------------------------------------------------------------------------- borders

def _dash_style(style_token: str) -> Literal["solid", "dash", "dot"]:
    if style_token == "dashed":
        return "dash"
    if style_token == "dotted":
        return "dot"
    return "solid"


def parse_border_side(width: str | None, style: str | None, color: str | None) -> Line | None:
    """Map one CSS border side (computed width/style/colour) to a :class:`Line`, or ``None``
    when there is no visible border (zero width, ``none``/``hidden`` style, transparent)."""
    style_token = (style or "none").strip().lower()
    if style_token in {"none", "hidden"}:
        return None
    width_px = parse_length_px(width)
    if width_px <= 0:
        return None
    rgba = parse_color(color)
    if rgba is None or rgba.a <= 0:
        return None
    return Line(color=rgba, width_emu=px_to_emu(width_px), dash=_dash_style(style_token))


# --------------------------------------------------------------------------- box-shadow


def _split_top_level(value: str) -> list[str]:
    """Split on commas that are not inside parentheses (separates gradient/shadow layers)."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def parse_shadow(value: str | None) -> Shadow | None:
    """Map the first layer of a CSS ``box-shadow`` to a :class:`Shadow`, or ``None`` when
    there is no shadow. Spread is dropped (no native OOXML equivalent)."""
    if not value or value.strip().lower() == "none":
        return None
    layer = _split_top_level(value)[0]
    rgba = parse_color(layer) or Rgba(r=0, g=0, b=0, a=0.5)
    inset = "inset" in layer.lower()
    lengths = [float(m) for m in _LENGTH_RE.findall(layer)]
    if len(lengths) < 2:
        return None
    offset_x, offset_y = lengths[0], lengths[1]
    blur = lengths[2] if len(lengths) > 2 else 0.0
    distance = math.hypot(offset_x, offset_y)
    # OOXML direction: 0° = East, 90° = South (y grows downward, same as CSS offsets).
    direction = math.degrees(math.atan2(offset_y, offset_x)) % 360.0
    return Shadow(
        color=rgba,
        blur_emu=px_to_emu(blur),
        distance_emu=px_to_emu(distance),
        direction_deg=direction,
        inset=inset,
    )


# --------------------------------------------------------------------------- gradients


def _gradient_body(value: str) -> tuple[str, bool] | None:
    """Return ``(inner-args, is_radial)`` for the first linear/radial gradient, or ``None``.

    ``conic-gradient`` (no native OOXML mapping) returns ``None`` so the element rasterises.
    """
    match = _FUNC_RE.search(value)
    if match is None or match.group(1).lower() == "conic":
        return None
    start = match.end()
    depth = 1
    for i in range(start, len(value)):
        if value[i] == "(":
            depth += 1
        elif value[i] == ")":
            depth -= 1
            if depth == 0:
                return value[start:i], match.group(1).lower() == "radial"
    return None


def _parse_stops(args: list[str]) -> tuple[GradientStop, ...]:
    """Parse the colour-stop arguments of a gradient into evenly-or-explicitly placed stops."""
    raw: list[tuple[Rgba, float | None]] = []
    for arg in args:
        color = parse_color(arg)
        if color is None:
            continue
        pct = _PERCENT_RE.search(arg)
        raw.append((color, float(pct.group(1)) / 100.0 if pct else None))
    if not raw:
        return ()
    # Fill in any missing positions by spreading them evenly across [0, 1].
    last = len(raw) - 1
    stops: list[GradientStop] = []
    for index, (color, pos) in enumerate(raw):
        resolved = pos if pos is not None else (index / last if last else 0.0)
        stops.append(GradientStop(pos=min(1.0, max(0.0, resolved)), color=color))
    return tuple(stops)


def parse_gradient(value: str | None) -> GradientFill | None:
    """Map a CSS ``linear-gradient``/``radial-gradient`` to a :class:`GradientFill`.

    Returns ``None`` for ``none``, ``url(...)``, ``conic-gradient``, stacked gradient layers,
    or any gradient with fewer than two parseable colour stops — those rasterise instead.
    """
    if not value or value.strip().lower() in {"none", ""}:
        return None
    if len(_split_top_level(value)) > 1:
        # Stacked, comma-separated layers have no single native fill — rasterise instead.
        # (Commas *inside* one gradient stay together: _split_top_level is paren-aware.)
        return None
    body = _gradient_body(value)
    if body is None:
        return None
    inner, radial = body
    args = _split_top_level(inner)
    angle = 180.0
    if args and _ANGLE_RE.search(args[0]) and parse_color(args[0]) is None:
        angle = float(_ANGLE_RE.search(args[0]).group(1))  # type: ignore[union-attr]
        args = args[1:]
    elif args and "to " in args[0].lower() and parse_color(args[0]) is None:
        angle = _KEYWORD_ANGLE.get(args[0].strip().lower(), 180.0)
        args = args[1:]
    stops = _parse_stops(args)
    if len(stops) < 2:
        return None
    return GradientFill(stops=stops, angle_deg=angle, radial=radial)


_KEYWORD_ANGLE = {
    "to top": 0.0,
    "to right": 90.0,
    "to bottom": 180.0,
    "to left": 270.0,
    "to top right": 45.0,
    "to bottom right": 135.0,
    "to bottom left": 225.0,
    "to top left": 315.0,
}
