"""``mix-blend-mode`` over solid shapes, resolved to the colours it produces.

PowerPoint has no blend mode that reaches the content beneath a shape, but when everything the
element overlaps is an opaque solid rectangle the blend is a known colour per region. The element
becomes plain shapes: its own box in its own colour (the canvas it sits on blends as transparent,
as the browser does), with a patch in the blended colour wherever it crosses another shape.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from domoxml.core.ir.lowering import sample_gradient
from domoxml.core.ir.model import (
    Box,
    GradientFill,
    GradientStop,
    Node,
    Rgba,
    ShapeNode,
    SolidFill,
)

_CHANNEL: dict[str, Callable[[float, float], float]] = {
    "multiply": lambda s, b: s * b,
    "screen": lambda s, b: s + b - s * b,
    "darken": min,
    "lighten": max,
    "difference": lambda s, b: abs(s - b),
}


def blend_colour(mode: str, source: Rgba, backdrop: Rgba) -> Rgba | None:
    """The colour ``source`` makes over an opaque ``backdrop``, or ``None`` for an unknown mode."""
    channel = _CHANNEL.get(mode)
    if channel is None or source.a != 1.0 or backdrop.a != 1.0:
        return None

    def mix(s: int, b: int) -> int:
        return round(channel(s / 255, b / 255) * 255)

    return Rgba(
        r=mix(source.r, backdrop.r), g=mix(source.g, backdrop.g), b=mix(source.b, backdrop.b)
    )


def _overlap(a: Box, b: Box) -> Box | None:
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.x + a.width, b.x + b.width), min(a.y + a.height, b.y + b.height)
    if right <= left or bottom <= top:
        return None
    return Box(x=left, y=top, width=right - left, height=bottom - top)


def blended_shapes(
    mode: str,
    box: Box,
    source: Rgba,
    beneath: Sequence[Node],
) -> list[ShapeNode] | None:
    """The shapes that paint ``source`` blended over ``beneath``, or ``None`` if it can't be.

    ``beneath`` is everything already on the slide, in paint order. Anything that crosses ``box``
    must be an opaque, square, unrotated, solid shape with no text, outline or effects, or the
    result would not be what the browser shows.
    """
    if mode not in _CHANNEL or source.a != 1.0:
        return None
    shapes = [ShapeNode(box=box, geom="rect", fill=SolidFill(color=source))]
    for node in beneath:
        if not isinstance(node, ShapeNode):
            if getattr(node, "box", None) is not None and _overlap(box, node.box) is not None:  # type: ignore[attr-defined]
                return None
            continue
        crossing = _overlap(box, node.box)
        if crossing is None:
            continue
        if (
            node.geom != "rect"
            or node.custom_geom is not None
            or node.corner_radius_emu
            or node.transform is not None
            or node.opacity != 1.0
            or node.line is not None
            or node.side_lines is not None
            or node.effects
            or node.text is not None
        ):
            return None
        if node.fill is None:
            continue
        if isinstance(node.fill, GradientFill):
            patch = _blended_gradient(mode, source, node.fill, node.box, crossing)
            if patch is None:
                return None
            shapes.append(ShapeNode(box=crossing, geom="rect", fill=patch))
            continue
        if not isinstance(node.fill, SolidFill) or node.fill.color.a != 1.0:
            return None
        colour = blend_colour(mode, source, node.fill.color)
        if colour is None:
            return None
        shapes.append(ShapeNode(box=crossing, geom="rect", fill=SolidFill(color=colour)))
    return shapes


# Over a gradient only these blends stay a gradient: they are affine in the backdrop colour, so
# blending every stop blends every point between them. The others bend at the point the two swap.
_AFFINE = frozenset({"multiply", "screen"})


def _blended_gradient(
    mode: str, source: Rgba, gradient: GradientFill, backdrop: Box, crossing: Box
) -> GradientFill | None:
    """The part of a linear gradient under ``crossing``, with ``source`` blended into every stop.

    The patch keeps the gradient's angle; its stops are the original's between the two positions
    where the patch's corners project onto the gradient line, plus the colours at those ends.
    """
    if (
        mode not in _AFFINE
        or gradient.radial
        or any(stop.color.a != 1.0 for stop in gradient.stops)
        or backdrop.width <= 0
        or backdrop.height <= 0
    ):
        return None
    angle = math.radians(gradient.angle_deg)
    dx, dy = math.sin(angle), -math.cos(angle)
    length = abs(backdrop.width * dx) + abs(backdrop.height * dy)
    if length <= 0:
        return None
    centre = (backdrop.x + backdrop.width / 2, backdrop.y + backdrop.height / 2)

    def position(x: float, y: float) -> float:
        return 0.5 + ((x - centre[0]) * dx + (y - centre[1]) * dy) / length

    corners = [
        position(x, y)
        for x in (crossing.x, crossing.x + crossing.width)
        for y in (crossing.y, crossing.y + crossing.height)
    ]
    start, end = min(corners), max(corners)
    if end - start <= 1e-9:
        return None
    stops = gradient.stops
    # Interior stops keep their own colours (so a hard transition stays hard); only the two new
    # ends are sampled just inside the patch, so a stop sitting on an end gives its inner side.
    inside = 1e-9
    points = [
        (start, sample_gradient(stops, start + inside)),
        *((stop.pos, stop.color) for stop in stops if start < stop.pos < end),
        (end, sample_gradient(stops, end - inside)),
    ]
    blended: list[GradientStop] = []
    for at, colour in points:
        mixed = blend_colour(mode, source, colour)
        if mixed is None:
            return None
        blended.append(GradientStop(pos=(at - start) / (end - start), color=mixed))
    return gradient.model_copy(update={"stops": tuple(blended)})
