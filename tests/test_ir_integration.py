"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import pytest

from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import SlideIR
from domoxml.core.render import BrowserSession, compose_page
from domoxml.core.units import pixels
from domoxml.types import SlideSize, Theme

pytestmark = pytest.mark.integration


async def _render_and_extract(slide_html: str) -> SlideIR:
    width, height = pixels(SlideSize.WIDE_16_9)
    page = compose_page(slide_html, css=None, theme=Theme(), width_px=width, height_px=height)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=width, height=height)
    return extract_slide(rendered)


async def test_extracts_fill_and_text_from_a_real_render() -> None:
    ir = await _render_and_extract(
        "<div style='width:300px;height:120px;background:rgb(79,70,229);"
        "border-radius:16px;color:#fff;font-size:32px;font-weight:700'>Driftwood</div>"
    )

    assert ir.width > 0 and ir.height > 0
    assert ir.shapes, "expected at least one shape"

    filled = [s for s in ir.shapes if s.fill is not None and s.fill.hex == "4F46E5"]
    assert filled, "the indigo div should map to a filled shape"
    assert any(s.text is not None and "Driftwood" in s.text.text and s.text.bold for s in ir.shapes)
