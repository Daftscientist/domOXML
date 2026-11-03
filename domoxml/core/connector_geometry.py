"""Where a connector's ends are, given the box PowerPoint stores it in.

A ``p:cxnSp`` draws its preset from the top left of its box to the bottom right, after the box's
flips and then its rotation about the centre. The IR keeps the two ends and whether an elbow
leaves its start horizontally or vertically; this converts both ways.
"""

from __future__ import annotations

import math

from domoxml.core.ir.model import Point

_FULL_TURN = 21_600_000  # 60000ths of a degree


def connector_ends(
    x: int, y: int, cx: int, cy: int, rotation: int, flip_h: bool, flip_v: bool
) -> tuple[Point, Point]:
    """The start and end of a connector stored as ``off``/``ext`` with ``rot`` and flips."""
    start, end = (0.0, 0.0), (float(cx), float(cy))
    if flip_h:
        start, end = (cx - start[0], start[1]), (cx - end[0], end[1])
    if flip_v:
        start, end = (start[0], cy - start[1]), (end[0], cy - end[1])
    angle = math.radians((rotation % _FULL_TURN) / 60_000)
    sin, cos = math.sin(angle), math.cos(angle)
    centre = (cx / 2, cy / 2)

    def place(point: tuple[float, float]) -> Point:
        dx, dy = point[0] - centre[0], point[1] - centre[1]
        return Point(
            x=round(x + centre[0] + dx * cos - dy * sin),
            y=round(y + centre[1] + dx * sin + dy * cos),
        )

    return place(start), place(end)


def connector_box(
    start: Point, end: Point, vertical_first: bool
) -> tuple[int, int, int, int, int, bool, bool]:
    """``(x, y, cx, cy, rot, flipH, flipV)`` that store a connector from ``start`` to ``end``.

    A connector whose elbow leaves vertically is the preset turned a quarter, so its box is
    the transposed one about the same centre.
    """
    dx, dy = abs(end.x - start.x), abs(end.y - start.y)
    centre_x, centre_y = (start.x + end.x) / 2, (start.y + end.y) / 2
    rotation = 5_400_000 if vertical_first else 0
    width, height = (dy, dx) if vertical_first else (dx, dy)
    width, height = max(1, width), max(1, height)
    x, y = round(centre_x - width / 2), round(centre_y - height / 2)
    best: tuple[int, bool, bool] | None = None
    for flip_h in (False, True):
        for flip_v in (False, True):
            placed = connector_ends(x, y, width, height, rotation, flip_h, flip_v)
            error = (
                abs(placed[0].x - start.x)
                + abs(placed[0].y - start.y)
                + abs(placed[1].x - end.x)
                + abs(placed[1].y - end.y)
            )
            if best is None or error < best[0]:
                best = (error, flip_h, flip_v)
    assert best is not None
    return x, y, width, height, rotation, best[1], best[2]
