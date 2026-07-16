"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import pytest

from domoxml.core.ir import ExtractResult, extract_slide
from domoxml.core.ir.model import AutoNumberBullet, SlideIR, SolidFill
from domoxml.core.render import BrowserSession, compose_page
from domoxml.core.units import pixels
from domoxml.types import Representation, SlideSize, Theme

pytestmark = pytest.mark.integration


async def _render_and_extract(slide_html: str) -> SlideIR:
    width, height = pixels(SlideSize.WIDE_16_9)
    page = compose_page(slide_html, css=None, theme=Theme(), width_px=width, height_px=height)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=width, height=height)
    return extract_slide(rendered).slide


async def _render_and_extract_result(slide_html: str) -> ExtractResult:
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


async def test_browser_capture_preserves_canvas_identity_metadata() -> None:
    ir = await _render_and_extract(
        '<div data-domoxml-node-id="hero" data-domoxml-source-format="pptx" '
        'data-domoxml-source-id="12" data-domoxml-source-part="ppt/slides/slide1.xml" '
        'style="position:absolute;width:240px;height:100px;background:#174b5f">Hero</div>'
    )

    [hero] = [shape for shape in ir.shapes if shape.node_id == "hero"]
    assert hero.provenance is not None
    assert hero.provenance.source_format == "pptx"
    assert hero.provenance.source_id == "12"
    assert hero.provenance.source_part == "ppt/slides/slide1.xml"


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


async def test_extracts_ordered_list_item_ordinals() -> None:
    ir = await _render_and_extract(
        "<ol start='3'><li>Third</li><li value='7'>Seventh</li><li>Eighth</li></ol>"
    )

    numbered = [
        paragraph.bullet.start_at
        for shape in ir.shapes
        if shape.text is not None
        for paragraph in shape.text.paragraphs
        if isinstance(paragraph.bullet, AutoNumberBullet)
    ]
    assert numbered == [3, 7, 8]


async def test_formatted_nested_list_does_not_create_whitespace_bullets() -> None:
    ir = await _render_and_extract(
        """
        <ul>
          <li>Parent
            <ul>
              <li>Child</li>
            </ul>
          </li>
        </ul>
        """
    )

    bullet_texts = [
        "".join(run.text for run in paragraph.runs).strip()
        for shape in ir.shapes
        if shape.text is not None
        for paragraph in shape.text.paragraphs
        if paragraph.bullet is not None
    ]
    assert bullet_texts == ["Parent", "Child"]


@pytest.mark.integration
async def test_simple_flex_text_children_consolidate_into_anchored_parent() -> None:
    html = """
    <div style="position:absolute;left:20px;top:20px;width:300px;height:180px;
                display:flex;flex-direction:column;justify-content:center;background:#4472c4">
      <span style="font-size:20px;color:white">Heading</span>
      <span style="font-size:14px;color:white">Supporting text</span>
    </div>
    """

    ir = await _render_and_extract(html)
    anchored = [shape for shape in ir.shapes if shape.text is not None]

    assert len(anchored) == 1
    assert anchored[0].text is not None
    assert anchored[0].text.anchor == "middle"
    assert [[run.text for run in paragraph.runs] for paragraph in anchored[0].text.paragraphs] == [
        ["Heading"],
        ["Supporting text"],
    ]


@pytest.mark.integration
async def test_serialized_plain_text_body_preserves_anchor_and_columns() -> None:
    html = """
    <div data-domoxml-text-body="true"
         style="position:absolute;left:20px;top:20px;width:300px;height:180px;
                display:flex;flex-direction:column;justify-content:center;
                column-count:2;column-gap:24px;column-fill:auto;
                padding:16px;background:#4472c4">
      <div class="domoxml-text"><span>Heading</span></div>
      <div class="domoxml-text"><span>Supporting text</span></div>
    </div>
    """

    ir = await _render_and_extract(html)
    [text_shape] = [shape for shape in ir.shapes if shape.text is not None]

    assert text_shape.text is not None
    assert text_shape.text.anchor == "middle"
    assert text_shape.text.columns == 2
    assert text_shape.text.column_gap_emu > 0
    assert text_shape.text.margins == (152_400, 152_400, 152_400, 152_400)
    assert [[run.text for run in paragraph.runs] for paragraph in text_shape.text.paragraphs] == [
        ["Heading"],
        ["Supporting text"],
    ]


@pytest.mark.integration
async def test_balanced_columns_warn_about_powerpoint_sequential_fill() -> None:
    result = await _render_and_extract_result(
        """
        <div style="position:absolute;left:20px;top:20px;width:300px;height:180px;
                    column-count:2;column-gap:24px">
          Balanced browser columns cannot map exactly to native PowerPoint columns.
        </div>
        """
    )

    assert any("balanced CSS columns" in warning.message for warning in result.warnings)
    assert any(
        item.representation is Representation.APPROXIMATED and "balanced CSS columns" in item.reason
        for item in result.coverage
    )


@pytest.mark.integration
async def test_transition_root_background_does_not_emit_body_cover_shape() -> None:
    result = await _render_and_extract_result(
        """
        <div data-transition="fade"
             style="position:relative;width:1280px;height:720px;
                    background:linear-gradient(135deg,#667eea,#764ba2)">
          <div style="position:absolute;left:240px;top:220px;width:800px;height:280px;
                      background:rgba(255,255,255,.15)">Title</div>
        </div>
        """
    )

    assert result.slide.background is not None
    assert len(result.slide.shapes) == 1
    assert all(item.element != "<body>" for item in result.coverage)
