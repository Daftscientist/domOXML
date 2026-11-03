"""``mix-blend-mode`` over solid shapes, resolved to the colours it produces.

PowerPoint has no blend mode that reaches the content beneath a shape, but when everything the
element overlaps is an opaque solid rectangle the blend is a known colour per region. The element
becomes plain shapes: its own box in its own colour (the canvas it sits on blends as transparent,
as the browser does), with a patch in the blended colour wherever it crosses another shape.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from domoxml.core.ir.model import Box, Node, Rgba, ShapeNode, SolidFill

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
        if not isinstance(node.fill, SolidFill) or node.fill.color.a != 1.0:
            return None
        colour = blend_colour(mode, source, node.fill.color)
        if colour is None:
            return None
        shapes.append(ShapeNode(box=crossing, geom="rect", fill=SolidFill(color=colour)))
    return shapes
