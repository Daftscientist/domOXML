"""A slide background gradient is written with sampled stops, exact in real PowerPoint."""

from __future__ import annotations

import io
import re
import zipfile

from domoxml.core.ir.model import (
    GradientFill,
    GradientStop,
    Rgba,
    SlideBackground,
    SlideIR,
)
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result


def _deck(*stops: tuple[float, Rgba]) -> bytes:
    fill = GradientFill(
        angle_deg=90, stops=tuple(GradientStop(pos=pos, color=colour) for pos, colour in stops)
    )
    slide = SlideIR(width=12_192_000, height=6_858_000, background=SlideBackground(fill=fill))
    return build_pptx([slide], faces=[])


def _stops(deck: bytes) -> list[tuple[int, str]]:
    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    background = xml[xml.index("<p:bg>") : xml.index("</p:bg>")]
    return [
        (int(p), c) for p, c in re.findall(r'<a:gs pos="(\d+)"><a:srgbClr val="(\w+)"', background)
    ]


def test_a_two_stop_background_is_written_with_sampled_stops_between_its_ends() -> None:
    stops = _stops(_deck((0, Rgba(r=250, g=30, b=200)), (1, Rgba(r=10, g=240, b=40))))

    assert len(stops) == 17 and stops[0] == (0, "FA1EC8") and stops[-1] == (100000, "0AF028")
    assert stops[8] == (50000, "828778")  # the exact midpoint, which PowerPoint no longer picks


def test_a_hard_transition_keeps_both_of_its_colours_and_the_gradient_reads_back() -> None:
    red, yellow = Rgba(r=255, g=0, b=0), Rgba(r=255, g=255, b=0)
    deck = _deck((0, red), (0.5, red), (0.5, yellow), (1, yellow))

    stops = _stops(deck)
    back = read_pptx_result(deck).slides[0].background

    assert (50000, "FF0000") in stops and (50000, "FFFF00") in stops
    assert stops.index((50000, "FF0000")) + 1 == stops.index((50000, "FFFF00"))
    assert back is not None and isinstance(back.fill, GradientFill)


def test_the_sampled_stops_collapse_back_to_the_authored_ones_on_reading() -> None:
    deck = _deck((0, Rgba(r=250, g=30, b=200)), (1, Rgba(r=10, g=240, b=40)))

    back = read_pptx_result(deck).slides[0].background

    assert back is not None and isinstance(back.fill, GradientFill)
    assert [(s.pos, s.color.hex) for s in back.fill.stops] == [(0, "FA1EC8"), (1, "0AF028")]


def test_a_gradient_with_a_real_bend_keeps_the_stop_at_the_bend() -> None:
    deck = _deck(
        (0, Rgba(r=255, g=0, b=0)),
        (0.25, Rgba(r=0, g=0, b=255)),
        (1, Rgba(r=0, g=255, b=0)),
    )

    back = read_pptx_result(deck).slides[0].background

    assert back is not None and isinstance(back.fill, GradientFill)
    assert [round(s.pos, 2) for s in back.fill.stops] == [0, 0.25, 1]


def test_authored_stops_off_the_sampling_grid_and_inside_the_ends_survive() -> None:
    red, blue = Rgba(r=255, g=0, b=0), Rgba(r=0, g=0, b=255)
    middle = Rgba(r=255 - round(255 * 0.3), g=0, b=round(255 * 0.3))
    deck = _deck((0.25, red), (0.3, middle), (0.75, blue))

    stops = _stops(deck)
    back = read_pptx_result(deck).slides[0].background

    assert stops[0][0] == 25000 and stops[-1][0] == 75000  # nothing sampled past the ends
    assert back is not None and isinstance(back.fill, GradientFill)
    assert [round(s.pos, 2) for s in back.fill.stops] == [0.25, 0.3, 0.75]


def test_a_radial_background_is_sampled_and_collapses_back_like_a_linear_one() -> None:
    fill = GradientFill(
        radial=True,
        stops=(
            GradientStop(pos=0, color=Rgba(r=250, g=30, b=200)),
            GradientStop(pos=1, color=Rgba(r=10, g=240, b=40)),
        ),
    )
    deck = build_pptx(
        [SlideIR(width=12_192_000, height=6_858_000, background=SlideBackground(fill=fill))],
        faces=[],
    )

    back = read_pptx_result(deck).slides[0].background

    assert len(_stops(deck)) == 17
    assert back is not None and isinstance(back.fill, GradientFill) and back.fill.radial
    assert [s.color.hex for s in back.fill.stops] == ["FA1EC8", "0AF028"]
