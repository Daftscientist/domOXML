"""Backgrounds that are several native shapes rather than one fill.

PowerPoint has no conic gradient and one fill per shape, but a conic gradient is a fan of coloured
wedges and a stack of background layers is a stack of shapes. Both are exact, editable and need no
raster. Wedges are clipped to the element's box (rounded corners included) so nothing spills out.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import pairwise

from domoxml.core.ir.lowering import mix_colors
from domoxml.core.ir.model import Rgba
from domoxml.core.ir.parse import parse_color, parse_gradient, split_top_level

type Polygon = list[tuple[float, float]]

_CONIC = re.compile(r"^\s*conic-gradient\s*\((.*)\)\s*$", re.IGNORECASE | re.DOTALL)
_FROM = re.compile(r"from\s+(-?[\d.]+)\s*(deg|turn|rad|grad)?", re.IGNORECASE)
_AT = re.compile(r"at\s+(-?[\d.]+)(%|px)\s+(-?[\d.]+)(%|px)", re.IGNORECASE)
_STOP_POSITION = re.compile(r"\s+(-?[\d.]+)(%|deg|turn)\s*$", re.IGNORECASE)
# A uniform 3 degree fan plus wedges at every stop reads as smooth; stops land on exact edges.
_STEP_DEGREES = 3.0
_OVERLAP_DEGREES = 0.25
_CORNER_SEGMENTS = 8


@dataclass(frozen=True)
class Conic:
    """A parsed conic gradient: start angle, centre as box fractions, and stops in degrees."""

    start_deg: float
    center: tuple[float, float]
    stops: tuple[tuple[float, Rgba], ...]


@dataclass(frozen=True)
class Wedge:
    """One coloured sector of a conic gradient, as a polygon in box coordinates (px)."""

    points: tuple[tuple[float, float], ...]
    color: Rgba


def stacked_gradients(value: str | None) -> list[str] | None:
    """The layers of a stacked gradient background, top first, or ``None`` if not all gradients."""
    if not value or value.strip().lower() == "none":
        return None
    layers = [layer.strip() for layer in split_top_level(value)]
    if len(layers) < 2 or any(parse_gradient(layer) is None for layer in layers):
        return None
    return layers


def parse_conic(value: str | None, *, width_px: float, height_px: float) -> Conic | None:
    """Parse one ``conic-gradient``; ``None`` for stacked layers or anything not understood."""
    if not value:
        return None
    match = _CONIC.match(value)
    if match is None or len(split_top_level(value)) > 1:
        return None
    parts = [part.strip() for part in split_top_level(match.group(1))]
    start, center = 0.0, (0.5, 0.5)
    if parts and not _has_color(parts[0]):
        prelude, parts = parts[0], parts[1:]
        from_match = _FROM.search(prelude)
        if from_match is not None:
            factor = {"": 1.0, "deg": 1.0, "turn": 360.0, "rad": 180 / math.pi, "grad": 0.9}
            start = float(from_match.group(1)) * factor[(from_match.group(2) or "").lower()]
        at_match = _AT.search(prelude)
        if at_match is not None:
            x, x_unit, y, y_unit = at_match.groups()
            center = (
                float(x) / 100 if x_unit == "%" else float(x) / width_px,
                float(y) / 100 if y_unit == "%" else float(y) / height_px,
            )
    raw: list[tuple[Rgba, float | None]] = []
    for part in parts:
        position = _STOP_POSITION.search(part)
        color = parse_color(part[: position.start()] if position else part)
        if color is None:
            return None
        angle = None
        if position is not None:
            amount, unit = float(position.group(1)), position.group(2).lower()
            angle = amount * 3.6 if unit == "%" else amount * 360 if unit == "turn" else amount
        raw.append((color, angle))
    resolved = _resolve_angles(raw)
    return Conic(start, center, tuple(resolved)) if resolved is not None else None


def _has_color(part: str) -> bool:
    return parse_color(_STOP_POSITION.sub("", part)) is not None


def _resolve_angles(raw: list[tuple[Rgba, float | None]]) -> list[tuple[float, Rgba]] | None:
    """CSS stop defaults: the first is 0, the last 360, the rest spread evenly; never backwards."""
    if len(raw) < 2:
        return None
    angles: list[float | None] = [angle for _, angle in raw]
    angles[0] = 0.0 if angles[0] is None else angles[0]
    angles[-1] = 360.0 if angles[-1] is None else angles[-1]
    index = 1
    while index < len(angles):
        if angles[index] is None:
            end = next(j for j in range(index, len(angles)) if angles[j] is not None)
            low, high = angles[index - 1] or 0.0, angles[end] or 0.0
            for step in range(index, end):
                angles[step] = low + (high - low) * (step - index + 1) / (end - index + 1)
            index = end
        index += 1
    ordered: list[tuple[float, Rgba]] = []
    floor = -math.inf
    for (color, _), angle in zip(raw, angles, strict=True):
        floor = max(floor, angle or 0.0)
        ordered.append((floor, color))
    return ordered


def color_at(conic: Conic, angle: float) -> Rgba:
    """The gradient's colour ``angle`` degrees round from its start, in premultiplied alpha."""
    stops = conic.stops
    if angle <= stops[0][0]:
        return stops[0][1]
    for (a0, c0), (a1, c1) in pairwise(stops):
        if a0 <= angle <= a1:
            return c1 if a1 <= a0 else mix_colors(c0, c1, (angle - a0) / (a1 - a0))
    return stops[-1][1]


def conic_wedges(
    conic: Conic, *, width_px: float, height_px: float, radius_px: float = 0.0
) -> list[Wedge]:
    """Cut ``conic`` into wedges, each clipped to the (rounded) box."""
    window = rounded_box(width_px, height_px, radius_px)
    center = (conic.center[0] * width_px, conic.center[1] * height_px)
    reach = 2.0 * (width_px + height_px)
    boundaries = {0.0, 360.0}
    boundaries.update(a for a, _ in conic.stops if 0.0 <= a <= 360.0)
    boundaries.update(float(step) for step in range(0, 360, int(_STEP_DEGREES)))
    edges = sorted(boundaries)
    wedges: list[Wedge] = []
    for index, (a0, a1) in enumerate(pairwise(edges)):
        if a1 - a0 < 1e-6:
            continue
        lead = a0 - (_OVERLAP_DEGREES if index else 0.0)
        triangle = [
            center,
            _ray(center, conic.start_deg + lead, reach),
            _ray(center, conic.start_deg + a1, reach),
        ]
        polygon = clip_polygon(triangle, window)
        if len(polygon) >= 3:
            wedges.append(Wedge(tuple(polygon), color_at(conic, (a0 + a1) / 2)))
    return wedges


@dataclass(frozen=True)
class Radial:
    """A parsed radial gradient: centre as box fractions, circle or ellipse, stops as fractions."""

    center: tuple[float, float]
    circle: bool
    extent: str
    stops: tuple[tuple[float, Rgba], ...]


_RADIAL = re.compile(r"^\s*radial-gradient\s*\((.*)\)\s*$", re.IGNORECASE | re.DOTALL)
_EXTENTS = ("closest-side", "farthest-side", "closest-corner", "farthest-corner")
_FRACTION = re.compile(r"\s+(-?[\d.]+)%\s*$")


def parse_radial(value: str | None, *, width_px: float, height_px: float) -> Radial | None:
    """Parse one ``radial-gradient`` with percentage stops; ``None`` for anything else."""
    if not value:
        return None
    match = _RADIAL.match(value)
    if match is None or len(split_top_level(value)) > 1:
        return None
    parts = [part.strip() for part in split_top_level(match.group(1))]
    circle, extent, center = False, "farthest-corner", (0.5, 0.5)
    if parts and not _has_fraction_color(parts[0]):
        prelude = parts.pop(0).lower()
        circle = "circle" in prelude
        extent = next((word for word in _EXTENTS if word in prelude), extent)
        at = _AT.search(prelude)
        if at is not None:
            x, x_unit, y, y_unit = at.groups()
            center = (
                float(x) / 100 if x_unit == "%" else float(x) / width_px,
                float(y) / 100 if y_unit == "%" else float(y) / height_px,
            )
        remainder = _AT.sub("", prelude).replace("circle", "").replace("ellipse", "")
        if any(word in remainder for word in _EXTENTS):
            remainder = re.sub("|".join(_EXTENTS), "", remainder)
        if remainder.strip():
            return None
    raw: list[tuple[Rgba, float | None]] = []
    for part in parts:
        position = _FRACTION.search(part)
        color = parse_color(part[: position.start()] if position else part)
        if color is None or (position is None and re.search(r"\d(px|em|deg)\s*$", part)):
            return None
        raw.append((color, float(position.group(1)) / 100 if position else None))
    fractions = _resolve_angles([(c, None if a is None else a * 360.0) for c, a in raw])
    if fractions is None:
        return None
    if any(color.a < 1.0 for _, color in fractions):
        return None  # stacked bands would compound the alpha; only opaque stops are exact
    return Radial(center, circle, extent, tuple((a / 360.0, c) for a, c in fractions))


def _has_fraction_color(part: str) -> bool:
    return parse_color(_FRACTION.sub("", part)) is not None


def radial_bands(
    radial: Radial, *, width_px: float, height_px: float, radius_px: float = 0.0, bands: int = 48
) -> list[Wedge]:
    """Concentric ellipse bands, outermost first, each clipped to the (rounded) box.

    Painted in order, every band is the gradient's colour over its own ring, so the result matches
    the browser's centre, aspect ratio and stops without any native radial gradient.
    """
    cx, cy = radial.center[0] * width_px, radial.center[1] * height_px
    rx, ry = _radii(radial, cx, cy, width_px, height_px)
    window = rounded_box(width_px, height_px, radius_px)
    edges = sorted(
        {
            0.0,
            1.0,
            *(f for f, _ in radial.stops if 0.0 < f < 1.0),
            *(i / bands for i in range(1, bands)),
        }
    )
    stops = tuple((fraction * 360.0, color) for fraction, color in radial.stops)
    conic = Conic(0.0, (0.5, 0.5), stops)
    # Past the ending ellipse CSS keeps painting the last stop, so start from the whole box.
    facets: list[Wedge] = [Wedge(tuple(window), radial.stops[-1][1])]
    for inner, outer in reversed(list(pairwise(edges))):
        outline = [
            (
                cx + rx * outer * math.cos(math.radians(a)),
                cy + ry * outer * math.sin(math.radians(a)),
            )
            for a in range(0, 360, 5)
        ]
        polygon = clip_polygon(outline, window)
        if len(polygon) >= 3:
            facets.append(Wedge(tuple(polygon), color_at(conic, (inner + outer) / 2 * 360.0)))
    return facets


def _radii(
    radial: Radial, cx: float, cy: float, width: float, height: float
) -> tuple[float, float]:
    """The ellipse's (or circle's) radii for the gradient's extent keyword."""
    near_x, near_y = min(cx, width - cx), min(cy, height - cy)
    far_x, far_y = max(cx, width - cx), max(cy, height - cy)
    if radial.circle:
        side = {
            "closest-side": min(near_x, near_y),
            "farthest-side": max(far_x, far_y),
            "closest-corner": math.hypot(near_x, near_y),
            "farthest-corner": math.hypot(far_x, far_y),
        }[radial.extent]
        return side, side
    if radial.extent == "closest-side":
        return near_x, near_y
    if radial.extent == "farthest-side":
        return far_x, far_y
    scale = math.sqrt(2.0)
    if radial.extent == "closest-corner":
        return near_x * scale, near_y * scale
    return far_x * scale, far_y * scale


def _ray(origin: tuple[float, float], degrees: float, length: float) -> tuple[float, float]:
    """A point ``length`` from ``origin`` at a CSS angle (0 is up, clockwise)."""
    radians = math.radians(degrees)
    return origin[0] + length * math.sin(radians), origin[1] - length * math.cos(radians)


def rounded_box(width: float, height: float, radius: float) -> Polygon:
    """The box as a clockwise polygon, with each corner rounded by ``radius`` px."""
    r = min(max(radius, 0.0), width / 2, height / 2)
    if r <= 0:
        return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    points: Polygon = []
    corners = [
        ((width - r, r), -90.0),
        ((width - r, height - r), 0.0),
        ((r, height - r), 90.0),
        ((r, r), 180.0),
    ]
    for (cx, cy), start in corners:
        for step in range(_CORNER_SEGMENTS + 1):
            angle = math.radians(start + 90.0 * step / _CORNER_SEGMENTS)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def clip_polygon(subject: Polygon, window: Polygon) -> Polygon:
    """Sutherland-Hodgman: ``subject`` clipped to the convex clockwise ``window``."""
    output: Polygon = list(subject)
    for start, end in zip(window, window[1:] + window[:1], strict=True):
        if not output:
            break
        candidates: Polygon = output
        output = []
        previous = candidates[-1]
        for current in candidates:
            if _inside(current, start, end):
                if not _inside(previous, start, end):
                    output.append(_cross(previous, current, start, end))
                output.append(current)
            elif _inside(previous, start, end):
                output.append(_cross(previous, current, start, end))
            previous = current
    return output


type Point = tuple[float, float]


def _inside(point: Point, start: Point, end: Point) -> bool:
    """Whether ``point`` is on the inner side of the clockwise edge ``start`` -> ``end``."""
    along = (end[0] - start[0], end[1] - start[1])
    return along[0] * (point[1] - start[1]) - along[1] * (point[0] - start[0]) >= 0


def _cross(a: Point, b: Point, c: Point, d: Point) -> Point:
    """Where segment ``a-b`` meets the line ``c-d``."""
    a1, b1 = b[1] - a[1], a[0] - b[0]
    a2, b2 = d[1] - c[1], c[0] - d[0]
    determinant = a1 * b2 - a2 * b1
    if abs(determinant) < 1e-12:
        return b
    c1, c2 = a1 * a[0] + b1 * a[1], a2 * c[0] + b2 * c[1]
    return (b2 * c1 - b1 * c2) / determinant, (a1 * c2 - a2 * c1) / determinant
