"""Shared CSS-to-DrawingML gradient projection."""

from __future__ import annotations

import math

from domoxml.core.ir.model import Box, GradientFill, GradientStop, Rgba

# OOXML writes gradient positions in 1/100000ths, and anything narrower than this many of them is a
# step rather than a ramp.
_POSITION_UNITS = 100_000
_MIN_RAMP_UNITS = 2


def _premultiplied_channel(
    start_channel: int,
    end_channel: int,
    *,
    start_alpha: float,
    end_alpha: float,
    amount: float,
    alpha: float,
) -> int:
    if alpha <= 0.0:
        return round(start_channel + (end_channel - start_channel) * amount)
    premultiplied = start_channel * start_alpha * (1.0 - amount) + end_channel * end_alpha * amount
    return round(premultiplied / alpha)


def _subdivide_srgb_stops(gradient: GradientFill) -> tuple[GradientStop, ...]:
    """Subdivide CSS sRGB stops so PowerPoint's interpolation tracks browser paint."""
    expanded: list[GradientStop] = []
    for index, (start, end) in enumerate(zip(gradient.stops, gradient.stops[1:], strict=False)):
        # Interpolation only differs between engines across a ramp. A flat run (same colour at both
        # ends) and a hard edge (a step one OOXML position unit wide) have nothing to subdivide, so
        # repeating patterns made of them do not multiply their stop count.
        flat = start.color == end.color
        hard_edge = (end.pos - start.pos) * _POSITION_UNITS < _MIN_RAMP_UNITS
        subdivisions = 1 if flat or hard_edge else 8
        for step in range(subdivisions + 1):
            if index > 0 and step == 0:
                continue
            amount = step / subdivisions
            alpha = start.color.a + (end.color.a - start.color.a) * amount

            expanded.append(
                GradientStop(
                    pos=start.pos + (end.pos - start.pos) * amount,
                    color=Rgba(
                        r=_premultiplied_channel(
                            start.color.r,
                            end.color.r,
                            start_alpha=start.color.a,
                            end_alpha=end.color.a,
                            amount=amount,
                            alpha=alpha,
                        ),
                        g=_premultiplied_channel(
                            start.color.g,
                            end.color.g,
                            start_alpha=start.color.a,
                            end_alpha=end.color.a,
                            amount=amount,
                            alpha=alpha,
                        ),
                        b=_premultiplied_channel(
                            start.color.b,
                            end.color.b,
                            start_alpha=start.color.a,
                            end_alpha=end.color.a,
                            amount=amount,
                            alpha=alpha,
                        ),
                        a=alpha,
                    ),
                )
            )
    return tuple(expanded)


def drawingml_gradient_angle(gradient: GradientFill, *, box: Box | None) -> int:
    """Return the serialized DrawingML linear-gradient angle in 1/60000 degrees."""
    drawingml_angle = (gradient.angle_deg + 270.0) % 360.0
    if box is not None and box.width > 0 and box.height > 0:
        angle = math.radians(drawingml_angle)
        drawingml_angle = (
            math.degrees(
                math.atan2(
                    math.sin(angle) * box.height,
                    math.cos(angle) * box.width,
                )
            )
            % 360.0
        )
    return round(drawingml_angle * 60_000)


def drawingml_gradient_projection(
    gradient: GradientFill,
    *,
    box: Box | None,
) -> GradientFill:
    """Return the gradient a DrawingML write/read cycle exposes to the IR reader."""
    source_stops = _subdivide_srgb_stops(gradient) if box is not None else gradient.stops
    stops = tuple(
        stop.model_copy(
            update={
                "pos": round(stop.pos * 100_000) / 100_000,
                "color": stop.color.model_copy(
                    update={"a": round(stop.color.a * 100_000) / 100_000}
                ),
            }
        )
        for stop in source_stops
    )
    if gradient.radial:
        return GradientFill(stops=stops, angle_deg=180.0, radial=True)

    serialized_angle = drawingml_gradient_angle(gradient, box=box)
    css_angle = ((serialized_angle / 60_000) - 270.0) % 360.0
    return GradientFill(stops=stops, angle_deg=css_angle, radial=False)
