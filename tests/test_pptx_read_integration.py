"""PPTX -> canvas IR -> HTML/CSS browser-rendered round trip."""

from __future__ import annotations

import pytest

from domoxml import Presentation, Slide, pptx_to_html
from domoxml.core.fidelity import compare
from domoxml.core.ir.model import (
    Box,
    GroupNode,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    Transform,
)
from domoxml.slides.pptx import build_pptx
from domoxml.types import OutputFormat

pytestmark = pytest.mark.integration


def test_generated_pptx_round_trips_to_browser_renderable_html() -> None:
    deck = Presentation()
    deck.add(
        Slide(
            html=(
                "<div style='position:absolute;left:96px;top:96px;width:320px;height:120px;"
                "background:rgb(79,70,229);border-radius:12px;color:white;font-size:32px'>"
                "Coffee <span style='font-style:italic'>calm</span></div>"
            )
        )
    )
    rendered = deck.render({OutputFormat.PNG, OutputFormat.PPTX})
    assert rendered.pptx is not None

    html = pptx_to_html(rendered.pptx)
    assert len(html.slides) == 1
    round_trip = Presentation(css=html.css).add(Slide(html=html.slides[0].html))
    rerendered = round_trip.render({OutputFormat.PNG})

    report = compare(rendered.pngs[0], rerendered.pngs[0])
    assert report.similarity >= 0.95


def test_transformed_nested_group_flattens_to_visible_html_not_a_failed_node() -> None:
    unit = 9525

    def block(x: int, y: int, colour: tuple[int, int, int]) -> ShapeNode:
        return ShapeNode(
            box=Box(x=x * unit, y=y * unit, width=100 * unit, height=100 * unit),
            geom="rect",
            fill=SolidFill(color=Rgba(r=colour[0], g=colour[1], b=colour[2])),
        )

    inner = GroupNode(
        box=Box(x=100 * unit, y=100 * unit, width=200 * unit, height=100 * unit),
        child_box=Box(x=100 * unit, y=100 * unit, width=200 * unit, height=100 * unit),
        children=(block(100, 100, (200, 0, 0)), block(200, 100, (0, 0, 200))),
        transform=Transform(rotation_deg=20),
    )
    outer = GroupNode(
        box=Box(x=50 * unit, y=50 * unit, width=500 * unit, height=400 * unit),
        child_box=Box(x=50 * unit, y=50 * unit, width=500 * unit, height=400 * unit),
        children=(inner, block(300, 300, (0, 150, 0))),
        transform=Transform(rotation_deg=10),
    )
    slide = SlideIR(width=1280 * unit, height=720 * unit, contents=(outer,))

    result = pptx_to_html(build_pptx([slide], faces=[]))

    [item] = result.coverage.items
    assert item.representation.value == "decomposed" and item.output_count == 3
    html = result.slides[0].html
    assert "rotate(10deg)" in html and "rotate(20deg)" in html
    assert "domoxml-preserved" not in html
