"""Connector ends, routing and their PPTX/HTML round trip."""

from __future__ import annotations

import pytest

from domoxml.core.connector_geometry import connector_box, connector_ends
from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import Connector, Line, Point, Rgba, SlideIR
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_LINE = Line(color=Rgba(r=0, g=0, b=0), width_emu=12_700)


@pytest.mark.parametrize("flip_h", [False, True])
@pytest.mark.parametrize("flip_v", [False, True])
def test_flips_swap_the_corners_the_connector_runs_between(flip_h: bool, flip_v: bool) -> None:
    start, end = connector_ends(100, 200, 400, 300, 0, flip_h, flip_v)

    assert (start.x, end.x) == ((500, 100) if flip_h else (100, 500))
    assert (start.y, end.y) == ((500, 200) if flip_v else (200, 500))


def test_a_quarter_turn_runs_from_the_top_right_corner_to_the_bottom_left() -> None:
    # A 400x100 box turned a quarter: the ends move to the corners of the 100x400 box it fills.
    start, end = connector_ends(0, 0, 400, 100, 5_400_000, False, False)

    assert (start, end) == (Point(x=250, y=-150), Point(x=150, y=250))


@pytest.mark.parametrize("vertical_first", [False, True])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (Point(x=100, y=100), Point(x=900, y=500)),
        (Point(x=900, y=100), Point(x=100, y=500)),
        (Point(x=100, y=500), Point(x=900, y=100)),
        (Point(x=900, y=500), Point(x=100, y=100)),
    ],
)
def test_the_box_stored_for_any_pair_of_ends_places_them_exactly(
    start: Point, end: Point, vertical_first: bool
) -> None:
    x, y, cx, cy, rotation, flip_h, flip_v = connector_box(start, end, vertical_first)

    assert connector_ends(x, y, cx, cy, rotation, flip_h, flip_v) == (start, end)


@pytest.mark.parametrize("kind", ["straight", "bent", "curved"])
@pytest.mark.parametrize("vertical_first", [False, True])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (Point(x=1_000_000, y=1_000_000), Point(x=4_000_000, y=2_500_000)),
        (Point(x=4_000_000, y=1_000_000), Point(x=1_000_000, y=2_500_000)),
        (Point(x=4_000_000, y=2_500_000), Point(x=1_000_000, y=1_000_000)),
    ],
)
def test_a_connector_survives_pptx_whatever_its_direction_and_routing(
    kind: str, vertical_first: bool, start: Point, end: Point
) -> None:
    connector = Connector(
        start=start,
        end=end,
        kind=kind,  # type: ignore[arg-type]
        vertical_first=vertical_first and kind != "straight",
        line=_LINE,
    )

    source = build_pptx(
        [SlideIR(width=12_192_000, height=6_858_000, contents=(connector,))], faces=[]
    )
    [read] = read_pptx_result(source).slides[0].contents

    assert isinstance(read, Connector)
    assert (read.start, read.end) == (start, end)
    assert read.kind == kind and read.vertical_first == connector.vertical_first


def test_an_elbow_is_three_segments_and_follows_its_leaving_direction_in_html() -> None:
    def path(vertical_first: bool) -> str:
        connector = Connector(
            start=Point(x=0, y=0),
            end=Point(x=1_905_000, y=952_500),
            kind="bent",
            vertical_first=vertical_first,
            line=_LINE,
        )
        html = (
            serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(connector,))])
            .slides[0]
            .html
        )
        return html.split(' d="')[1].split('"')[0]

    horizontal, vertical = path(False), path(True)

    assert horizontal.count("L") == 3 and vertical.count("L") == 3
    assert horizontal != vertical


@pytest.mark.parametrize("kind", ["bent", "curved"])
def test_the_elbow_position_survives_pptx_and_moves_the_html_turn(kind: str) -> None:
    connector = Connector(
        start=Point(x=0, y=0),
        end=Point(x=1_905_000, y=952_500),
        kind=kind,  # type: ignore[arg-type]
        elbow=0.25,
        line=_LINE,
    )
    slide = SlideIR(width=12_192_000, height=6_858_000, contents=(connector,))

    [read] = read_pptx_result(build_pptx([slide], faces=[])).slides[0].contents

    assert isinstance(read, Connector) and read.elbow == 0.25
    centred = connector.model_copy(update={"elbow": 0.5})
    assert (
        serialize_canvas([slide]).slides[0].html.split(' d="')[1].split('"')[0]
        != serialize_canvas([slide.model_copy(update={"contents": (centred,)})])
        .slides[0]
        .html.split(' d="')[1]
        .split('"')[0]
    )
