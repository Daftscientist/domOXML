"""Blend modes over a gradient stay exact: a stop at every bend of the blended channels."""

from __future__ import annotations

import pytest

from domoxml.core.ir.blend import blend_colour, blended_shapes
from domoxml.core.ir.lowering import sample_gradient
from domoxml.core.ir.model import Box, GradientFill, GradientStop, Rgba, ShapeNode

_UNIT = 9525


def _backdrop(*stops: tuple[float, Rgba]) -> ShapeNode:
    return ShapeNode(
        box=Box(x=0, y=0, width=400 * _UNIT, height=200 * _UNIT),
        geom="rect",
        fill=GradientFill(
            angle_deg=90, stops=tuple(GradientStop(pos=pos, color=colour) for pos, colour in stops)
        ),
    )


@pytest.mark.parametrize("mode", ["darken", "lighten", "difference", "multiply", "screen"])
def test_the_blended_gradient_matches_the_blend_at_every_position(mode: str) -> None:
    backdrop = _backdrop((0, Rgba(r=250, g=30, b=200)), (1, Rgba(r=10, g=240, b=40)))
    source = Rgba(r=120, g=128, b=100)
    box = Box(x=0, y=0, width=400 * _UNIT, height=200 * _UNIT)

    shapes = blended_shapes(mode, box, source, [backdrop])

    assert shapes is not None
    patch = next(s for s in shapes if isinstance(s.fill, GradientFill))
    assert isinstance(patch.fill, GradientFill)
    for position in (0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0):
        expected = blend_colour(
            mode,
            source,
            sample_gradient(backdrop.fill.stops, position),  # type: ignore[union-attr]
        )
        got = sample_gradient(patch.fill.stops, position)
        assert expected is not None
        assert max(abs(got.r - expected.r), abs(got.g - expected.g), abs(got.b - expected.b)) <= 2


def test_a_bending_blend_adds_stops_where_a_channel_crosses_the_source() -> None:
    backdrop = _backdrop((0, Rgba(r=250, g=30, b=200)), (1, Rgba(r=10, g=240, b=40)))
    box = Box(x=0, y=0, width=400 * _UNIT, height=200 * _UNIT)

    darken = blended_shapes("darken", box, Rgba(r=120, g=128, b=100), [backdrop])
    multiply = blended_shapes("multiply", box, Rgba(r=120, g=128, b=100), [backdrop])

    assert darken is not None and multiply is not None
    stops = {
        mode: len(next(s.fill.stops for s in shapes if isinstance(s.fill, GradientFill)))
        for mode, shapes in (("darken", darken), ("multiply", multiply))
    }
    assert stops["multiply"] == 2 and stops["darken"] == 5  # three channels cross the source
