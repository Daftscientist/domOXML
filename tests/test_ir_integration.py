"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import pytest

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import SlideIR, SolidFill
from domoxml.core.render import BrowserSession, compose_page
from domoxml.core.units import pixels
from domoxml.types import SlideSize, Theme

pytestmark = pytest.mark.integration


async def _render_and_extract(slide_html: str) -> SlideIR:
    width, height = pixels(SlideSize.WIDE_16_9)
    page = compose_page(slide_html, css=None, theme=Theme(), width_px=width, height_px=height)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=width, height=height)
    return extract_slide(rendered).slide


async def test_extracts_fill_and_text_from_a_real_render() -> None:
    ir = await _render_and_extract(
        "<div style='width:300px;height:120px;background:rgb(79,70,229);"
        "border-radius:16px;color:#fff;font-size:32px;font-weight:700'>Driftwood</div>"
    )

    assert ir.width > 0 and ir.height > 0
    assert ir.shapes, "expected at least one shape"

    filled = [
        s for s in ir.shapes if isinstance(s.fill, SolidFill) and s.fill.color.hex == "4F46E5"
    ]
    assert filled, "the indigo div should map to a filled shape"
    assert any(
        s.text is not None
        and any(
            "Driftwood" in run.text and run.bold
            for paragraph in s.text.paragraphs
            for run in paragraph.runs
        )
        for s in ir.shapes
    )


async def test_extracts_nested_inline_text_as_ordered_editable_runs() -> None:
    ir = await _render_and_extract(
        "<h1 style='font-size:32px'>Coffee that tastes like "
        "<span style='font-style:italic;color:rgb(79,70,229)'>calm</span>.</h1>"
    )

    text_shapes = [shape for shape in ir.shapes if shape.text is not None]
    assert len(text_shapes) == 1
    body = text_shapes[0].text
    assert body is not None
    runs = body.paragraphs[0].runs
    assert "".join(run.text for run in runs) == "Coffee that tastes like calm."
    assert [run.text for run in runs] == ["Coffee that tastes like ", "calm", "."]
    assert runs[1].italic is True
    assert runs[1].color.hex == "4F46E5"
