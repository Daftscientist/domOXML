"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import base64
import math
from io import BytesIO

import pytest
from PIL import Image

from domoxml import pptx_to_html
from domoxml.core.html import serialize_canvas
from domoxml.core.ir import ExtractResult, extract_slide
from domoxml.core.ir.group_payload import encode_group_payload
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Blur,
    Box,
    CharBullet,
    ClosePath,
    Connector,
    CubicTo,
    CustomGeometry,
    FillOverlay,
    GradientFill,
    GradientStop,
    GroupNode,
    Line,
    PatternFill,
    PictureFill,
    Point,
    PortableFallback,
    PreservationPayload,
    PreservedNode,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SoftEdge,
    SolidFill,
    SrcRect,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.core.render import BrowserSession, compose_page
from domoxml.core.roundtrip import inline_assets, render_html_roundtrip
from domoxml.core.units import pixels, px_to_emu
from domoxml.slides import build_pptx, read_pptx
from domoxml.types import Editability, Representation, SlideSize, SourceRetention, Theme

pytestmark = pytest.mark.integration


def _solid_shape(ir: SlideIR, hex_color: str) -> ShapeNode:
    return next(
        s for s in ir.shapes if isinstance(s.fill, SolidFill) and s.fill.color.hex == hex_color
    )


async def _render_and_extract(slide_html: str) -> SlideIR:
    width, height = pixels(SlideSize.WIDE_16_9)
    page = compose_page(slide_html, css=None, theme=Theme(), width_px=width, height_px=height)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=width, height=height)
    return extract_slide(rendered).slide


async def _render_and_extract_result(slide_html: str, *, css: str | None = None) -> ExtractResult:
    width, height = pixels(SlideSize.WIDE_16_9)
    page = compose_page(slide_html, css=css, theme=Theme(), width_px=width, height_px=height)
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


async def test_unmappable_background_raster_excludes_overlapping_native_text() -> None:
    # The stripe pattern has no native mapping, so the full-slide div is rasterised. Text drawn
    # over it is its own native shape; baking it into the raster too would draw it twice.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:0;top:0;width:1280px;height:720px;"
        "background:repeating-linear-gradient(90deg,transparent 0px,transparent 39px,"
        "rgba(24,31,26,.2) 39px,rgba(24,31,26,.2) 40px,rgba(200,30,30,.3) 41px)'></div>"
        "<div style='position:absolute;left:100px;top:100px;font-size:96px;font-weight:800;"
        "color:#111'>Overlap</div>"
    )

    pictures = [s for s in ir.shapes if isinstance(s.fill, PictureFill)]
    assert pictures, "the unmappable gradient should be an element layer"
    for picture in pictures:
        assert isinstance(picture.fill, PictureFill)
        with Image.open(BytesIO(picture.fill.data)) as image:
            raw = image.convert("RGBA").tobytes()
        text_pixels = sum(
            1 for i in range(0, len(raw), 4) if raw[i + 3] > 200 and max(raw[i : i + 3]) < 80
        )
        assert text_pixels == 0, "the raster must not contain the overlapping text's pixels"
    assert any(
        s.text is not None and any("Overlap" in r.text for p in s.text.paragraphs for r in p.runs)
        for s in ir.shapes
    ), "the text stays a native, editable shape"


async def test_descendants_of_a_rotated_element_keep_size_and_inherit_rotation() -> None:
    # A child has no transform of its own, but it is drawn rotated by its ancestor. Its box must
    # be its unrotated layout size (not the box enclosing the rotated shape) with the inherited
    # rotation, because every shape on a slide is positioned absolutely, never nested.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:300px;top:200px;width:400px;height:300px;"
        "transform:rotate(-13deg);background:#eee'>"
        "<div style='position:absolute;left:30px;top:40px;width:200px;height:4px;"
        "background:#123456'></div></div>"
    )

    bar = _solid_shape(ir, "123456")
    assert abs(bar.box.width - px_to_emu(200)) <= px_to_emu(1)
    assert abs(bar.box.height - px_to_emu(4)) <= px_to_emu(1)
    assert bar.transform is not None
    assert abs(bar.transform.rotation_deg - 347.0) < 0.5

    # The bar's centre in the unrotated card is (30+100, 40+2) from the card's top-left.
    # Rotating about the card centre (200, 150) by -13 degrees places it here on the slide.
    import math

    angle = math.radians(-13)
    dx, dy = (30 + 100) - 200, (40 + 2) - 150
    centre_x = 300 + 200 + dx * math.cos(angle) - dy * math.sin(angle)
    centre_y = 200 + 150 + dx * math.sin(angle) + dy * math.cos(angle)
    assert abs(bar.box.x + bar.box.width / 2 - px_to_emu(centre_x)) <= px_to_emu(1)
    assert abs(bar.box.y + bar.box.height / 2 - px_to_emu(centre_y)) <= px_to_emu(1)


async def test_nested_rotations_compose_and_cancelling_rotations_leave_no_transform() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:200px;top:150px;width:400px;height:300px;"
        "transform:rotate(30deg)'>"
        "<div style='position:absolute;left:20px;top:20px;width:100px;height:40px;"
        "transform:rotate(15deg);background:#aa0000'></div>"
        "<div style='position:absolute;left:20px;top:100px;width:100px;height:40px;"
        "transform:rotate(-30deg);background:#00aa00'></div></div>"
    )

    composed = _solid_shape(ir, "AA0000")
    assert composed.transform is not None
    assert abs(composed.transform.rotation_deg - 45.0) < 0.5
    assert abs(composed.box.width - px_to_emu(100)) <= px_to_emu(1)

    upright = _solid_shape(ir, "00AA00")
    assert upright.transform is None
    assert abs(upright.box.width - px_to_emu(100)) <= px_to_emu(1)
    assert abs(upright.box.height - px_to_emu(40)) <= px_to_emu(1)


async def test_text_inside_a_rotated_element_is_rotated_with_it() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:200px;top:150px;width:400px;height:300px;"
        "transform:rotate(10deg)'>"
        "<div style='position:absolute;left:20px;top:20px;font-size:32px;color:#111'>"
        "Tilted</div></div>"
    )

    label = next(
        s
        for s in ir.shapes
        if s.text is not None and any("Tilted" in r.text for p in s.text.paragraphs for r in p.runs)
    )
    assert label.transform is not None
    assert abs(label.transform.rotation_deg - 10.0) < 0.5


async def test_child_clipped_by_an_ancestor_is_rasterised_without_the_clipped_part() -> None:
    # Half the circle sits outside the card's overflow box. PowerPoint cannot clip one shape to
    # another, so the circle is rasterised in isolation and must not paint past the card edge.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "overflow:hidden;background:#eeeeee'>"
        "<div style='position:absolute;left:200px;top:50px;width:200px;height:100px;"
        "background:#cc2200'></div></div>"
    )

    [layer] = [s for s in ir.shapes if isinstance(s.fill, PictureFill)]
    assert isinstance(layer.fill, PictureFill)
    with Image.open(BytesIO(layer.fill.data)) as image:
        width = image.width
        alpha = image.convert("RGBA").getchannel("A").tobytes()
    scale = width / (layer.box.width / px_to_emu(1))

    def alpha_at(x: float, y: float) -> int:
        return alpha[int(y * scale) * width + int(x * scale)]

    # The child spans x=300..500; the card ends at x=400, so everything right of it is clipped.
    assert alpha_at(50, 20) == 255
    assert alpha_at(150, 20) == 0


async def test_children_inside_their_clipping_ancestor_stay_native() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "overflow:hidden;border-radius:12px;background:#eeeeee'>"
        "<div style='position:absolute;left:30px;top:30px;width:100px;height:20px;"
        "background:#cc2200'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(100)


async def test_rotated_clipping_ancestor_keeps_contained_children_native() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:300px;top:150px;width:400px;height:300px;"
        "overflow:hidden;border-radius:9px;transform:rotate(-13deg);background:#eeeeee'>"
        "<div style='position:absolute;left:28px;top:35px;width:300px;height:3px;"
        "background:#cc2200'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _solid_shape(ir, "CC2200").transform is not None


async def test_absolutely_positioned_child_escapes_an_unpositioned_clipping_ancestor() -> None:
    # The clip belongs to the static middle box, but the child's containing block is the outer
    # positioned box, so the browser does not clip it and neither must we.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:600px;height:400px'>"
        "<div style='overflow:hidden;width:100px;height:100px'>"
        "<div style='position:absolute;left:200px;top:200px;width:80px;height:40px;"
        "background:#cc2200'></div></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(80)


async def test_children_of_a_pill_shaped_clip_stay_native() -> None:
    # `border-radius:9999px` is the pill idiom. The used radius is clamped to half the shorter
    # side, so a child in the middle of the pill is not near any rounded corner.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:60px;"
        "overflow:hidden;border-radius:9999px;background:#eeeeee'>"
        "<div style='position:absolute;left:120px;top:20px;width:60px;height:20px;"
        "background:#cc2200'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(60)


async def test_absolutely_positioned_svg_poking_out_of_a_clip_is_rasterised() -> None:
    # Inline <svg> has no offsetParent, so its containing block has to be found by hand. A lone
    # <path> would otherwise become native custom geometry that spills past the clip.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:200px;"
        "overflow:hidden;background:#eeeeee'>"
        "<svg style='position:absolute;left:150px;top:50px' width='150' height='80' "
        "viewBox='0 0 150 80'><path d='M0 0H150V80H0Z' fill='#cc2200'/></svg></div>"
    )

    layer = next(s for s in ir.shapes if isinstance(s.fill, PictureFill))
    assert isinstance(layer.fill, PictureFill)


async def test_shape_bleeding_past_the_slide_edge_is_not_treated_as_clipped() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:1200px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(200)


async def test_backdrop_filter_raster_carries_the_blurred_backdrop_in_its_own_shape() -> None:
    # A backdrop blur has nothing to blur once the element is captured alone, so its layer is a
    # composite of what is painted below it, cut to the element's own rounded shape. Content
    # painted above it must stay out.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
        "<div style='position:absolute;left:150px;top:120px;width:300px;height:80px;"
        "border-radius:20px;background:rgba(255,255,255,.4);backdrop-filter:blur(6px)'></div>"
        "<div style='position:absolute;left:200px;top:140px;width:60px;height:20px;"
        "background:#000000'></div>"
    )

    [glass] = [s for s in ir.shapes if isinstance(s.fill, PictureFill)]
    assert isinstance(glass.fill, PictureFill)
    with Image.open(BytesIO(glass.fill.data)) as image:
        width = image.width
        rgba = image.convert("RGBA").tobytes()

    def pixel(x: float, y: float) -> tuple[int, int, int, int]:
        scale = width / (glass.box.width / px_to_emu(1))
        offset = (int(y * scale) * width + int(x * scale)) * 4
        return rgba[offset], rgba[offset + 1], rgba[offset + 2], rgba[offset + 3]

    red, green, _, alpha = pixel(20, 20)  # over the red box, inside the glass
    assert alpha == 255 and red - green > 40, "the backdrop is baked into the glass layer"
    assert pixel(0, 0)[3] == 0, "outside the rounded corner stays transparent"
    assert max(pixel(70, 30)[:3]) > 80, "content painted above the glass is not baked in"
    # What is below the glass is still its own native, editable shape.
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(200)


async def test_body_background_becomes_the_native_slide_background() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
    )

    assert ir.background is not None
    assert isinstance(ir.background.fill, SolidFill)
    # No full-slide rectangle underneath the content: only the authored shape remains.
    assert [s.box.width for s in ir.shapes] == [px_to_emu(200)]


async def test_full_slide_container_repeating_the_background_colour_is_folded_in() -> None:
    ir = await _render_and_extract(
        "<style>body{background:#f2f1ea}</style>"
        "<main style='position:relative;width:1280px;height:720px;background:#f2f1ea'>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div></main>"
    )

    assert ir.background is not None
    assert isinstance(ir.background.fill, SolidFill)
    assert ir.background.fill.color.hex == "F2F1EA"
    assert [s.box.width for s in ir.shapes] == [px_to_emu(200)]


async def test_full_slide_container_with_a_different_colour_stays_a_shape() -> None:
    ir = await _render_and_extract(
        "<style>body{background:#f2f1ea}</style>"
        "<main style='position:relative;width:1280px;height:720px;background:#102030'></main>"
    )

    assert ir.background is not None
    assert _solid_shape(ir, "102030").box.width == px_to_emu(1280)


async def test_same_colour_full_slide_shape_drawn_over_other_content_is_kept() -> None:
    # It covers the earlier shape, so removing it would reveal what it was hiding.
    ir = await _render_and_extract(
        "<style>body{background:#f2f1ea}</style>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
        "<div style='position:absolute;left:0;top:0;width:1280px;height:720px;"
        "background:#f2f1ea'></div>"
    )

    assert len(ir.shapes) == 2
    assert _solid_shape(ir, "F2F1EA").box.width == px_to_emu(1280)


async def test_translucent_or_rounded_full_slide_shape_is_not_folded() -> None:
    ir = await _render_and_extract(
        "<style>body{background:#f2f1ea}</style>"
        "<div style='position:absolute;left:0;top:0;width:1280px;height:720px;"
        "background:#f2f1ea;border-radius:24px'></div>"
    )

    assert len(ir.shapes) == 1


async def test_oversized_gradient_body_is_not_rescaled_into_the_slide_background() -> None:
    # Promoting this body would stretch its gradient from 1380px down to the 1280px slide and
    # shift it, so it stays the positioned shape it is.
    ir = await _render_and_extract(
        "<style>body{margin-left:-100px;width:1380px;"
        "background:linear-gradient(90deg,#102030,#405060)}</style>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
    )

    assert ir.background is None
    assert any(isinstance(s.fill, GradientFill) for s in ir.shapes)


async def test_blended_body_background_is_never_promoted() -> None:
    # background-blend-mode needs a fill overlay that the native background cannot carry.
    ir = await _render_and_extract(
        "<style>body{background:linear-gradient(90deg,#ff0000,#0000ff),#cc2200;"
        "background-blend-mode:multiply}</style>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
    )

    assert ir.background is None


async def test_picture_body_background_stays_a_shape() -> None:
    png = BytesIO()
    Image.new("RGB", (40, 10), (200, 30, 30)).save(png, "PNG")
    encoded = base64.b64encode(png.getvalue()).decode()
    ir = await _render_and_extract(
        f"<style>body{{background:url(data:image/png;base64,{encoded}) center/cover}}</style>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
    )

    assert ir.background is None
    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_gradient_body_background_is_a_native_gradient_slide_background() -> None:
    ir = await _render_and_extract(
        "<style>body{background:linear-gradient(90deg,#102030,#405060)}</style>"
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:80px;"
        "background:#cc2200'></div>"
    )

    assert ir.background is not None
    assert isinstance(ir.background.fill, GradientFill)
    assert len(ir.shapes) == 1


def _text_shape(ir: SlideIR, text: str) -> ShapeNode:
    return next(
        s
        for s in ir.shapes
        if s.text is not None and any(text in r.text for p in s.text.paragraphs for r in p.runs)
    )


async def test_plain_text_slack_never_moves_the_text_it_is_anchored_to() -> None:
    # A fill-less text box is widened so PowerPoint's wider glyph metrics do not force a wrap. The
    # extra width has to go on the side the text is not anchored to, or the text itself shifts.
    def row(top: int, align: str, text: str) -> str:
        return (
            f"<div style='position:absolute;left:200px;top:{top}px;width:300px;"
            f"text-align:{align}'>{text}</div>"
        )

    ir = await _render_and_extract(
        row(100, "left", "Lefty") + row(200, "right", "Righty") + row(300, "center", "Mid")
    )

    def edges(text: str) -> tuple[float, float]:
        box = _text_shape(ir, text).box
        return box.x / px_to_emu(1), (box.x + box.width) / px_to_emu(1)

    left_edge, left_right = edges("Lefty")
    assert (left_edge, left_right) == (200.0, 508.0), "left-aligned: slack on the right only"
    right_left, right_edge = edges("Righty")
    assert (right_left, right_edge) == (192.0, 500.0), "right-aligned: slack on the left only"
    mid_left, mid_right = edges("Mid")
    assert (mid_left, mid_right) == (196.0, 504.0), "centred: slack split evenly"


async def test_rotated_plain_text_keeps_its_anchor_point_despite_lopsided_slack() -> None:
    # PowerPoint rotates about the box centre, and one-sided slack moves that centre. The box is
    # shifted to compensate, so the text's anchored corner must land where the browser draws it.
    def row(top: int, align: str, text: str) -> str:
        return (
            f"<div style='position:absolute;left:300px;top:{top}px;width:300px;"
            f"text-align:{align};transform:rotate(30deg)'>{text}</div>"
        )

    ir = await _render_and_extract(row(100, "left", "Lefty") + row(300, "right", "Righty"))
    angle = math.radians(30)

    def rendered(box_x: float, box_y: float, box_w: float, box_h: float, px: float, py: float):
        cx, cy = box_x + box_w / 2, box_y + box_h / 2
        dx, dy = px - cx, py - cy
        return (
            cx + dx * math.cos(angle) - dy * math.sin(angle),
            cy + dx * math.sin(angle) + dy * math.cos(angle),
        )

    for text, top, anchor_is_right in (("Lefty", 100, False), ("Righty", 300, True)):
        box = _text_shape(ir, text).box
        x, y, w, h = (v / px_to_emu(1) for v in (box.x, box.y, box.width, box.height))
        # Where the browser draws the element's anchored top corner (box is 300 wide, unslacked).
        expected = rendered(300, top, 300, h, 300 + (300 if anchor_is_right else 0), top)
        actual = rendered(x, y, w, h, x + (w if anchor_is_right else 0), y)
        assert abs(actual[0] - expected[0]) < 1.0, (text, actual, expected)
        assert abs(actual[1] - expected[1]) < 1.0, (text, actual, expected)


async def test_isolated_effect_fallback_excludes_ancestor_backdrop() -> None:
    result = await _render_and_extract_result(
        '<div style="position:relative;width:1280px;height:720px;background:#f7f8fb">'
        '<div style="position:absolute;left:340px;top:214px;width:600px;height:268px;'
        "box-sizing:border-box;background:#2563eb;border:4px solid #facc15;"
        "border-radius:18px;box-shadow:18px 22px 24px rgba(15,23,42,.55),"
        '-26px 24px 30px 2px rgba(225,29,72,.65)"></div>'
        '<div style="position:absolute;inset:0;background:#22c55e;'
        'visibility:visible!important"></div></div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if shape.effect_container == "sibling" and shape.portable_fallback is not None
    ]
    assert shape.portable_fallback is not None
    with Image.open(BytesIO(shape.portable_fallback.picture.data)) as fallback:
        rgba = fallback.convert("RGBA")
        alpha = rgba.getchannel("A").tobytes()
        corners = (
            alpha[0],
            alpha[rgba.width - 1],
            alpha[(rgba.height - 1) * rgba.width],
            alpha[-1],
        )
        assert all(value == 0 for value in corners)
        assert alpha[(rgba.height // 2) * rgba.width + rgba.width // 2] == 255


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


async def test_extracts_css_fill_overlay_with_shape_bound_fallback() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background-color:#143c8c;"
        "background-image:linear-gradient(rgba(255,40,80,.75),rgba(255,40,80,.75));"
        'background-blend-mode:multiply;color:white;font-size:24px">OVERLAY</div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in shape.effects)
    ]
    assert shape.effects == (
        FillOverlay(
            fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
            blend="mult",
        ),
    )
    assert shape.fill == SolidFill(color=Rgba(r=20, g=60, b=140))
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


async def test_extracts_css_normal_overlay_as_typed_over_with_exact_owned_layer() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background-color:rgb(20,60,140);"
        "background-image:linear-gradient(rgba(255,40,80,.75),rgba(255,40,80,.75));"
        'background-blend-mode:normal"></div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in shape.effects)
    ]
    assert shape.fill == SolidFill(color=Rgba(r=20, g=60, b=140))
    assert shape.effects == (
        FillOverlay(
            fill=SolidFill(color=Rgba(r=255, g=40, b=80, a=0.75)),
            blend="over",
        ),
    )
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == shape.box
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    with Image.open(BytesIO(shape.portable_fallback.picture.data)) as fallback:
        assert fallback.convert("RGB").getpixel((110, 45)) == (196, 45, 95)
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(90)


async def test_css_normal_overlay_with_rounded_edges_stays_outside_typed_over_subset() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "border-radius:18px;background-color:rgb(20,60,140);"
        "background-image:linear-gradient(rgba(255,40,80,.75),rgba(255,40,80,.75));"
        'background-blend-mode:normal"></div>'
    )

    assert not any(
        isinstance(effect, FillOverlay) for shape in result.slide.shapes for effect in shape.effects
    )
    [coverage] = [
        item for item in result.coverage if item.representation is Representation.ELEMENT_LAYER
    ]
    assert coverage.editability is Editability.LAYERS


async def test_css_normal_overlay_with_element_opacity_stays_outside_typed_over_subset() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "opacity:.8;background-color:rgb(20,60,140);"
        "background-image:linear-gradient(rgba(255,40,80,.75),rgba(255,40,80,.75));"
        'background-blend-mode:normal"></div>'
    )

    assert not any(
        isinstance(effect, FillOverlay) for shape in result.slide.shapes for effect in shape.effects
    )
    [coverage] = [
        item for item in result.coverage if item.representation is Representation.ELEMENT_LAYER
    ]
    assert coverage.editability is Editability.LAYERS


async def test_extracts_picture_fill_overlay_with_shape_bound_fallback() -> None:
    image_buffer = BytesIO()
    image = Image.new("RGB", (8, 4), (37, 99, 235))
    for x in range(4, 8):
        for y in range(4):
            image.putpixel((x, y), (16, 185, 129))
    image.save(image_buffer, "PNG")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background-image:"
        "linear-gradient(rgba(244,63,94,.72),rgba(244,63,94,.72)),"
        f"url(data:image/png;base64,{encoded});"
        "background-blend-mode:multiply,normal;"
        "background-size:auto,100% 100%;"
        "background-position:0% 0%,0% 0%;"
        'background-repeat:repeat,no-repeat"></div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in shape.effects)
    ]
    assert isinstance(shape.fill, PictureFill)
    assert shape.fill.data == image_buffer.getvalue()
    assert shape.effects == (
        FillOverlay(
            fill=SolidFill(color=Rgba(r=244, g=63, b=94, a=0.72)),
            blend="mult",
        ),
    )
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(220),
        height=px_to_emu(90),
    )
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(90)

    serialized = inline_assets(serialize_canvas([result.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html, css=serialized.css)

    [recovered] = [
        candidate
        for candidate in second.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in candidate.effects)
    ]
    assert isinstance(recovered.fill, PictureFill)
    assert recovered.fill.data == image_buffer.getvalue()
    assert recovered.effects == shape.effects
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box


async def test_extracts_gradient_fill_overlay_and_reingests_exact_intent() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background-color:rgb(20,60,140);"
        "background-image:linear-gradient("
        "90deg,rgba(244,63,94,.8) 0%,rgba(37,99,235,.35) 100%);"
        'background-blend-mode:screen"></div>'
    )

    [shape] = [
        shape
        for shape in result.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in shape.effects)
    ]
    expected_effect = FillOverlay(
        fill=GradientFill(
            stops=(
                GradientStop(pos=0.0, color=Rgba(r=244, g=63, b=94, a=0.8)),
                GradientStop(pos=1.0, color=Rgba(r=37, g=99, b=235, a=0.35)),
            ),
            angle_deg=90.0,
        ),
        blend="screen",
    )
    assert shape.fill == SolidFill(color=Rgba(r=20, g=60, b=140))
    assert shape.effects == (expected_effect,)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(220),
        height=px_to_emu(90),
    )
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(90)

    serialized = inline_assets(serialize_canvas([result.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html, css=serialized.css)

    [recovered] = [
        candidate
        for candidate in second.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in candidate.effects)
    ]
    assert recovered.fill == shape.fill
    assert recovered.effects == (expected_effect,)
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box


async def test_extracts_pattern_fill_overlay_as_owned_hybrid_and_reingests() -> None:
    result = await _render_and_extract_result(
        '<div style="position:absolute;left:100px;top:80px;width:220px;height:90px;'
        "background-color:rgb(20,60,140);"
        "background-image:repeating-linear-gradient("
        "0deg,rgb(244,63,94) 0px,rgb(244,63,94) 1px,"
        "rgb(254,226,226) 1px,rgb(254,226,226) 4px);"
        'background-blend-mode:multiply"></div>'
    )

    [shape] = [
        candidate
        for candidate in result.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in candidate.effects)
    ]
    expected_effect = FillOverlay(
        fill=PatternFill(
            preset="horz",
            fg=Rgba(r=244, g=63, b=94),
            bg=Rgba(r=254, g=226, b=226),
        ),
        blend="mult",
    )
    assert shape.fill == SolidFill(color=Rgba(r=20, g=60, b=140))
    assert shape.effects == (expected_effect,)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(220),
        height=px_to_emu(90),
    )
    [coverage] = [item for item in result.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(220) * px_to_emu(90)

    serialized = inline_assets(serialize_canvas([result.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html, css=serialized.css)

    [recovered] = [
        candidate
        for candidate in second.slide.shapes
        if any(isinstance(effect, FillOverlay) for effect in candidate.effects)
    ]
    assert recovered.fill == shape.fill
    assert recovered.effects == (expected_effect,)
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box


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


async def test_normalized_html_reingests_one_native_group_without_flattening() -> None:
    group = GroupNode(
        node_id="group-1",
        box=Box(
            x=px_to_emu(200),
            y=px_to_emu(120),
            width=px_to_emu(420),
            height=px_to_emu(260),
        ),
        child_box=Box(
            x=px_to_emu(10),
            y=px_to_emu(20),
            width=px_to_emu(210),
            height=px_to_emu(130),
        ),
        children=(
            ShapeNode(
                node_id="group-1.1",
                box=Box(
                    x=px_to_emu(10),
                    y=px_to_emu(20),
                    width=px_to_emu(80),
                    height=px_to_emu(50),
                ),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
            ShapeNode(
                node_id="group-1.2",
                box=Box(
                    x=px_to_emu(120),
                    y=px_to_emu(50),
                    width=px_to_emu(90),
                    height=px_to_emu(80),
                ),
                fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
            ),
        ),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(group,))])
    )

    result = await _render_and_extract_result(
        f"<style>{serialized.css}</style>{serialized.slides[0].html}"
    )
    recovered_slide = result.slide

    [recovered] = recovered_slide.contents
    assert isinstance(recovered, GroupNode)
    assert recovered.node_id == group.node_id
    assert recovered.box == group.box
    assert recovered.child_box == group.child_box
    assert [child.node_id for child in recovered.children] == [
        child.node_id for child in group.children
    ]
    recovered_shapes = [child for child in recovered.children if isinstance(child, ShapeNode)]
    expected_shapes = [child for child in group.children if isinstance(child, ShapeNode)]
    assert len(recovered_shapes) == len(recovered.children)
    assert [child.box for child in recovered_shapes] == [child.box for child in expected_shapes]
    [coverage] = result.coverage
    assert coverage.representation is Representation.NATIVE
    assert coverage.editability is Editability.SEMANTIC
    assert coverage.output_count == 1
    assert not any(
        "flattened" in warning.message or "projection changed" in warning.message
        for warning in result.warnings
    )


async def test_authored_transformed_connector_group_converges_through_normalized_html() -> None:
    source = GroupNode(
        node_id="authored-group",
        box=Box(
            x=px_to_emu(180),
            y=px_to_emu(120),
            width=px_to_emu(360),
            height=px_to_emu(220),
        ),
        child_box=Box(x=0, y=0, width=px_to_emu(180), height=px_to_emu(110)),
        children=(
            ShapeNode(
                node_id="authored-shape",
                box=Box(x=0, y=0, width=px_to_emu(80), height=px_to_emu(60)),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
            Connector(
                node_id="authored-connector",
                start=Point(x=px_to_emu(30), y=px_to_emu(20)),
                end=Point(x=px_to_emu(150), y=px_to_emu(90)),
                line=Line(color=Rgba(r=15, g=23, b=42), width_emu=12_700),
            ),
        ),
        transform=Transform(rotation_deg=15),
    )
    recovered = source

    for _ in range(2):
        serialized = inline_assets(
            serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(recovered,))])
        )
        assert any("visibly flattened" in warning.message for warning in serialized.warnings)
        result = await _render_and_extract_result(
            f"<style>{serialized.css}</style>{serialized.slides[0].html}"
        )
        [candidate] = result.slide.contents
        assert isinstance(candidate, GroupNode)
        recovered = candidate

    assert recovered.node_id == source.node_id
    assert recovered.box == source.box
    assert recovered.child_box == source.child_box
    assert recovered.transform == source.transform
    assert [child.node_id for child in recovered.children] == [
        child.node_id for child in source.children
    ]
    recovered_shape, recovered_connector = recovered.children
    source_shape, source_connector = source.children
    assert isinstance(recovered_shape, ShapeNode)
    assert isinstance(source_shape, ShapeNode)
    assert recovered_shape.box == source_shape.box
    assert isinstance(recovered_connector, Connector)
    assert isinstance(source_connector, Connector)
    assert recovered_connector.start == source_connector.start
    assert recovered_connector.end == source_connector.end


async def test_stale_group_geometry_does_not_override_a_visible_html_edit() -> None:
    source = GroupNode(
        node_id="editable-group",
        box=Box(
            x=px_to_emu(200),
            y=px_to_emu(100),
            width=px_to_emu(300),
            height=px_to_emu(180),
        ),
        child_box=Box(x=0, y=0, width=px_to_emu(300), height=px_to_emu(180)),
        children=(
            ShapeNode(
                node_id="edited-child",
                box=Box(x=0, y=0, width=px_to_emu(120), height=px_to_emu(80)),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
        ),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(source,))])
    )
    html = serialized.slides[0].html
    assert "left:200px" in html
    edited_html = html.replace("left:200px", "left:240px", 1)

    result = await _render_and_extract_result(f"<style>{serialized.css}</style>{edited_html}")

    [edited] = result.slide.contents
    assert isinstance(edited, ShapeNode)
    assert edited.node_id == "edited-child"
    assert edited.box.x == px_to_emu(240)
    assert any("projection changed" in warning.message for warning in result.warnings)
    [coverage] = result.coverage
    assert coverage.representation is Representation.APPROXIMATED
    assert "left flattened" in coverage.reason


async def test_stale_group_wrapper_geometry_or_transform_does_not_override_html_edits() -> None:
    source = GroupNode(
        node_id="moved-group",
        box=Box(
            x=px_to_emu(180),
            y=px_to_emu(100),
            width=px_to_emu(300),
            height=px_to_emu(180),
        ),
        child_box=Box(x=0, y=0, width=px_to_emu(300), height=px_to_emu(180)),
        children=(
            ShapeNode(
                node_id="moved-child",
                box=Box(x=0, y=0, width=px_to_emu(120), height=px_to_emu(80)),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
            Connector(
                node_id="moved-connector",
                start=Point(x=px_to_emu(20), y=px_to_emu(20)),
                end=Point(x=px_to_emu(240), y=px_to_emu(140)),
                line=Line(color=Rgba(r=15, g=23, b=42), width_emu=12_700),
            ),
        ),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(source,))])
    )
    html = serialized.slides[0].html
    assert "left:180px" in html
    edited_html = html.replace("left:180px", "left:220px", 1)

    result = await _render_and_extract_result(f"<style>{serialized.css}</style>{edited_html}")

    assert all(not isinstance(node, GroupNode) for node in result.slide.contents)
    moved = next(node for node in result.slide.contents if node.node_id == "moved-child")
    assert isinstance(moved, ShapeNode)
    assert moved.box.x == px_to_emu(220)
    assert any("projection changed" in warning.message for warning in result.warnings)
    assert all(item.representation is Representation.APPROXIMATED for item in result.coverage)

    for transform in ("translateX(40px)", "scale(1.2)"):
        transformed_html = html.replace(
            "overflow:visible", f"overflow:visible;transform:{transform}", 1
        )
        transformed = await _render_and_extract_result(
            f"<style>{serialized.css}</style>{transformed_html}"
        )
        assert all(not isinstance(node, GroupNode) for node in transformed.slide.contents)
        assert any("projection changed" in warning.message for warning in transformed.warnings)
        assert all(
            item.representation is Representation.APPROXIMATED for item in transformed.coverage
        )


async def test_invalid_normalized_group_payload_leaves_visible_children_flattened() -> None:
    result = await _render_and_extract_result(
        '<div class="domoxml-slide" style="width:1280px;height:720px">'
        '<div data-domoxml-node-id="broken-group" data-domoxml-group="not-base64" '
        'style="display:contents">'
        '<div data-domoxml-node-id="child-a" style="position:absolute;left:100px;top:80px;'
        'width:140px;height:90px;background:#ef4444"></div>'
        '<div data-domoxml-node-id="child-b" style="position:absolute;left:260px;top:120px;'
        'width:120px;height:100px;background:#2563eb"></div>'
        "</div></div>"
    )

    assert [node.node_id for node in result.slide.contents] == ["child-a", "child-b"]
    assert all(isinstance(node, ShapeNode) for node in result.slide.contents)
    assert any("invalid normalized group payload" in warning.message for warning in result.warnings)


async def test_zero_size_normalized_group_box_leaves_visible_children_flattened() -> None:
    payload = encode_group_payload(
        box=Box(x=px_to_emu(100), y=px_to_emu(80), width=0, height=px_to_emu(100)),
        child_box=Box(x=0, y=0, width=px_to_emu(140), height=px_to_emu(90)),
    )
    result = await _render_and_extract_result(
        '<div class="domoxml-slide" style="width:1280px;height:720px">'
        f'<div data-domoxml-node-id="zero-group" data-domoxml-group="{payload}" '
        'style="display:contents">'
        '<div data-domoxml-node-id="child-a" style="position:absolute;left:100px;top:80px;'
        'width:140px;height:90px;background:#ef4444"></div>'
        "</div></div>"
    )

    [child] = result.slide.contents
    assert isinstance(child, ShapeNode)
    assert child.node_id == "child-a"
    assert any("invalid normalized group payload" in warning.message for warning in result.warnings)


async def test_normalized_group_requires_stable_identity_on_every_child() -> None:
    payload = encode_group_payload(
        box=Box(
            x=px_to_emu(100),
            y=px_to_emu(80),
            width=px_to_emu(300),
            height=px_to_emu(180),
        ),
        child_box=Box(x=0, y=0, width=px_to_emu(300), height=px_to_emu(180)),
    )
    result = await _render_and_extract_result(
        '<div class="domoxml-slide" style="width:1280px;height:720px">'
        f'<div data-domoxml-node-id="partial-group" data-domoxml-group="{payload}" '
        'style="display:contents">'
        '<div data-domoxml-node-id="child-a" style="position:absolute;left:100px;top:80px;'
        'width:140px;height:90px;background:#ef4444"></div>'
        '<div style="position:absolute;left:260px;top:120px;width:120px;height:100px;'
        'background:#2563eb"></div>'
        "</div></div>"
    )

    assert len(result.slide.contents) == 2
    assert all(isinstance(child, ShapeNode) for child in result.slide.contents)
    assert any("missing stable identity" in warning.message for warning in result.warnings)


def test_native_group_converges_across_two_normalized_html_cycles() -> None:
    group = GroupNode(
        node_id="group-1",
        box=Box(
            x=px_to_emu(200),
            y=px_to_emu(120),
            width=px_to_emu(420),
            height=px_to_emu(260),
        ),
        child_box=Box(
            x=px_to_emu(10),
            y=px_to_emu(20),
            width=px_to_emu(210),
            height=px_to_emu(130),
        ),
        children=(
            ShapeNode(
                node_id="group-1.1",
                box=Box(
                    x=px_to_emu(10),
                    y=px_to_emu(20),
                    width=px_to_emu(80),
                    height=px_to_emu(50),
                ),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
            ShapeNode(
                node_id="group-1.2",
                box=Box(
                    x=px_to_emu(120),
                    y=px_to_emu(50),
                    width=px_to_emu(90),
                    height=px_to_emu(80),
                ),
                fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
            ),
        ),
    )
    pptx = build_pptx([SlideIR(width=12_192_000, height=6_858_000, contents=(group,))], faces=[])

    for _ in range(2):
        html = pptx_to_html(pptx)
        assert 'data-domoxml-group="' in html.slides[0].html
        result = render_html_roundtrip(html)
        assert result.pptx is not None
        pptx = result.pptx

    [recovered] = read_pptx(pptx)[0].contents
    assert isinstance(recovered, GroupNode)
    assert recovered.node_id == group.node_id
    assert recovered.box == group.box
    assert recovered.child_box == group.child_box
    assert [child.node_id for child in recovered.children] == [
        child.node_id for child in group.children
    ]
    recovered_shapes = [child for child in recovered.children if isinstance(child, ShapeNode)]
    expected_shapes = [child for child in group.children if isinstance(child, ShapeNode)]
    assert len(recovered_shapes) == len(recovered.children)
    assert [child.box for child in recovered_shapes] == [child.box for child in expected_shapes]


def test_native_group_picture_child_converges_across_two_normalized_html_cycles() -> None:
    image = BytesIO()
    Image.new("RGB", (24, 16), "#2563eb").save(image, "PNG")
    picture_data = image.getvalue()
    group = GroupNode(
        node_id="picture-group",
        box=Box(
            x=px_to_emu(200),
            y=px_to_emu(120),
            width=px_to_emu(420),
            height=px_to_emu(260),
        ),
        child_box=Box(
            x=px_to_emu(10),
            y=px_to_emu(20),
            width=px_to_emu(210),
            height=px_to_emu(130),
        ),
        children=(
            ShapeNode(
                node_id="group-picture",
                box=Box(
                    x=px_to_emu(10),
                    y=px_to_emu(20),
                    width=px_to_emu(120),
                    height=px_to_emu(90),
                ),
                fill=PictureFill(
                    data=picture_data,
                    ext="png",
                    crop=SrcRect(left=0.125, right=0.125),
                ),
            ),
            ShapeNode(
                node_id="group-shape",
                box=Box(
                    x=px_to_emu(140),
                    y=px_to_emu(40),
                    width=px_to_emu(60),
                    height=px_to_emu(70),
                ),
                fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
            ),
        ),
    )
    pptx = build_pptx(
        [SlideIR(width=12_192_000, height=6_858_000, contents=(group,))],
        faces=[],
    )

    for _ in range(2):
        html = pptx_to_html(pptx)
        assert 'data-domoxml-group="' in html.slides[0].html
        assert "background-image:url(../assets/" in html.slides[0].html
        result = render_html_roundtrip(html)
        assert result.pptx is not None
        pptx = result.pptx

    [recovered] = read_pptx(pptx)[0].contents
    assert isinstance(recovered, GroupNode)
    assert recovered.node_id == group.node_id
    assert recovered.box == group.box
    assert recovered.child_box == group.child_box
    assert [child.node_id for child in recovered.children] == [
        "group-picture",
        "group-shape",
    ]
    picture, shape = recovered.children
    source_picture, source_shape = group.children
    assert isinstance(picture, ShapeNode)
    assert isinstance(shape, ShapeNode)
    assert isinstance(source_picture, ShapeNode)
    assert isinstance(source_shape, ShapeNode)
    assert [picture.box, shape.box] == [source_picture.box, source_shape.box]
    assert isinstance(picture.fill, PictureFill)
    assert picture.fill.data == picture_data
    assert picture.fill.crop == SrcRect(left=0.125, right=0.125)
    assert shape.fill == source_shape.fill


def test_native_group_keeps_its_top_level_position_between_siblings() -> None:
    before = ShapeNode(
        node_id="before",
        box=Box(x=px_to_emu(40), y=px_to_emu(40), width=px_to_emu(100), height=px_to_emu(80)),
        fill=SolidFill(color=Rgba(r=15, g=23, b=42)),
    )
    group = GroupNode(
        node_id="group",
        box=Box(x=px_to_emu(200), y=px_to_emu(120), width=px_to_emu(300), height=px_to_emu(180)),
        child_box=Box(x=0, y=0, width=px_to_emu(300), height=px_to_emu(180)),
        children=(
            ShapeNode(
                node_id="group-child",
                box=Box(x=0, y=0, width=px_to_emu(300), height=px_to_emu(180)),
                fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
            ),
        ),
    )
    after = ShapeNode(
        node_id="after",
        box=Box(x=px_to_emu(540), y=px_to_emu(320), width=px_to_emu(100), height=px_to_emu(80)),
        fill=SolidFill(color=Rgba(r=245, g=158, b=11)),
    )
    pptx = build_pptx(
        [
            SlideIR(
                width=12_192_000,
                height=6_858_000,
                contents=(before, group, after),
            )
        ],
        faces=[],
    )

    html = pptx_to_html(pptx)
    rebuilt = render_html_roundtrip(html)
    assert rebuilt.pptx is not None
    recovered = read_pptx(rebuilt.pptx)[0]

    assert [node.node_id for node in recovered.contents] == ["before", "group", "after"]
    assert isinstance(recovered.contents[1], GroupNode)


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


async def test_browser_capture_restores_slide_fallback_above_native_contents() -> None:
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (1280, 720), "#315C7B").save(image, "PNG")
    payload = PreservationPayload(kind="sp", root_xml="<p:sp/>")
    preserved = PreservedNode(
        node_id="shadow-source",
        box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
        payload=payload,
    )
    sibling = ShapeNode(
        node_id="sibling",
        box=Box(x=2_000_000, y=1_500_000, width=2_500_000, height=1_500_000),
        fill=SolidFill(color=Rgba(r=239, g=68, b=68, a=0.55)),
    )
    serialized = inline_assets(
        serialize_canvas(
            [
                SlideIR(
                    width=12_192_000,
                    height=6_858_000,
                    contents=(preserved, sibling),
                    renderer_fallback=PictureFill(data=image.getvalue(), ext="png"),
                    renderer_fallback_owner_node_id="shadow-source",
                )
            ]
        )
    )

    result = await _render_and_extract_result(serialized.slides[0].html)

    assert result.slide.renderer_fallback is not None
    assert result.slide.renderer_fallback.data == image.getvalue()
    assert result.slide.renderer_fallback_owner_node_id == "shadow-source"
    assert [node.node_id for node in result.slide.contents] == ["shadow-source", "sibling"]
    assert [item.representation for item in result.coverage] == [
        Representation.NATIVE,
        Representation.RASTERIZED,
    ]
    assert result.coverage[-1].source_retention is SourceRetention.ATTACHED


async def test_slide_fallback_does_not_claim_unrelated_preserved_source() -> None:
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (1280, 720), "#315C7B").save(image, "PNG")
    owned = PreservedNode(
        node_id="shadow-source",
        box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
        payload=PreservationPayload(kind="sp", root_xml="<p:sp/>"),
    )
    unrelated = PreservedNode(
        node_id="chart-source",
        box=Box(x=3_000_000, y=1_000_000, width=2_000_000, height=2_000_000),
        payload=PreservationPayload(kind="graphicFrame", root_xml="<p:graphicFrame/>"),
    )
    serialized = inline_assets(
        serialize_canvas(
            [
                SlideIR(
                    width=12_192_000,
                    height=6_858_000,
                    contents=(owned, unrelated),
                    renderer_fallback=PictureFill(data=image.getvalue(), ext="png"),
                    renderer_fallback_owner_node_id="shadow-source",
                )
            ]
        )
    )

    result = await _render_and_extract_result(serialized.slides[0].html)

    assert result.slide.renderer_fallback_owner_node_id == "shadow-source"
    assert [item.representation for item in result.coverage] == [
        Representation.FAILED,
        Representation.RASTERIZED,
    ]
    assert result.coverage[0].source_retention is SourceRetention.ATTACHED
    assert result.coverage[0].output_count == 0
    assert result.coverage[-1].source_retention is SourceRetention.ATTACHED


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


async def test_svg_drop_shadow_becomes_native_custom_geometry_effect() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px">
      <path d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#4472c4"
            style="filter:drop-shadow(rgba(0,0,0,0.4) 6px 8px 12px)"/>
    </svg>
    """

    result = await _render_and_extract_result(html)

    [shape] = [candidate for candidate in result.slide.shapes if candidate.custom_geom is not None]
    assert shape.custom_geom is not None
    [effect] = shape.effects
    assert isinstance(effect, Shadow)
    assert (effect.color.r, effect.color.g, effect.color.b) == (0, 0, 0)
    assert abs(effect.color.a - 0.3) < 1e-9
    assert effect.distance_emu == px_to_emu(10)
    assert effect.blur_emu == px_to_emu(12)
    assert any(item.representation is Representation.NATIVE for item in result.coverage)


async def test_svg_blur_becomes_native_custom_geometry_with_owned_layer() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px;
                overflow:visible;filter:blur(12px)">
      <path d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#4472c4" stroke="#1f4e79" stroke-width="4"/>
    </svg>
    """

    first = await _render_and_extract_result(html)

    [shape] = [candidate for candidate in first.slide.shapes if candidate.custom_geom is not None]
    assert shape.effects == (Blur(radius_emu=px_to_emu(12)),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(64),
        y=px_to_emu(44),
        width=px_to_emu(272),
        height=px_to_emu(172),
    )
    [coverage] = [item for item in first.coverage if item.representation is Representation.HYBRID]
    assert coverage.representation is Representation.HYBRID
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(272) * px_to_emu(172)

    serialized = inline_assets(serialize_canvas([first.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html)

    [recovered] = [
        candidate for candidate in second.slide.shapes if candidate.custom_geom is not None
    ]
    assert recovered.custom_geom == shape.custom_geom
    assert recovered.effects == shape.effects
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box
    [second_coverage] = [
        item for item in second.coverage if item.representation is Representation.HYBRID
    ]
    assert second_coverage.representation is Representation.HYBRID
    assert second_coverage.editability is Editability.COMPONENTS
    assert second_coverage.output_count == 2
    assert second_coverage.raster_area_emu2 == coverage.raster_area_emu2


async def test_svg_reflection_becomes_native_custom_geometry_with_owned_layer() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px;
                overflow:visible;-webkit-box-reflect:below 12px
                linear-gradient(to bottom,rgba(0,0,0,.8) 0%,transparent 100%)">
      <path d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#4472c4" stroke="#1f4e79" stroke-width="4"/>
    </svg>
    """

    first = await _render_and_extract_result(html)

    [shape] = [candidate for candidate in first.slide.shapes if candidate.custom_geom is not None]
    assert shape.effects == (
        Reflection(
            distance_emu=px_to_emu(12),
            start_alpha=0.8,
            end_alpha=0.0,
        ),
    )
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(200),
        height=px_to_emu(212),
    )
    [coverage] = [item for item in first.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(200) * px_to_emu(212)

    serialized = inline_assets(serialize_canvas([first.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html)

    [recovered] = [
        candidate for candidate in second.slide.shapes if candidate.custom_geom is not None
    ]
    assert recovered.custom_geom == shape.custom_geom
    assert recovered.effects == shape.effects
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box
    [second_coverage] = [
        item for item in second.coverage if item.representation is Representation.HYBRID
    ]
    assert second_coverage.editability is Editability.COMPONENTS
    assert second_coverage.output_count == 2
    assert second_coverage.raster_area_emu2 == coverage.raster_area_emu2


async def test_svg_soft_edge_becomes_native_custom_geometry_with_owned_layer() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px;
                overflow:visible">
      <defs>
        <filter id="soft-edge" x="0" y="0" width="100%" height="100%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="softBlur"/>
          <feComposite in="softBlur" in2="SourceAlpha" operator="in" result="softClip"/>
          <feComposite in="SourceGraphic" in2="softClip" operator="in"/>
        </filter>
      </defs>
      <path style="filter:url(#soft-edge)"
            d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#4472c4" stroke="#1f4e79" stroke-width="4"/>
    </svg>
    """

    first = await _render_and_extract_result(html)

    [shape] = [candidate for candidate in first.slide.shapes if candidate.custom_geom is not None]
    assert shape.effects == (SoftEdge(radius_emu=px_to_emu(12)),)
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(200),
        height=px_to_emu(100),
    )
    with Image.open(BytesIO(shape.portable_fallback.picture.data)) as fallback:
        alpha = fallback.convert("RGBA").getchannel("A")
        assert alpha.getextrema() == (0, 255)
        assert any(0 < value < 255 for value in alpha.tobytes())
    [coverage] = [item for item in first.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(200) * px_to_emu(100)

    serialized = inline_assets(serialize_canvas([first.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html)

    [recovered] = [
        candidate for candidate in second.slide.shapes if candidate.custom_geom is not None
    ]
    assert recovered.custom_geom == shape.custom_geom
    assert recovered.effects == shape.effects
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box
    [second_coverage] = [
        item for item in second.coverage if item.representation is Representation.HYBRID
    ]
    assert second_coverage.editability is Editability.COMPONENTS
    assert second_coverage.output_count == 2
    assert second_coverage.raster_area_emu2 == coverage.raster_area_emu2


async def test_svg_fill_overlay_becomes_native_custom_geometry_with_owned_layer() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px;
                overflow:visible">
      <defs>
        <filter id="fill-overlay" x="0" y="0" width="100%" height="100%"
                color-interpolation-filters="sRGB">
          <feFlood flood-color="rgb(244,63,94)" flood-opacity=".72" result="overlay"/>
          <feComposite in="overlay" in2="SourceAlpha" operator="in" result="overlayClip"/>
          <feBlend in="SourceGraphic" in2="overlayClip" mode="multiply"/>
        </filter>
      </defs>
      <path style="filter:url(#fill-overlay)"
            d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#2563eb" stroke="#1e3a8a" stroke-width="4"/>
    </svg>
    """

    first = await _render_and_extract_result(html)

    [shape] = [candidate for candidate in first.slide.shapes if candidate.custom_geom is not None]
    assert shape.fill == SolidFill(color=Rgba(r=37, g=99, b=235))
    assert shape.effects == (
        FillOverlay(
            fill=SolidFill(color=Rgba(r=244, g=63, b=94, a=0.72)),
            blend="mult",
        ),
    )
    assert shape.portable_fallback is not None
    assert shape.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert shape.portable_fallback.box == Box(
        x=px_to_emu(100),
        y=px_to_emu(80),
        width=px_to_emu(200),
        height=px_to_emu(100),
    )
    [coverage] = [item for item in first.coverage if item.representation is Representation.HYBRID]
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(200) * px_to_emu(100)

    serialized = inline_assets(serialize_canvas([first.slide]))
    second = await _render_and_extract_result(serialized.slides[0].html)

    [recovered] = [
        candidate for candidate in second.slide.shapes if candidate.custom_geom is not None
    ]
    assert recovered.custom_geom == shape.custom_geom
    assert recovered.fill == shape.fill
    assert recovered.effects == shape.effects
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.box == shape.portable_fallback.box
    [second_coverage] = [
        item for item in second.coverage if item.representation is Representation.HYBRID
    ]
    assert second_coverage.editability is Editability.COMPONENTS
    assert second_coverage.output_count == 2
    assert second_coverage.raster_area_emu2 == coverage.raster_area_emu2


async def test_custom_geometry_owned_effect_layer_round_trips_as_one_hybrid() -> None:
    fallback_buffer = BytesIO()
    Image.new("RGBA", (250, 140), (37, 99, 235, 255)).save(fallback_buffer, "PNG")
    geometry = CustomGeometry(
        width_emu=px_to_emu(200),
        height_emu=px_to_emu(100),
        path=(
            CubicTo(
                c1=Point(x=0, y=0),
                c2=Point(x=px_to_emu(200), y=0),
                to=Point(x=px_to_emu(200), y=px_to_emu(100)),
            ),
            ClosePath(),
        ),
    )
    effects = (
        Shadow(
            color=Rgba(r=15, g=23, b=42, a=0.55),
            blur_emu=px_to_emu(20),
            distance_emu=px_to_emu(24),
            direction_deg=45,
        ),
        Shadow(
            color=Rgba(r=255, g=255, b=255, a=0.7),
            blur_emu=px_to_emu(10),
            distance_emu=px_to_emu(5),
            direction_deg=45,
            inset=True,
        ),
        Shadow(
            color=Rgba(r=225, g=29, b=72, a=0.65),
            blur_emu=px_to_emu(30),
            distance_emu=px_to_emu(36),
            direction_deg=135,
        ),
    )
    node = ShapeNode(
        node_id="custom-owned-effects",
        box=Box(
            x=px_to_emu(100),
            y=px_to_emu(80),
            width=px_to_emu(200),
            height=px_to_emu(100),
        ),
        custom_geom=geometry,
        fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
        effects=effects,
        native_effect_projection="schema_subset",
        portable_fallback=PortableFallback(
            box=Box(
                x=px_to_emu(80),
                y=px_to_emu(70),
                width=px_to_emu(250),
                height=px_to_emu(140),
            ),
            picture=PictureFill(data=fallback_buffer.getvalue(), ext="png"),
        ),
    )
    serialized = inline_assets(
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(node,))])
    )

    result = await _render_and_extract_result(serialized.slides[0].html)

    [recovered] = [shape for shape in result.slide.shapes if shape.node_id == node.node_id]
    assert recovered.custom_geom == geometry
    assert recovered.effects == effects
    assert recovered.native_effect_projection == "schema_subset"
    assert recovered.portable_fallback is not None
    assert recovered.portable_fallback.picture.raster_role == "portable-effect-fallback"
    assert node.portable_fallback is not None
    assert recovered.portable_fallback.box == node.portable_fallback.box
    [coverage] = result.coverage
    assert coverage.representation is Representation.HYBRID
    assert coverage.editability is Editability.COMPONENTS
    assert coverage.output_count == 2
    assert coverage.raster_area_emu2 == px_to_emu(250) * px_to_emu(140)


async def test_unsupported_svg_filter_uses_visible_element_layer() -> None:
    html = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"
         style="position:absolute;left:100px;top:80px;width:200px;height:100px">
      <path d="M 10 50 C 10 10 190 10 190 50 C 190 90 10 90 10 50 Z"
            fill="#4472c4" style="filter:brightness(0.8)"/>
    </svg>
    """

    result = await _render_and_extract_result(html)

    [shape] = [
        candidate
        for candidate in result.slide.shapes
        if isinstance(candidate.fill, PictureFill) and candidate.custom_geom is None
    ]
    assert shape.custom_geom is None
    [coverage] = [
        item for item in result.coverage if item.representation is Representation.ELEMENT_LAYER
    ]
    assert coverage.representation is Representation.ELEMENT_LAYER
    assert coverage.editability is Editability.LAYERS
    assert coverage.output_count == 1
    assert result.warnings and "filter" in result.warnings[0].message


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
