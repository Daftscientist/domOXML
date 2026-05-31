"""PPTX -> canvas IR -> HTML/CSS browser-rendered round trip."""

from __future__ import annotations

import pytest

from domoxml import Presentation, Slide, pptx_to_html
from domoxml.core.fidelity import compare
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
