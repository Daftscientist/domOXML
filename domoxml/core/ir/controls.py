"""Browser-drawn form controls as plain shapes.

``<progress>``, ``<meter>``, checkboxes, radio buttons and range sliders have no DOM children to
read: the browser paints them from its own theme. Their state (value, range, checked) is what
defines them, so this redraws each from that state with the colours Chrome uses by default (an
``accent-color`` replaces the blue), as ordinary rounded shapes that stay editable.
"""

from __future__ import annotations

import json

from domoxml.core.ir.model import (
    Box,
    ClosePath,
    CustomGeometry,
    Line,
    LineTo,
    MoveTo,
    Point,
    Rgba,
    ShapeNode,
    SolidFill,
)
from domoxml.core.units import px_to_emu

ACCENT = Rgba(r=0, g=117, b=255)
TRACK = Rgba(r=239, g=239, b=239)
TRACK_EDGE = Rgba(r=203, g=203, b=203)
BORDER = Rgba(r=118, g=118, b=118)
WHITE = Rgba(r=255, g=255, b=255)
RANGE_EDGE = Rgba(r=178, g=178, b=178)
METER_OPTIMUM = Rgba(r=16, g=124, b=16)
METER_SUBOPTIMAL = Rgba(r=255, g=185, b=0)
METER_BAD = Rgba(r=216, g=59, b=1)


def control_shapes(
    state_json: str, x: float, y: float, width: float, height: float, accent: Rgba | None
) -> list[ShapeNode] | None:
    """The shapes that draw a control of the given box, or ``None`` if it is not one we draw."""
    try:
        state = json.loads(state_json)
    except ValueError:
        return None
    tag, kind = state.get("tag"), state.get("type")
    colour = accent or ACCENT
    if state.get("indeterminate"):
        return None  # an animated bar has no value to draw
    rtl = bool(state.get("rtl"))
    if tag == "progress":
        return _bar(x, y, width, height, _fraction(state), colour, rtl=rtl)
    if tag == "meter":
        return _bar(x, y, width, height, _fraction(state), _meter_colour(state), rtl=rtl)
    if tag == "input" and kind == "checkbox":
        return _checkbox(x, y, width, height, bool(state.get("checked")), colour)
    if tag == "input" and kind == "radio":
        return _radio(x, y, width, height, bool(state.get("checked")), colour)
    if tag == "input" and kind == "range":
        return _range(x, y, width, height, _fraction(state, default_max=100.0), colour, rtl=rtl)
    return None


def _fraction(state: dict[str, float], default_max: float = 1.0) -> float:
    low = 0.0 if state.get("min") is None else float(state["min"])
    high = default_max if state.get("max") is None else float(state["max"])
    value = 0.0 if state.get("value") is None else float(state["value"])
    if high <= low:
        return 0.0
    return min(1.0, max(0.0, (value - low) / (high - low)))


def _meter_colour(state: dict[str, float]) -> Rgba:
    """Green in the optimum region, amber next to it, red-orange two regions away."""
    low = 0.0 if state.get("min") is None else float(state["min"])
    high = 1.0 if state.get("max") is None else float(state["max"])
    lo = low if state.get("low") is None else float(state["low"])
    hi = high if state.get("high") is None else float(state["high"])
    optimum = (low + high) / 2 if state.get("optimum") is None else float(state["optimum"])
    value = 0.0 if state.get("value") is None else float(state["value"])

    def region(v: float) -> int:
        return 0 if v < lo else 2 if v > hi else 1

    distance = abs(region(value) - region(optimum))
    return METER_OPTIMUM if distance == 0 else METER_SUBOPTIMAL if distance == 1 else METER_BAD


def _box(x: float, y: float, width: float, height: float) -> Box:
    return Box(x=px_to_emu(x), y=px_to_emu(y), width=px_to_emu(width), height=px_to_emu(height))


def _line(colour: Rgba, width_px: float = 1.0) -> Line:
    return Line(color=colour, width_emu=px_to_emu(width_px))


def _pill(
    x: float, y: float, width: float, height: float, fill: Rgba, line: Rgba | None
) -> ShapeNode:
    box = _box(x, y, width, height)
    return ShapeNode(
        box=box,
        geom="roundRect",
        corner_radius_emu=min(box.width, box.height) // 2,
        fill=SolidFill(color=fill),
        line=_line(line) if line else None,
    )


def _bar(
    x: float,
    y: float,
    width: float,
    height: float,
    fraction: float,
    colour: Rgba,
    *,
    rtl: bool = False,
) -> list[ShapeNode]:
    """A pill track with a pill bar; Chrome draws both half the element's height, centred."""
    thickness = height / 2
    top = y + (height - thickness) / 2
    shapes = [_pill(x, top, width, thickness, TRACK, TRACK_EDGE)]
    if fraction > 0:
        length = max(thickness, width * fraction)
        start = x + width - length if rtl else x
        shapes.append(_pill(start, top, length, thickness, colour, None))
    return shapes


def _checkbox(
    x: float, y: float, width: float, height: float, checked: bool, accent: Rgba
) -> list[ShapeNode]:
    box = _box(x, y, width, height)
    shapes = [
        ShapeNode(
            box=box,
            geom="roundRect",
            corner_radius_emu=px_to_emu(min(width, height) * 0.15),
            fill=SolidFill(color=accent if checked else WHITE),
            line=None if checked else _line(BORDER),
        )
    ]
    if checked:
        points = [(0.22, 0.52), (0.42, 0.72), (0.78, 0.30)]
        path = (
            MoveTo(to=Point(x=round(points[0][0] * box.width), y=round(points[0][1] * box.height))),
            *(
                LineTo(to=Point(x=round(px * box.width), y=round(py * box.height)))
                for px, py in points[1:]
            ),
        )
        shapes.append(
            ShapeNode(
                box=box,
                custom_geom=CustomGeometry(width_emu=box.width, height_emu=box.height, path=path),
                line=_line(WHITE, max(1.5, min(width, height) * 0.12)),
            )
        )
    return shapes


def _radio(
    x: float, y: float, width: float, height: float, checked: bool, accent: Rgba
) -> list[ShapeNode]:
    shapes = [
        ShapeNode(
            box=_box(x, y, width, height),
            geom="ellipse",
            fill=SolidFill(color=WHITE),
            line=_line(accent if checked else BORDER),
        )
    ]
    if checked:
        inset = min(width, height) * 0.25
        shapes.append(
            ShapeNode(
                box=_box(x + inset, y + inset, width - 2 * inset, height - 2 * inset),
                geom="ellipse",
                fill=SolidFill(color=accent),
            )
        )
    return shapes


def _range(
    x: float,
    y: float,
    width: float,
    height: float,
    fraction: float,
    accent: Rgba,
    *,
    rtl: bool = False,
) -> list[ShapeNode]:
    thickness, thumb = 6.0, min(15.0, height)
    top = y + (height - thickness) / 2
    travel = max(0.0, width - thumb)
    centre = x + thumb / 2 + (1.0 - fraction) * travel if rtl else x + thumb / 2 + fraction * travel
    shapes = [_pill(x, top, width, thickness, TRACK, RANGE_EDGE)]
    if rtl and centre < x + width:
        shapes.append(_pill(centre, top, x + width - centre, thickness, accent, None))
    elif not rtl and centre > x:
        shapes.append(_pill(x, top, centre - x, thickness, accent, None))
    shapes.append(
        ShapeNode(
            box=_box(centre - thumb / 2, y + (height - thumb) / 2, thumb, thumb),
            geom="ellipse",
            fill=SolidFill(color=accent),
        )
    )
    return shapes


__all__ = ["ClosePath", "control_shapes"]


ARROW = Rgba(r=16, g=16, b=16)


def select_arrow(x: float, y: float, width: float, height: float) -> ShapeNode | None:
    """The down chevron Chrome paints at the right of a drop-down ``<select>``."""
    if width < 40 or height < 14:
        return None
    arrow_w, arrow_h = 10.0, 6.0
    box = _box(x + width - 8.0 - arrow_w, y + (height - arrow_h) / 2, arrow_w, arrow_h)
    path = (
        MoveTo(to=Point(x=0, y=0)),
        LineTo(to=Point(x=box.width // 2, y=box.height)),
        LineTo(to=Point(x=box.width, y=0)),
    )
    return ShapeNode(
        box=box,
        custom_geom=CustomGeometry(width_emu=box.width, height_emu=box.height, path=path),
        line=_line(ARROW, 1.5),
    )


def disclosure_marker(
    opened: bool, x: float, y: float, font_px: float, line_px: float, colour: Rgba
) -> ShapeNode:
    """The triangle Chrome draws before a ``<summary>``: down when open, right when closed.

    ``x`` and ``y`` are the summary's top left; both triangles are equilateral with a side of
    0.64em and centred on the first line.
    """
    side, altitude = 0.64 * font_px, 0.55 * font_px
    width, height = (side, altitude) if opened else (altitude, side)
    box = _box(x + 0.005 * font_px, y + line_px / 2 - height / 2, width, height)
    corners = (
        [(0, 0), (box.width, 0), (box.width // 2, box.height)]
        if opened
        else [(0, 0), (box.width, box.height // 2), (0, box.height)]
    )
    path = (
        MoveTo(to=Point(x=corners[0][0], y=corners[0][1])),
        *(LineTo(to=Point(x=px, y=py)) for px, py in corners[1:]),
        ClosePath(),
    )
    return ShapeNode(
        box=box,
        custom_geom=CustomGeometry(width_emu=box.width, height_emu=box.height, path=path),
        fill=SolidFill(color=colour),
    )
