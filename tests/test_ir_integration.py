"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import pytest

from domoxml.core.html import serialize_canvas
from domoxml.core.ir import ExtractResult, extract_slide
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    PictureFill,
    PreservationPayload,
    PreservedNode,
    Reflection,
    Rgba,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.render import BrowserSession, compose_page
from domoxml.core.roundtrip import inline_assets
from domoxml.core.units import pixels, px_to_emu
from domoxml.types import Editability, Representation, SlideSize, SourceRetention, Theme

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


async def test_extracts_css_reflection_with_complete_isolated_paint_bounds() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background:#e84a5f;color:white;font-size:24px;"
        "-webkit-box-reflect:below 12px linear-gradient(to bottom, "
        'rgba(0,0,0,0.8) 0%, transparent 100%)">REFLECT</div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, Reflection) for effect in shape.effects)
    ]
    assert shape.effects == (
        Reflection(
            distance_emu=px_to_emu(12),
            start_alpha=0.8,
            end_alpha=0.0,
        ),
    )
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(220),
        height=px_to_emu(192),
    )
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(192)


async def test_extracts_css_soft_edge_with_shape_bound_fallback() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background:#276678;color:white;font-size:24px;"
        "mask-image:linear-gradient(to right,transparent 0px,black 12px,"
        "black calc(100% - 12px),transparent 100%),"
        "linear-gradient(to bottom,transparent 0px,black 12px,"
        "black calc(100% - 12px),transparent 100%);"
        'mask-composite:intersect">SOFT EDGE</div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, SoftEdge) for effect in shape.effects)
    ]
    assert shape.effects == (SoftEdge(radius_emu=px_to_emu(12)),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(220),
        height=px_to_emu(90),
    )
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(90)


async def test_blurred_reflection_render_layer_reingests_as_one_hybrid_owner() -> None:
    reflection = Reflection(
        blur_emu=px_to_emu(4),
        distance_emu=px_to_emu(12),
        start_alpha=0.8,
        end_alpha=0.0,
    )
    node = ShapeNode(
        node_id="blurred-reflection",
        box=Box(
            x=px_to_emu(100),
            y=px_to_emu(80),
            width=px_to_emu(220),
            height=px_to_emu(90),
        ),
        fill=SolidFill(color=Rgba(r=232, g=74, b=95)),
        effects=(reflection,),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])
    )

    result = await _render_and_extract_result(
        f"<style>{serialized.css}</style>{serialized.slides[0].html}"
    )

    [recovered] = [shape for shape in result.slide.shapes if shape.node_id == node.node_id]
    assert recovered.effects == (reflection,)
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == Box(
        x=px_to_emu(88),
        y=px_to_emu(80),
        width=px_to_emu(244),
        height=px_to_emu(204),
    )
    assert len(result.slide.shapes) == 1
    [coverage] = result.coverage
    assert coverage.representation is Representation.HYBRID
    assert coverage.output_count == 2


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


async def test_browser_capture_restores_attached_preservation_payload() -> None:
    payload = PreservationPayload(kind="graphicFrame", root_xml="<p:graphicFrame/>")
    node = PreservedNode(
        node_id="chart-1",
        box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
        payload=payload,
    )
    html = (
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])
        .slides[0]
        .html
    )

    ir = await _render_and_extract(html)

    [recovered] = [item for item in ir.contents if isinstance(item, PreservedNode)]
    assert recovered.node_id == "chart-1"
    assert recovered.payload == payload


async def test_browser_capture_restores_preserved_visual_fallback_and_coverage() -> None:
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (240, 100), "#2A7F62").save(image, "PNG")
    payload = PreservationPayload(kind="graphicFrame", root_xml="<p:graphicFrame/>")
    node = PreservedNode(
        node_id="chart-1",
        box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
        payload=payload,
        fallback=PictureFill(data=image.getvalue(), ext="png"),
    )
    serialized = serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])

    result = await _render_and_extract_result(inline_assets(serialized).slides[0].html)

    [recovered] = [item for item in result.slide.contents if isinstance(item, PreservedNode)]
    assert recovered.fallback is not None
    assert recovered.payload == payload
    assert recovered.fallback.data == image.getvalue()
    [coverage] = result.coverage
    assert coverage.representation is Representation.ELEMENT_LAYER
    assert coverage.source_retention is SourceRetention.ATTACHED


async def test_serialized_text_payload_keeps_the_exact_source_box() -> None:
    body = TextBody(paragraphs=(TextParagraph(runs=()),))
    node = ShapeNode(
        node_id="title",
        box=Box(x=760_363, y=442_466, width=438_894, height=1_840_260),
        text=body,
    )
    serialized = serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])

    inlined = inline_assets(serialized)
    recovered = await _render_and_extract(f"<style>{inlined.css}</style>{inlined.slides[0].html}")

    [title] = [shape for shape in recovered.shapes if shape.node_id == "title"]
    assert title.box == node.box


async def test_serialized_bullet_payload_owns_its_rendered_list_subtree() -> None:
    paragraphs = tuple(
        TextParagraph(
            runs=(TextRun(text=text, font_family="Arial", size_pt=18),),
            bullet=CharBullet(char="\u2022"),
        )
        for text in ("First", "Second")
    )
    node = ShapeNode(
        node_id="bullets",
        box=Box(x=762_000, y=438_150, width=5_334_000, height=1_828_800),
        text=TextBody(paragraphs=paragraphs),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])
    )

    result = await _render_and_extract_result(
        f"<style>{serialized.css}</style>{serialized.slides[0].html}"
    )

    [recovered] = result.slide.shapes
    assert recovered.node_id == "bullets"
    assert recovered.text == node.text
    assert len(result.coverage) == 1


async def test_serialized_table_payload_preserves_exact_geometry() -> None:
    table = TableNode(
        node_id="table",
        box=Box(x=4_114_800, y=2_743_200, width=4_114_800, height=1_371_600),
        col_widths_emu=(2_057_400, 2_057_400),
        rows=(
            TableRow(height_emu=685_800, cells=(TableCell(), TableCell())),
            TableRow(height_emu=685_800, cells=(TableCell(), TableCell())),
        ),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(table,))])
    )

    result = await _render_and_extract_result(
        f"<style>{serialized.css}</style>{serialized.slides[0].html}"
    )

    [recovered] = [node for node in result.slide.contents if isinstance(node, TableNode)]
    assert recovered.box == table.box
    assert recovered.col_widths_emu == table.col_widths_emu
    assert tuple(row.height_emu for row in recovered.rows) == tuple(
        row.height_emu for row in table.rows
    )


async def test_browser_capture_retains_serialized_svg_picture_bytes() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    node = ShapeNode(
        node_id="vector",
        box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
        fill=PictureFill(data=b"png", ext="png", svg_data=svg),
    )
    serialized = serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])
    html = inline_assets(serialized).slides[0].html

    result = await _render_and_extract_result(html)

    [recovered] = [shape for shape in result.slide.shapes if shape.node_id == "vector"]
    assert isinstance(recovered.fill, PictureFill)
    assert recovered.fill.svg_data == svg
    assert [item.representation for item in result.coverage] == [Representation.NATIVE]


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
