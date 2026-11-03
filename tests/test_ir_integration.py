"""Render → extract end-to-end. Requires Chromium: ``playwright install chromium``."""

from __future__ import annotations

import base64
import math
from collections.abc import Callable
from io import BytesIO
from zipfile import ZipFile

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
    LineTo,
    MediaNode,
    MoveTo,
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
    # A <canvas> is raster by nature and will never map natively, so it stays a fixed example of an
    # element layer. Text drawn over it is its own native shape; baking it into the raster too would
    # draw it twice.
    ir = await _render_and_extract(
        "<canvas width='1280' height='720' style='position:absolute;left:0;top:0'></canvas>"
        "<div style='position:absolute;left:100px;top:100px;font-size:96px;font-weight:800;"
        "color:#111'>Overlap</div>"
    )

    pictures = [s for s in ir.shapes if isinstance(s.fill, PictureFill)]
    assert pictures, "the canvas should be an element layer"
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


async def test_child_clipped_by_an_ancestor_is_cropped_to_the_clip_edge() -> None:
    # Half the box sits outside the card's overflow box. PowerPoint cannot clip one shape to
    # another, so the child becomes a free-form path cut at the card edge: nothing paints past it.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "overflow:hidden;background:#eeeeee'>"
        "<div style='position:absolute;left:200px;top:50px;width:200px;height:100px;"
        "background:#cc2200'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    child = _solid_shape(ir, "CC2200")
    assert child.custom_geom is not None
    xs = [
        command.to.x for command in child.custom_geom.path if isinstance(command, LineTo | MoveTo)
    ]
    # The child spans x=300..500 on the slide; the card ends at x=400, 100px into the child.
    assert max(xs) <= px_to_emu(100) + 2


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


type Pixel = tuple[int, int, int, int]


def _probe(data: bytes) -> Callable[[float, float, float], Pixel]:
    """A ``pixel(x, y, scale)`` reader over a PNG, addressed in CSS px."""
    with Image.open(BytesIO(data)) as image:
        width = image.width
        raw = image.convert("RGBA").tobytes()

    def pixel(x: float, y: float, scale: float) -> Pixel:
        offset = (int(y * scale) * width + int(x * scale)) * 4
        return raw[offset], raw[offset + 1], raw[offset + 2], raw[offset + 3]

    return pixel


async def test_backdrop_filter_becomes_a_native_clipped_blur_on_the_sharp_backdrop() -> None:
    # PowerPoint cannot read what is behind a shape, but it can blur a picture itself. The glass's
    # backdrop is a picture shape holding the SHARP pixels with a native a:blur that stays inside
    # the shape; the blurred pixels the browser painted ride along as the owned fallback. The glass
    # (tint, border, text) stays a native shape above it and content below is untouched.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
        "<div style='position:absolute;left:150px;top:120px;width:300px;height:80px;"
        "border-radius:20px;background:rgba(255,255,255,.4);backdrop-filter:blur(6px)'></div>"
        "<div style='position:absolute;left:200px;top:140px;width:60px;height:20px;"
        "background:#000000'></div>"
    )

    [layer] = [
        s
        for s in ir.shapes
        if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
    ]
    assert isinstance(layer.fill, PictureFill)
    # PowerPoint's blur radius is 3x the CSS sigma (measured in real PowerPoint).
    assert layer.effects == (Blur(radius_emu=px_to_emu(6 * 3), grow=False),)
    assert layer.corner_radius_emu == px_to_emu(20) and layer.geom == "roundRect"
    assert layer.box.width == px_to_emu(300) and layer.box.height == px_to_emu(80)

    sharp = _probe(layer.fill.data)  # local frame: x=0 is the glass's left edge (abs 150)
    assert sharp(146, 40, 2)[1] < 60, "left of the red box's edge is still red"
    assert sharp(156, 40, 2)[1] > 200, "right of it is the white page: the edge is sharp"
    assert max(sharp(70, 30, 2)[:3]) > 80, "content painted above the glass is not baked in"

    fallback = layer.portable_fallback
    assert fallback is not None and fallback.picture.raster_role == "portable-blur-fallback"
    baked = _probe(fallback.picture.data)
    assert 90 < baked(150, 40, 2)[1] < 200, "the fallback carries the blurred edge"
    assert baked(0, 0, 2)[3] == 0, "outside the rounded corner stays transparent"

    glass = _solid_shape(ir, "FFFFFF")
    assert glass.fill is not None and not isinstance(glass.fill, PictureFill)
    assert ir.shapes.index(layer) < ir.shapes.index(glass), "the layer sits beneath the glass"
    assert _solid_shape(ir, "CC2200").box.width == px_to_emu(200)


async def test_backdrop_blur_stays_baked_where_a_native_blur_would_not_be_exact() -> None:
    # The native layer is a rounded rectangle blurred at full strength, so a clip-path (it would
    # blur outside the clip) or an element opacity (it would blur at full strength) keeps the
    # browser's own pixels instead.
    behind = (
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
    )
    for extra in ("clip-path:polygon(50% 0, 100% 100%, 0 100%)", "opacity:.4"):
        ir = await _render_and_extract(
            behind + "<div style='position:absolute;left:150px;top:120px;width:300px;height:80px;"
            f"background:rgba(255,255,255,.4);backdrop-filter:blur(6px);{extra}'></div>"
        )

        layers = [
            s
            for s in ir.shapes
            if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
        ]
        assert layers, extra
        assert all(s.effects == () and s.portable_fallback is None for s in layers), extra


async def test_backdrop_blur_round_trips_through_pptx_and_html() -> None:
    glass_html = (
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
        "<div style='position:absolute;left:150px;top:120px;width:300px;height:80px;"
        "border-radius:20px;transform:rotate(-12deg);background:rgba(255,255,255,.4);"
        "backdrop-filter:blur(6px)'></div>"
    )
    first = await _render_and_extract_result(glass_html)

    def backdrop(ir: SlideIR) -> ShapeNode:
        return next(
            s
            for s in ir.shapes
            if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
        )

    layer = backdrop(first.slide)
    assert layer.transform is not None and abs(layer.transform.rotation_deg - 348) < 0.5

    # PPTX -> IR: the blur stays a native, clipped blur on a picture that keeps its role.
    recovered = next(
        s
        for s in read_pptx(build_pptx([first.slide], faces=[]))[0].contents
        if isinstance(s, ShapeNode) and s.effects and isinstance(s.effects[0], Blur)
    )
    assert recovered.effects == layer.effects
    assert (
        isinstance(recovered.fill, PictureFill) and recovered.fill.raster_role == "backdrop-layer"
    )

    # IR -> HTML: a live CSS backdrop filter at the original sigma, not a picture or a filter.
    serialized = inline_assets(serialize_canvas([first.slide]))
    html = serialized.slides[0].html
    assert "backdrop-filter:blur(6px)" in html
    assert "filter:blur" not in html.replace("backdrop-filter:blur", "")

    # ... and that HTML renders back to the same native blur, with the same shapes under the same
    # ids, cycle after cycle: the generated carrier must not be extracted as an extra shape.
    def structure(ir: SlideIR) -> list[tuple[str, str]]:
        return [(s.node_id or "", type(s.fill).__name__) for s in ir.shapes]

    current = first
    for _ in range(3):
        serialized = inline_assets(serialize_canvas([current.slide]))
        current = await _render_and_extract_result(serialized.slides[0].html, css=serialized.css)
        assert backdrop(current.slide).effects == layer.effects
    assert structure(current.slide) == structure(first.slide)


async def test_backdrop_filter_with_a_drop_shadow_keeps_only_the_baked_layer() -> None:
    # A native blur plus colour maths (saturate, brightness) is carried natively; anything that is
    # not (a second blur, a drop shadow) would be lost, so the browser's pixels stay one picture.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#cc2200'></div>"
        "<div style='position:absolute;left:150px;top:120px;width:300px;height:80px;"
        "background:rgba(255,255,255,.4);backdrop-filter:blur(6px) drop-shadow(2px 2px 2px #000)'>"
        "</div>"
    )

    [layer] = [
        s
        for s in ir.shapes
        if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
    ]
    assert layer.effects == () and layer.portable_fallback is None


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


async def test_repeating_stripes_become_one_native_gradient_that_survives_both_ways() -> None:
    # A repeating gradient is one ramp tiled along the gradient line. Over a known box it is a plain
    # many-stop gradient, which PowerPoint renders natively, so nothing needs a raster.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:0;top:0;width:1280px;height:720px;opacity:.58;"
        "background:repeating-linear-gradient(90deg,transparent 0px,transparent 399px,"
        "rgba(24,31,26,.2) 399px,rgba(24,31,26,.2) 400px)'></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    [stripes] = [s for s in ir.shapes if isinstance(s.fill, GradientFill)]
    assert isinstance(stripes.fill, GradientFill)
    assert len(stripes.fill.stops) >= 12
    assert stripes.opacity == 0.58

    # PPTX -> IR: the stops, including the hard edges, survive the file.
    pptx = build_pptx([ir], faces=[])
    [recovered] = [
        s for s in read_pptx(pptx)[0].contents if isinstance(s, ShapeNode) and s.fill is not None
    ][-1:]
    assert isinstance(recovered.fill, GradientFill)
    assert len(recovered.fill.stops) == len(stripes.fill.stops), "no stop multiplication"
    hard_edges = [
        (a, b)
        for a, b in zip(recovered.fill.stops, recovered.fill.stops[1:], strict=False)
        if b.pos - a.pos < 1e-3 and a.color != b.color
    ]
    assert len(hard_edges) >= 3, "the stripe edges stay hard through the PPTX"

    # IR -> HTML: it is written as one CSS gradient, not a picture.
    html = serialize_canvas([ir]).slides[0].html
    assert "linear-gradient(90deg" in html and "<img" not in html


def _run_of(ir: SlideIR, text: str) -> TextRun:
    return next(
        run
        for shape in ir.shapes
        if shape.text is not None
        for paragraph in shape.text.paragraphs
        for run in paragraph.runs
        if text in run.text
    )


async def test_text_gradient_outline_and_shadow_are_native_run_properties_both_ways() -> None:
    # PowerPoint paints a run's gradient fill, outline and drop shadow itself, so CSS gradient text,
    # -webkit-text-stroke and text-shadow need no raster (and must not be silently dropped).
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;font-size:60px;font-weight:800;"
        "background:linear-gradient(90deg,#cc2200,#0088ff);-webkit-background-clip:text;"
        "color:transparent'>Grad</div>"
        "<div style='position:absolute;left:100px;top:250px;font-size:60px;font-weight:800;"
        "color:transparent;-webkit-text-stroke:2px #cc2200'>Line</div>"
        "<div style='position:absolute;left:100px;top:400px;font-size:60px;font-weight:800;"
        "color:#cc2200;text-shadow:4px 4px 6px rgba(0,0,0,.4)'>Shade</div>"
    )

    def check(ir: SlideIR) -> None:
        box = next(
            s
            for s in ir.shapes
            if s.text is not None and "Grad" in s.text.paragraphs[0].runs[0].text
        )
        assert box.fill is None, "background-clip:text paints the glyphs, not the box"
        gradient = _run_of(ir, "Grad")
        assert gradient.gradient is not None and len(gradient.gradient.stops) == 2
        assert gradient.color.hex == "CC2200" and gradient.color.a == 1.0, (
            "first stop is the fallback"
        )
        outline = _run_of(ir, "Line").outline
        assert outline is not None and abs(outline.width_pt - 1.5) < 0.01
        assert outline.color.hex == "CC2200"
        shadow = _run_of(ir, "Shade").shadow
        assert shadow is not None and abs(shadow.blur_emu - px_to_emu(6)) <= 1
        assert abs(shadow.distance_emu - px_to_emu(5.657)) <= px_to_emu(0.1)
        assert abs(shadow.direction_deg - 45) < 0.5

    check(ir)

    # PPTX -> IR: the same properties come back out of the file.
    check(read_pptx(build_pptx([ir], faces=[]))[0])

    # IR -> HTML is real CSS, and rendering it again gives the same runs.
    serialized = inline_assets(serialize_canvas([ir]))
    html = serialized.slides[0].html
    assert "background-clip:text" in html and "-webkit-text-stroke:" in html
    assert "text-shadow:" in html
    check((await _render_and_extract_result(html, css=serialized.css)).slide)


async def test_text_clipped_background_that_a_run_cannot_carry_stays_visible() -> None:
    # A conic gradient clipped to text cannot be a run fill. Dropping the box fill anyway would
    # leave transparent text on nothing, so it must keep its raster instead of disappearing.
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;font-size:80px;font-weight:800;"
        "background:conic-gradient(red,blue,red);-webkit-background-clip:text;"
        "color:transparent'>Conic</div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_text_fill_colour_overrides_color_for_the_glyph_interior() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;font-size:80px;font-weight:800;"
        "color:#cc2200;-webkit-text-fill-color:transparent;-webkit-text-stroke:2px #0000ff'>"
        "Hollow</div>"
    )

    run = _run_of(ir, "Hollow")
    assert run.color.a == 0.0, "Chromium paints no interior, so neither may the PPTX"
    assert run.outline is not None and run.outline.color.hex == "0000FF"


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


async def test_colour_filter_on_a_leaf_is_folded_into_its_fill_without_a_raster() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:100px;"
        "background:#ff0000;filter:grayscale(1)'></div>"
    )

    shape = next(s for s in ir.shapes if isinstance(s.fill, SolidFill))
    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert shape.fill.color.r == shape.fill.color.g == shape.fill.color.b  # type: ignore[union-attr]


async def test_colour_filter_on_a_parent_keeps_its_raster() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:100px;"
        "filter:sepia(1)'><div style='width:50px;height:50px;background:red'></div></div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_conic_and_layered_backgrounds_become_editable_shapes() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:200px;"
        "background:conic-gradient(red,blue,red)'></div>"
        "<div style='position:absolute;left:300px;top:50px;width:200px;height:200px;"
        "background:linear-gradient(90deg,rgba(255,0,0,.5),transparent),"
        "linear-gradient(0deg,blue,green)'></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _layer_count(ir) >= 3


async def test_off_centre_elliptical_radial_gradient_becomes_banded_shapes() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:360px;height:220px;"
        "background:radial-gradient(ellipse at 30% 40%,#f80,#306)'></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert _layer_count(ir) >= 24


def _layer_count(ir: SlideIR) -> int:
    return sum(
        1
        for s in ir.shapes
        if s.provenance is not None and (s.provenance.role or "").startswith("layer-")
    )


_BOX = "position:absolute;left:50px;top:50px;width:200px;height:100px;"


@pytest.mark.parametrize(
    "style",
    [
        "background:red;mask-image:linear-gradient(90deg,black,transparent)",
        "background:radial-gradient(circle at 30% 40%,rgba(255,0,0,.5),rgba(0,0,255,.5))",
        "background:linear-gradient(red,blue) 0 0/20px 20px,linear-gradient(blue,red)",
        "background:conic-gradient(red,blue,red);transform:rotate(20deg)",
        "background:url(data:image/gif;base64,R0lGODlhAQABAAAAACw=);filter:grayscale(1)",
    ],
)
async def test_unsafe_lowerings_stay_raster(style: str) -> None:
    text = "Hi" if "mask-image" in style else ""
    ir = await _render_and_extract(f"<div style='{_BOX}{style}'>{text}</div>")

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_brightness_on_a_gradient_keeps_the_clamped_ramp() -> None:
    ir = await _render_and_extract(
        f"<div style='{_BOX}background:linear-gradient(90deg,#000,#fff);"
        "filter:brightness(2)'></div>"
    )

    gradient = next(s.fill for s in ir.shapes if isinstance(s.fill, GradientFill))
    middle = min(gradient.stops, key=lambda stop: abs(stop.pos - 0.75))
    assert middle.color.hex == "FFFFFF"


async def test_text_drop_shadow_reaches_every_run() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;font-size:40px;"
        "filter:drop-shadow(4px 4px 2px #000)'>Hello</div>"
    )

    runs = [r for s in ir.shapes if s.text for p in s.text.paragraphs for r in p.runs]
    assert runs and all(r.shadow is not None for r in runs)


_CANVAS = (
    "<canvas id='c' width='360' height='220' style='position:absolute;left:50px;top:50px'>"
    "</canvas><script>const x=document.getElementById('c').getContext('2d');"
    "const g=x.createLinearGradient(0,0,360,0);g.addColorStop(0,'#f80');g.addColorStop(1,'#306');"
    "x.fillStyle=g;x.fillRect(0,0,360,220);x.save();x.translate(180,110);x.rotate(.3);"
    "x.fillStyle='#fff';x.beginPath();x.arc(0,0,60,0,Math.PI*1.5);x.lineTo(0,0);x.fill();"
    "x.restore();x.font='bold 28px sans-serif';x.fillText('Canvas',20,200);</script>"
)


async def test_recorded_canvas_becomes_a_vector_picture_in_both_formats() -> None:
    ir = await _render_and_extract(_CANVAS)

    picture = next(s.fill for s in ir.shapes if isinstance(s.fill, PictureFill))
    assert picture.svg_data is not None and b"<path" in picture.svg_data
    assert b"<text" in picture.svg_data and b"linearGradient" in picture.svg_data

    # IR -> PPTX -> IR keeps the vector next to its PNG fallback.
    again = read_pptx(build_pptx([ir], faces=[]))[0]
    assert any(isinstance(s.fill, PictureFill) and s.fill.svg_data for s in again.shapes)

    # IR -> HTML ships the vector as an asset.
    assert any(asset.path.endswith(".svg") for asset in serialize_canvas([ir]).assets)


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ("x.fillStyle=x.createPattern(x,'repeat');x.fillRect(0,0,50,50)", "createPattern"),
        ("x.fillRect(0,0,50,50);x.clearRect(5,5,10,10)", "partial clearRect"),
        ("x.globalCompositeOperation='multiply';x.fillRect(0,0,50,50)", "globalComposite"),
    ],
)
async def test_unrecordable_canvas_stays_raster_with_its_reason(script: str, reason: str) -> None:
    result = await _render_and_extract_result(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px'>"
        f"</canvas><script>const x=document.getElementById('c').getContext('2d');{script}</script>"
    )

    assert any(
        reason in (item.reason or "") and item.representation.value != "native"
        for item in result.coverage
    )


async def test_redrawing_a_canvas_keeps_only_the_current_frame() -> None:
    ir = await _render_and_extract(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px'>"
        "</canvas><script>const x=document.getElementById('c').getContext('2d');"
        "for(let i=0;i<5;i++){x.clearRect(0,0,100,100);x.fillStyle='#0f0';x.fillRect(i,0,20,20)}"
        "</script>"
    )

    assert len([s for s in ir.shapes if s.custom_geom is not None]) == 1


async def test_canvas_keeps_its_css_presentation() -> None:
    ir = await _render_and_extract(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px;"
        "opacity:.5;transform:rotate(20deg);border:4px solid #f00;border-radius:12px'>"
        "</canvas><script>document.getElementById('c').getContext('2d').fillRect(0,0,50,50)"
        "</script>"
    )

    shape = next(s for s in ir.shapes if isinstance(s.fill, PictureFill) and s.fill.svg_data)
    assert shape.transform is not None
    assert shape.line is not None or any(s.line is not None for s in ir.shapes)


async def test_draw_image_does_not_recurse_through_the_recorder() -> None:
    ir = await _render_and_extract(
        "<canvas id='src' width='20' height='20'></canvas>"
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px'>"
        "</canvas><script>const s=document.getElementById('src').getContext('2d');"
        "s.fillStyle='#f00';s.fillRect(0,0,20,20);"
        "document.getElementById('c').getContext('2d').drawImage(document.getElementById('src'),5,5)"
        "</script>"
    )

    drawn = [
        s.fill.svg_data
        for s in ir.shapes
        if isinstance(s.fill, PictureFill) and s.fill.svg_data and b"<image" in s.fill.svg_data
    ]
    assert len(drawn) == 1 and drawn[0].count(b"<image") == 1


async def test_resizing_a_canvas_forgets_the_open_path() -> None:
    result = await _render_and_extract(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px'>"
        "</canvas><script>const k=document.getElementById('c'),x=k.getContext('2d');"
        "x.rect(10,10,20,20);k.width=100;x.fill();x.fillStyle='#0f0';x.fillRect(0,0,5,5)</script>"
    )

    assert len([s for s in result.shapes if s.custom_geom is not None]) == 1


_SVG_BOX = "position:absolute;left:50px;top:50px;width:200px;height:200px;"


@pytest.mark.parametrize(
    ("body", "count"),
    [
        ("<path d='M10 10H50V50H10Z' fill='#c20'/><path d='M55 55H95V95H55Z' fill='#08f'/>", 2),
        (
            "<defs><linearGradient id='g'><stop offset='0' stop-color='#c20'/>"
            "<stop offset='1' stop-color='#08f'/></linearGradient></defs>"
            "<path d='M10 10H90V90H10Z' fill='url(#g)'/>",
            1,
        ),
        ("<path d='M10 50H90' stroke='#c20' stroke-width='6' stroke-dasharray='10 4 2 4'/>", 1),
        (
            "<g transform='translate(10 10)' opacity='.5'><circle cx='30' cy='30' r='20' "
            "fill='#c20'/><rect x='5' y='5' width='20' height='10' rx='3' fill='#08f'/>"
            "<polyline points='0,0 40,40 80,0' fill='none' stroke='#000' stroke-width='2'/></g>",
            3,
        ),
    ],
)
async def test_svg_becomes_editable_shapes_in_both_directions(body: str, count: int) -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>{body}</svg>"
    )

    shapes = [s for s in result.slide.shapes if s.custom_geom is not None]
    assert len(shapes) == count
    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    assert all(item.representation.value in ("native", "decomposed") for item in result.coverage)

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert len([s for s in again.shapes if s.custom_geom is not None]) == count
    html = serialize_canvas([again]).slides[0].html
    reloaded = await _render_and_extract(html)
    assert not any(isinstance(s.fill, PictureFill) for s in reloaded.shapes)


async def test_svg_dash_pattern_and_gradient_are_exact_natives() -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'><stop offset='0' "
        "stop-color='#ff0000'/><stop offset='1' stop-color='#0000ff'/></linearGradient></defs>"
        "<rect x='10' y='10' width='80' height='30' fill='url(#g)'/>"
        "<path d='M10 70H90' stroke='#000' stroke-width='4' stroke-dasharray='8 4 2 4'/></svg>"
    )

    gradient = next(s.fill for s in result.slide.shapes if isinstance(s.fill, GradientFill))
    assert abs(gradient.angle_deg - 180.0) < 0.5  # top to bottom
    dashed = next(s.line for s in result.slide.shapes if s.line is not None)
    assert dashed is not None and dashed.custom_dash == (2.0, 1.0, 0.5, 1.0)
    data = build_pptx([result.slide], faces=[])
    with ZipFile(BytesIO(data)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    assert '<a:ds d="200000" sp="100000"/>' in xml
    again = [s.line for s in read_pptx(data)[0].shapes if s.line is not None]
    assert again[0] is not None and again[0].custom_dash == (2.0, 1.0, 0.5, 1.0)


async def test_svg_with_tspans_or_markers_stays_a_vector_picture() -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>"
        "<path d='M10 10H50V50H10Z' fill='#c20'/>"
        "<text x='10' y='80' font-size='20'><tspan>Hi</tspan>"
        "<tspan dy='5'>there</tspan></text></svg>"
    )

    pictures = [s.fill for s in result.slide.shapes if isinstance(s.fill, PictureFill)]
    assert pictures and pictures[0].svg_data is not None
    assert all(item.representation.value == "native" for item in result.coverage)


async def test_svg_and_canvas_text_become_editable_text_boxes_at_their_baseline() -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 200 200'>"
        "<text x='100' y='60' font-size='24' font-weight='700' font-family='Arial' "
        "text-anchor='middle' fill='#cc2200'>Centred</text>"
        "<text x='10' y='150' font-size='16' font-style='italic' fill='#0044cc'>Left</text></svg>"
        "<canvas id='c' width='200' height='100' style='position:absolute;left:300px;top:50px'>"
        "</canvas><script>const x=document.getElementById('c').getContext('2d');"
        "x.font='bold 30px sans-serif';x.fillStyle='#008800';x.fillText('Canvas',10,60)</script>"
    )

    texts = {
        s.text.paragraphs[0].runs[0].text: s
        for s in result.slide.shapes
        if s.text and s.text.paragraphs
    }
    assert set(texts) == {"Centred", "Left", "Canvas"}
    centred = texts["Centred"].text
    assert centred is not None and centred.paragraphs[0].align == "center"
    run = centred.paragraphs[0].runs[0]
    assert run.bold and run.color.hex == "CC2200" and abs(run.size_pt - 18.0 * 1.0) < 6
    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert {r.text for s in again.shapes if s.text for p in s.text.paragraphs for r in p.runs} == {
        "Centred",
        "Left",
        "Canvas",
    }


async def test_svg_text_keeps_offsets_and_spacing_and_refuses_what_it_cannot_place() -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 200 200'>"
        "<text x='10' y='50' dy='40' font-size='20' letter-spacing='3'>Spaced</text></svg>"
    )
    shape = next(s for s in result.slide.shapes if s.text and s.text.paragraphs)
    run = shape.text.paragraphs[0].runs[0]  # type: ignore[union-attr]
    assert run.letter_spacing_pt > 1.0
    plain = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 200 200'>"
        "<text x='10' y='50' font-size='20' letter-spacing='3'>Spaced</text></svg>"
    )
    base = next(s for s in plain.slide.shapes if s.text and s.text.paragraphs)
    assert shape.box.y - base.box.y > 0

    for bad in (
        "<text x='10' y='50' font-size='20' transform='scale(-1,1)'>Mirror</text>",
        "<text x='10' y='50' font-size='20' transform='rotate(180 50 50)'>Flip</text>",
        "<text x='10 40 70' y='50' font-size='20'>Spread</text>",
    ):
        out = await _render_and_extract_result(
            f"<svg style='{_SVG_BOX}' viewBox='0 0 200 200'>{bad}</svg>"
        )
        assert not any(s.text for s in out.slide.shapes)


@pytest.mark.parametrize(
    "extra",
    [
        "<defs><filter id='f'><feTurbulence baseFrequency='.05'/></filter></defs>"
        "<path d='M10 10H90V90H10Z' fill='#c20' filter='url(#f)'/>",
        "<image href='https://example.com/a.png' width='50' height='50'/>"
        "<path d='M10 10H50V50H10Z' fill='#c20'/><path d='M60 60H90V90H60Z' fill='#08f'/>",
    ],
)
async def test_svg_a_renderer_would_draw_wrongly_keeps_its_raster(extra: str) -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>{extra}</svg>"
    )

    pictures = [s.fill for s in result.slide.shapes if isinstance(s.fill, PictureFill)]
    assert pictures and all(p.svg_data is None for p in pictures)


@pytest.mark.parametrize(
    "html",
    [
        "<svg style='{box}filter:blur(3px)' viewBox='0 0 100 100'>{two}</svg>",
        "<div style='transform:rotate(15deg);position:absolute;left:0;top:0'>"
        "<svg style='{box}' viewBox='0 0 100 100'>{two}</svg></div>",
        "<svg style='{box}' viewBox='0 0 100 100'>"
        "<path d='M10 10H50V50H10Z' fill='url(https://example.com/p.svg#p)'/>"
        "<path d='M60 60H90V90H60Z' fill='#08f'/></svg>",
        "<style>.h{{display:none}}</style><svg style='{box}' viewBox='0 0 100 100'>{two}"
        "<path class='h' d='M0 0H9V9H0Z' fill='red'/></svg>",
    ],
)
async def test_svg_whose_effects_a_standalone_file_would_lose_keeps_its_raster(html: str) -> None:
    two = "<path d='M10 10H50V50H10Z' fill='#c20'/><path d='M55 55H95V95H55Z' fill='#08f'/>"
    result = await _render_and_extract_result(
        html.format(box=_SVG_BOX.replace("left:50px;top:50px", "left:150px;top:150px"), two=two)
    )

    pictures = [s.fill for s in result.slide.shapes if isinstance(s.fill, PictureFill)]
    assert pictures and all(p.svg_data is None for p in pictures)


_CLIP_BOX = "position:absolute;left:100px;top:80px;width:360px;height:220px;background:#c20;"


@pytest.mark.parametrize(
    "clip",
    [
        "circle(50%)",
        "circle(40% at 30% 40%)",
        "ellipse(40% 30% at 50% 50%)",
        "inset(10% 20% 10% 20% round 16px)",
        "polygon(0 0,100% 20%,80% 100%,10% 80%)",
    ],
)
async def test_clip_path_shapes_become_native_geometry_and_round_trip(clip: str) -> None:
    ir = await _render_and_extract(f"<div style='{_CLIP_BOX}clip-path:{clip}'></div>")

    shapes = [s for s in ir.shapes if isinstance(s.fill, SolidFill)]
    assert len(shapes) == 1 and not any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert shapes[0].custom_geom is not None

    again = read_pptx(build_pptx([ir], faces=[]))[0]
    assert any(s.custom_geom is not None for s in again.shapes)

    html = inline_assets(serialize_canvas([ir])).slides[0].html
    reloaded = await _render_and_extract(html)
    assert not any(isinstance(s.fill, PictureFill) for s in reloaded.shapes)


async def test_circle_clip_on_a_square_is_the_ellipse_preset() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:200px;height:200px;"
        "background:#c20;clip-path:circle(50%)'></div>"
    )

    [shape] = [s for s in ir.shapes if isinstance(s.fill, SolidFill)]
    assert shape.geom == "ellipse" and shape.custom_geom is None


@pytest.mark.parametrize(
    "extra", ["border:4px solid #000;", "box-shadow:0 4px 8px #000;", "color:#fff;"]
)
async def test_clip_path_with_content_the_clip_would_hide_keeps_its_raster(extra: str) -> None:
    text = "Hi" if "color" in extra else ""
    ir = await _render_and_extract(
        f"<div style='{_CLIP_BOX}{extra}clip-path:circle(40%)'>{text}</div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_flipped_text_is_mirrored_by_the_text_body_not_a_raster() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:120px;"
        "background:#c20;color:#fff;font-size:40px;transform:scaleX(-1)'>Mirror</div>"
    )

    [shape] = [s for s in ir.shapes if s.text is not None]
    assert shape.transform is not None and shape.transform.flip_h
    assert shape.text is not None and shape.text.mirror_x
    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)

    # PPTX carries the mirror as a text-body 3-D turn, and reads it back.
    data = build_pptx([ir], faces=[])
    again = next(s for s in read_pptx(data)[0].shapes if s.text is not None)
    assert again.text is not None and again.text.mirror_x

    # HTML leaves the text mirrored with its element (no counter-flip), as authored.
    html = inline_assets(serialize_canvas([ir])).slides[0].html
    assert html.count("scaleX(-1)") == 1


async def test_a_flipped_shape_with_readable_text_counter_mirrors_in_html() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:120px;"
        "background:#c20;color:#fff;font-size:40px;transform:scaleX(-1)'>Mirror</div>"
    )
    [shape] = [s for s in ir.shapes if s.text is not None]
    assert shape.text is not None
    readable = shape.model_copy(update={"text": shape.text.model_copy(update={"mirror_x": False})})
    html = inline_assets(serialize_canvas([ir.model_copy(update={"contents": (readable,)})]))

    assert html.slides[0].html.count("scaleX(-1)") == 2


_PLAIN_BOX = "position:absolute;left:100px;top:80px;width:360px;height:220px;background:#c20;"


async def test_skewed_and_perspective_boxes_become_native_quads() -> None:
    for transform in ("skewX(-15deg)", "perspective(600px) rotateY(35deg)"):
        ir = await _render_and_extract(f"<div style='{_PLAIN_BOX}transform:{transform}'></div>")

        [shape] = [s for s in ir.shapes if isinstance(s.fill, SolidFill)]
        assert shape.custom_geom is not None and shape.transform is None
        assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_skewed_box_with_content_keeps_its_raster() -> None:
    ir = await _render_and_extract(
        f"<div style='{_PLAIN_BOX}transform:skewX(-15deg);color:#fff'>Skew</div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_children_cut_by_an_overflow_hidden_ancestor_become_cropped_shapes() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:220px;"
        "overflow:hidden;background:#eee;border-radius:24px'>"
        "<div style='position:absolute;left:250px;top:40px;width:200px;height:100px;"
        "background:#c20'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    cropped = [s for s in result.slide.shapes if s.custom_geom is not None]
    assert len(cropped) == 1
    assert all(item.representation.value == "native" for item in result.coverage)


async def test_overflow_cropped_text_keeps_its_raster() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:200px;height:100px;"
        "overflow:hidden'><div style='position:absolute;left:150px;top:10px;font-size:30px;"
        "white-space:nowrap'>Cut off text</div></div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_clipped_gradient_survives_the_html_round_trip() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:220px;"
        "background:linear-gradient(90deg,#c20,#08f);clip-path:inset(10% 20% 10% 20%)'></div>"
    )
    [shape] = [s for s in ir.shapes if s.custom_geom is not None]
    assert isinstance(shape.fill, GradientFill)

    html = inline_assets(serialize_canvas([ir])).slides[0].html
    assert "clip-path:polygon(" in html and "linear-gradient" in html
    reloaded = await _render_and_extract(html)
    again = [s for s in reloaded.shapes if s.custom_geom is not None]
    assert len(again) == 1 and isinstance(again[0].fill, GradientFill)


async def test_skew_of_a_rounded_or_clipped_box_keeps_its_raster() -> None:
    for extra in ("border-radius:24px;", "clip-path:circle(40%);"):
        ir = await _render_and_extract(
            f"<div style='{_PLAIN_BOX}{extra}transform:skewX(-15deg)'></div>"
        )

        assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_readable_text_in_a_flipped_shape_survives_html_and_back() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:120px;"
        "background:#c20;color:#fff;font-size:40px;transform:scaleX(-1)'>Mirror</div>"
    )
    [shape] = [s for s in ir.shapes if s.text is not None]
    assert shape.text is not None
    readable = shape.model_copy(update={"text": shape.text.model_copy(update={"mirror_x": False})})
    html = inline_assets(serialize_canvas([ir.model_copy(update={"contents": (readable,)})]))
    reloaded = await _render_and_extract(html.slides[0].html)

    [again] = [s for s in reloaded.shapes if s.text is not None]
    assert again.text is not None and not again.text.mirror_x


async def test_a_clip_path_shape_cut_by_an_overflow_ancestor_keeps_its_raster() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:200px;"
        "overflow:hidden'><div style='position:absolute;left:100px;top:50px;width:200px;"
        "height:200px;background:#c20;clip-path:circle(50%)'></div></div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)


async def test_box_reflect_with_implicit_stops_becomes_a_native_reflection() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:120px;"
        "background:#c20;-webkit-box-reflect:below 6px "
        "linear-gradient(transparent,rgba(0,0,0,.4))'></div>"
    )

    shape = next(s for s in result.slide.shapes if isinstance(s.fill, SolidFill))
    assert any(effect.kind == "reflection" for effect in shape.effects)
    assert all(item.representation.value != "element_layer" for item in result.coverage)


async def test_backdrop_saturate_recolours_the_sharp_backdrop_under_a_native_blur() -> None:
    plain = await _render_and_extract(_GLASS.format(filter="blur(6px)"))
    saturated = await _render_and_extract(_GLASS.format(filter="blur(6px) saturate(180%)"))

    def backdrop(ir: SlideIR) -> PictureFill:
        return next(
            s.fill
            for s in ir.shapes
            if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
        )

    layer = next(
        s
        for s in saturated.shapes
        if isinstance(s.fill, PictureFill) and s.fill.raster_role == "backdrop-layer"
    )
    assert any(isinstance(effect, Blur) for effect in layer.effects)
    assert backdrop(saturated).data != backdrop(plain).data


_GLASS = (
    "<div style='position:absolute;left:0;top:0;width:1280px;height:720px;"
    "background:linear-gradient(135deg,#f80,#306 60%,#08f)'></div>"
    "<div style='position:absolute;left:140px;top:120px;width:380px;height:260px;"
    "background:rgba(255,255,255,.25);backdrop-filter:{filter}'></div>"
)


async def test_svg_gaussian_blur_filter_becomes_a_native_blur_scaled_to_the_box() -> None:
    result = await _render_and_extract_result(
        "<svg style='position:absolute;left:100px;top:100px;width:360px;height:220px' "
        "viewBox='0 0 100 100'><defs><filter id='f'><feGaussianBlur stdDeviation='3'/></filter>"
        "</defs><path d='M10 10H90V90H10Z' fill='#c20' filter='url(#f)'/></svg>"
    )

    shape = next(s for s in result.slide.shapes if s.custom_geom is not None)
    [blur] = [effect for effect in shape.effects if isinstance(effect, Blur)]
    # 3 user units at the SVG's uniform scale (the smaller of 3.6 and 2.2 px per unit).
    assert abs(blur.radius_emu - px_to_emu(3 * 2.2)) < px_to_emu(0.2)


async def test_svg_geometry_keeps_its_aspect_ratio_inside_a_wider_box() -> None:
    ir = await _render_and_extract(
        "<svg style='position:absolute;left:100px;top:100px;width:360px;height:220px' "
        "viewBox='0 0 100 100'><path d='M0 0H100V100H0Z' fill='#c20'/></svg>"
    )

    shape = next(s for s in ir.shapes if s.custom_geom is not None)
    assert shape.custom_geom is not None
    xs = [c.to.x for c in shape.custom_geom.path if isinstance(c, LineTo | MoveTo)]
    ys = [c.to.y for c in shape.custom_geom.path if isinstance(c, LineTo | MoveTo)]
    # The browser draws a 220px square centred in the 360px width, not a stretched rectangle.
    tolerance = px_to_emu(1)
    assert abs(max(xs) - min(xs) - px_to_emu(220)) < tolerance
    assert abs(min(xs) - px_to_emu(70)) < tolerance
    assert abs(max(ys) - min(ys) - px_to_emu(220)) < tolerance


@pytest.mark.parametrize(
    "filter_markup",
    [
        "<filter id='f' primitiveUnits='objectBoundingBox'><feGaussianBlur stdDeviation='.05'/>"
        "</filter>",
        "<filter id='f'><feGaussianBlur stdDeviation='1e309'/></filter>",
    ],
)
async def test_svg_blur_that_is_not_a_plain_user_unit_length_keeps_its_raster(
    filter_markup: str,
) -> None:
    result = await _render_and_extract_result(
        "<svg style='position:absolute;left:100px;top:100px;width:220px;height:220px' "
        f"viewBox='0 0 100 100'><defs>{filter_markup}</defs>"
        "<path d='M10 10H90V90H10Z' fill='#c20' filter='url(#f)'/></svg>"
    )

    assert not any(isinstance(e, Blur) for s in result.slide.shapes for e in s.effects)


async def test_a_css_filter_overriding_the_svg_filter_attribute_is_not_replaced_by_a_blur() -> None:
    result = await _render_and_extract_result(
        "<svg style='position:absolute;left:100px;top:100px;width:220px;height:220px' "
        "viewBox='0 0 100 100'><defs><filter id='f'><feGaussianBlur stdDeviation='3'/></filter>"
        "</defs><path d='M10 10H90V90H10Z' fill='#c20' filter='url(#f)' "
        "style='filter:brightness(2)'/></svg>"
    )

    assert not any(isinstance(e, Blur) for s in result.slide.shapes for e in s.effects)


_MP4 = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDE="
_MP3 = "data:audio/mpeg;base64,SUQzBAAAAAAA"
_YOUTUBE = "https://www.youtube.com/embed/dQw4w9WgXcQ?feature=oembed"


def _media(ir: SlideIR) -> MediaNode:
    return next(node for node in ir.contents if isinstance(node, MediaNode))


async def test_video_audio_and_online_players_become_native_media_clips() -> None:
    result = await _render_and_extract_result(
        f"<video src='{_MP4}' style='position:absolute;left:50px;top:50px;width:320px;"
        "height:180px'></video>"
        f"<audio controls src='{_MP3}' style='position:absolute;left:400px;top:50px'></audio>"
        f"<iframe src='{_YOUTUBE}' style='position:absolute;left:50px;top:300px;width:320px;"
        "height:180px;border:0'></iframe>"
    )

    clips = [node for node in result.slide.contents if isinstance(node, MediaNode)]
    assert {(clip.kind, clip.media_data is not None, clip.media_url) for clip in clips} >= {
        ("video", True, None),
        ("video", False, _YOUTUBE),
    }
    assert all(item.representation.value == "native" for item in result.coverage)
    assert not any(
        isinstance(s.fill, PictureFill) and s.fill.raster_role for s in result.slide.shapes
    )


async def test_media_clips_round_trip_through_pptx_and_html() -> None:
    ir = await _render_and_extract(
        f"<video src='{_MP4}' style='position:absolute;left:50px;top:50px;width:320px;"
        "height:180px'></video>"
        f"<iframe src='{_YOUTUBE}' style='position:absolute;left:50px;top:300px;width:320px;"
        "height:180px;border:0'></iframe>"
    )

    data = build_pptx([ir], faces=[])
    again = read_pptx(data)[0]
    clips = [node for node in again.contents if isinstance(node, MediaNode)]
    assert len(clips) == 2
    embedded = next(clip for clip in clips if clip.media_data is not None)
    assert embedded.media_data == _media(ir).media_data or embedded.media_ext == "mp4"
    online = next(clip for clip in clips if clip.media_url is not None)
    assert online.media_url == _YOUTUBE

    html = inline_assets(serialize_canvas([again])).slides[0].html
    assert "<iframe" in html and "youtube.com/embed" in html and "<video" in html
    reloaded = await _render_and_extract(html)
    assert sum(isinstance(node, MediaNode) for node in reloaded.contents) >= 1


async def test_an_iframe_that_is_not_an_online_video_keeps_its_raster() -> None:
    ir = await _render_and_extract(
        "<iframe srcdoc='<h1>hi</h1>' style='position:absolute;left:50px;top:50px;width:320px;"
        "height:180px'></iframe>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert not any(isinstance(node, MediaNode) for node in ir.contents)


async def test_two_identical_clips_share_one_part_and_both_export() -> None:
    clip = (
        f"<video src='{_MP4}' style='position:absolute;left:{{x}}px;top:50px;width:200px;"
        "height:120px'></video>"
    )
    ir = await _render_and_extract(clip.format(x=50) + clip.format(x=300))

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        parts = [name for name in package.namelist() if name.startswith("ppt/media/media")]
    assert len(parts) == 1
    assert sum(isinstance(node, MediaNode) for node in read_pptx(data)[0].contents) == 2


async def test_media_clipped_by_an_ancestor_or_off_the_slide_keeps_a_whole_poster() -> None:
    clipped = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:150px;height:100px;"
        "overflow:hidden'>"
        f"<video src='{_MP4}' style='position:absolute;left:80px;top:10px;width:200px;"
        "height:120px'></video></div>"
    )
    assert not any(isinstance(node, MediaNode) for node in clipped.contents)
    assert any(isinstance(s.fill, PictureFill) for s in clipped.shapes)

    off_slide = await _render_and_extract(
        f"<video src='{_MP4}' style='position:absolute;left:-60px;top:50px;width:200px;"
        "height:120px'></video>"
    )
    clip = _media(off_slide)
    assert clip.poster_fill is not None
    with Image.open(BytesIO(clip.poster_fill.data)) as poster:
        assert abs(poster.width / poster.height - 200 / 120) < 0.02


async def test_media_identity_and_play_settings_survive_the_pptx_round_trip() -> None:
    ir = await _render_and_extract(
        f"<video id='intro' src='{_MP4}' style='position:absolute;left:50px;top:50px;width:200px;"
        "height:120px'></video>"
    )
    clip = _media(ir)
    settings = (
        '<p:videoPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'autoplay="1"/>'
    )
    tagged = ir.model_copy(
        update={"contents": (clip.model_copy(update={"play_settings_xml": settings}),)}
    )

    again = _media(read_pptx(build_pptx([tagged], faces=[]))[0])
    assert again.play_settings_xml is not None and "autoplay" in again.play_settings_xml
    assert again.node_id == clip.node_id and again.provenance is not None


async def test_alt_text_survives_html_to_pptx_to_html() -> None:
    ir = await _render_and_extract(
        "<div role='img' aria-label='Quarterly revenue bars' style='position:absolute;left:50px;"
        "top:50px;width:200px;height:100px;background:#c20'></div>"
        "<img alt='A red square' src='data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA='"
        " style='position:absolute;left:300px;top:50px;width:100px;height:100px'>"
        "<svg role='img' viewBox='0 0 10 10' style='position:absolute;left:450px;top:50px;"
        "width:100px;height:100px'><title>A tiny path</title><path d='M0 0H10V10Z' fill='red'/>"
        "</svg>"
    )

    described = {s.alt_text for s in ir.shapes if s.alt_text}
    assert {"Quarterly revenue bars", "A red square", "A tiny path"} <= described

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode()
    assert 'descr="Quarterly revenue bars"' in slide_xml and 'descr="A red square"' in slide_xml

    again = read_pptx(data)[0]
    assert {s.alt_text for s in again.shapes if s.alt_text} == described
    html = inline_assets(serialize_canvas([again])).slides[0].html
    assert 'aria-label="A red square"' in html


async def test_speaker_notes_round_trip_html_pptx_html() -> None:
    html = (
        "<div class='domoxml-slide' data-notes='Open with the headline.&#10;Pause here.&#10;&#10;"
        "Then the demo.' style='position:relative;width:960px;height:540px'>"
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:100px;"
        "background:#c20'></div></div>"
    )
    ir = await _render_and_extract(html)
    assert ir.notes == "Open with the headline.\nPause here.\n\nThen the demo."

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        names = set(package.namelist())
        assert {"ppt/notesSlides/notesSlide1.xml", "ppt/notesMasters/notesMaster1.xml"} <= names
        assert "Open with the headline." in package.read("ppt/notesSlides/notesSlide1.xml").decode()
        assert "notesMasterIdLst" in package.read("ppt/presentation.xml").decode()

    again = read_pptx(data)[0]
    assert again.notes == ir.notes
    serialized = serialize_canvas([again]).slides[0].html
    assert "data-notes=" in serialized and "Pause here." in serialized


async def test_slides_without_notes_write_no_notes_parts() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:100px;"
        "background:#c20'></div>"
    )

    assert ir.notes is None
    with ZipFile(BytesIO(build_pptx([ir], faces=[]))) as package:
        assert not [n for n in package.namelist() if "notes" in n.lower()]


async def test_notes_normalise_line_endings_and_keep_line_breaks() -> None:
    from domoxml.slides.notes import notes_slide_xml

    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:200px;height:100px;"
        "background:#c20'></div>"
    )
    data = build_pptx([ir.model_copy(update={"notes": "First\r\nSecond\rThird"})], faces=[])
    assert read_pptx(data)[0].notes == "First\nSecond\nThird"

    with_break = notes_slide_xml("x").replace(
        "<a:t>x</a:t></a:r>", "<a:t>one</a:t></a:r><a:br/><a:r><a:t>two</a:t></a:r>"
    )
    with ZipFile(BytesIO(data)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    parts["ppt/notesSlides/notesSlide1.xml"] = with_break.encode()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as target:
        for name, content in parts.items():
            target.writestr(name, content)
    assert read_pptx(buffer.getvalue())[0].notes == "one\ntwo"


async def test_pseudo_elements_become_real_shapes_and_text() -> None:
    ir = await _render_and_extract(
        "<style>.card::before{content:'';position:absolute;left:10px;top:10px;width:80px;"
        "height:60px;background:#cc2200}"
        ".card::after{content:' - ' attr(data-tag) ' \\201C';color:#0044cc;font-size:24px}"
        ".none::before{content:none;background:#00ff00;width:50px;height:50px}</style>"
        "<div class='card' data-tag='new' style='position:absolute;left:50px;top:50px;"
        "width:300px;height:200px;background:#eeeeee;font-size:24px'>Title</div>"
        "<div class='none' style='position:absolute;left:400px;top:50px;width:50px;"
        "height:50px'></div>"
    )

    badge = _solid_shape(ir, "CC2200")
    assert badge.box.width == px_to_emu(80) and badge.box.height == px_to_emu(60)
    texts = " ".join(
        run.text for s in ir.shapes if s.text for p in s.text.paragraphs for run in p.runs
    )
    assert "Title" in texts and "- new" in texts and "“" in texts
    assert not any(
        isinstance(s.fill, SolidFill) and s.fill.color.hex == "00FF00" for s in ir.shapes
    )


async def test_counters_and_images_in_generated_content_are_left_alone() -> None:
    ir = await _render_and_extract(
        "<style>.c{counter-reset:n}.c li{counter-increment:n}"
        ".c li::before{content:counter(n) '. '}</style>"
        "<ol class='c' style='position:absolute;left:50px;top:50px;list-style:none;"
        "font-size:24px'><li>One</li><li>Two</li></ol>"
    )

    texts = " ".join(
        run.text for s in ir.shapes if s.text for p in s.text.paragraphs for run in p.runs
    )
    assert "One" in texts and "Two" in texts


_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_ancestor_opacity_reaches_children_text_borders_and_pictures() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:400px;height:300px;opacity:.5;"
        "background:#eeeeee'><div style='width:100px;height:60px;background:#cc2200;"
        "border:4px solid #000000'></div><p style='margin:0;color:#0000ff;font-size:30px'>Faded</p>"
        f"<img alt='' src='{_PNG}' "
        "style='width:50px;height:50px'></div>"
    )

    red = _solid_shape(ir, "CC2200")
    assert red.opacity == 0.5
    assert red.line is not None and red.line.color.a == 0.5
    text = next(s for s in ir.shapes if s.text and "Faded" in s.text.paragraphs[0].runs[0].text)
    assert text.text is not None and text.text.paragraphs[0].runs[0].color.a == 0.5
    picture = next(s for s in ir.shapes if isinstance(s.fill, PictureFill))
    assert picture.opacity == 0.5

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        assert 'alphaModFix amt="50000"' in package.read("ppt/slides/slide1.xml").decode()
    again = [s for s in read_pptx(data)[0].shapes if isinstance(s.fill, PictureFill)]
    assert again and again[0].opacity == 0.5
    assert "opacity:0.5" in serialize_canvas([read_pptx(data)[0]]).slides[0].html


async def test_nested_opacities_multiply() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:300px;height:200px;opacity:.5'>"
        "<div style='opacity:.5;width:100px;height:100px;background:#cc2200'></div></div>"
    )

    assert _solid_shape(ir, "CC2200").opacity == 0.25


@pytest.mark.parametrize(
    ("style", "token", "css"),
    [("wavy", "wavy", "wavy"), ("dotted", "dotted", "dotted"), ("double", "dbl", "double")],
)
async def test_underline_style_survives_both_directions(style: str, token: str, css: str) -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;font-size:40px;"
        f"text-decoration:underline {style}'>Styled</div>"
    )
    run = next(r for s in ir.shapes if s.text for p in s.text.paragraphs for r in p.runs)
    assert run.underline == token

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        assert f'u="{token}"' in package.read("ppt/slides/slide1.xml").decode()
    again = read_pptx(data)[0]
    assert (
        next(r for s in again.shapes if s.text for p in s.text.paragraphs for r in p.runs).underline
        == token
    )
    assert f"text-decoration-style:{css}" in serialize_canvas([again]).slides[0].html


@pytest.mark.parametrize(
    "radius", ["50% / 30%", "40px 0 40px 0", "60px 20px / 30px 10px", "10px 80px 10px 80px"]
)
async def test_corners_that_are_not_one_circle_become_a_free_form_outline(radius: str) -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:220px;"
        f"background:linear-gradient(90deg,#c20,#08f);border-radius:{radius}'></div>"
    )

    [shape] = [s for s in ir.shapes if s.custom_geom is not None]
    assert isinstance(shape.fill, GradientFill) and shape.corner_radius_emu == 0
    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)

    again = read_pptx(build_pptx([ir], faces=[]))[0]
    assert any(s.custom_geom is not None for s in again.shapes)

    html = inline_assets(serialize_canvas([ir])).slides[0].html
    assert "clip-path:path(" in html and "linear-gradient" in html
    reloaded = await _render_and_extract(html)
    assert any(
        s.custom_geom is not None and isinstance(s.fill, GradientFill) for s in reloaded.shapes
    )


async def test_equal_circular_corners_stay_a_preset_round_rect() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:360px;height:220px;"
        "background:#c20;border-radius:24px'></div>"
    )

    [shape] = [s for s in ir.shapes if isinstance(s.fill, SolidFill)]
    assert shape.geom == "roundRect" and shape.custom_geom is None


async def test_outline_is_a_ring_just_outside_the_box_and_round_trips() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#eeeeee;border-radius:20px;outline:6px solid #cc2200;outline-offset:4px'>"
        "</div>"
    )

    ring = next(s for s in ir.shapes if s.line is not None and s.fill is None)
    assert ring.line is not None and ring.line.color.hex == "CC2200"
    # The ring is inflated by offset (4px) plus half the 6px width, so it sits outside the box.
    assert ring.box.x == px_to_emu(100) - px_to_emu(7)
    assert ring.box.width == px_to_emu(200) + 2 * px_to_emu(7)
    assert ring.geom == "roundRect" and ring.corner_radius_emu > px_to_emu(20)
    assert ring.provenance is not None and ring.provenance.role == "outline"

    again = read_pptx(build_pptx([ir], faces=[]))[0]
    assert any(s.line is not None and s.fill is None for s in again.shapes)


async def test_no_outline_adds_no_ring() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;height:100px;"
        "background:#eeeeee'></div>"
    )

    assert not any(s.line is not None and s.fill is None for s in ir.shapes)


async def test_underline_colour_that_differs_from_the_text_travels_both_ways() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;font-size:40px;color:#000000;"
        "text-decoration:underline wavy #cc2200'>Coloured</div>"
        "<div style='position:absolute;left:50px;top:200px;font-size:40px;color:#000000;"
        "text-decoration:underline'>Plain</div>"
    )
    coloured, plain = (
        next(r for p in s.text.paragraphs for r in p.runs)
        for s in ir.shapes
        if s.text and s.text.paragraphs
    )
    assert coloured.underline_color is not None and coloured.underline_color.hex == "CC2200"
    assert plain.underline_color is None

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        assert "<a:uFill>" in package.read("ppt/slides/slide1.xml").decode()
    again = [
        r for s in read_pptx(data)[0].shapes if s.text for p in s.text.paragraphs for r in p.runs
    ]
    assert again[0].underline_color is not None and again[0].underline_color.hex == "CC2200"
    assert (
        "text-decoration-color:rgba(204,34,0"
        in serialize_canvas([read_pptx(data)[0]]).slides[0].html
    )


async def test_faded_picture_with_text_fades_only_its_own_layer_in_html() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:300px;height:200px;opacity:.5;"
        f"background:url({_PNG}) center/cover;color:#000000;font-size:30px'>Caption</div>"
    )

    html = serialize_canvas([ir]).slides[0].html
    assert html.count("opacity:0.5") == 1  # the fill layer; the element itself is not faded
    assert 'data-domoxml-fill-layer="true"' in html and "isolation:isolate" in html
    caption = next(s for s in ir.shapes if s.text)
    assert caption.text is not None and caption.text.paragraphs[0].runs[0].color.a == 0.5


async def test_faded_per_side_borders_are_faded_with_the_element() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:50px;top:50px;width:300px;height:200px;opacity:.5;"
        "background:#eeeeee;border-left:8px solid #cc2200;border-top:2px solid #0044cc'></div>"
    )

    drawn = [s for s in ir.shapes if s.fill is not None]
    assert len(drawn) >= 3 and all(s.opacity == 0.5 for s in drawn)


async def test_outline_follows_the_css_box_not_the_text_slack_box() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:200px;font-size:24px;"
        "outline:4px solid #cc2200'>Text only</div>"
    )

    ring = next(s for s in ir.shapes if s.line is not None and s.fill is None)
    assert ring.box.x == px_to_emu(100) - px_to_emu(2)
    assert ring.box.width == px_to_emu(200) + 2 * px_to_emu(2)


def test_custom_outline_in_a_small_coordinate_space_is_scaled_to_its_box_in_html() -> None:
    from domoxml.core.ir.model import (
        Box,
        ClosePath,
        CubicTo,
        CustomGeometry,
        MoveTo,
        Point,
        ShapeNode,
        SlideIR,
    )

    square = Point(x=0, y=0)
    geometry = CustomGeometry(
        width_emu=100,
        height_emu=100,
        path=(
            MoveTo(to=square),
            CubicTo(c1=Point(x=50, y=0), c2=Point(x=100, y=50), to=Point(x=100, y=100)),
            ClosePath(),
        ),
    )
    node = ShapeNode(
        box=Box(x=0, y=0, width=px_to_emu(200), height=px_to_emu(100)),
        custom_geom=geometry,
        fill=GradientFill(
            stops=(
                GradientStop(pos=0.0, color=Rgba(r=200, g=0, b=0)),
                GradientStop(pos=1.0, color=Rgba(r=0, g=0, b=200)),
            ),
            angle_deg=90,
        ),
    )
    html = serialize_canvas([SlideIR(width=px_to_emu(400), height=px_to_emu(300), shapes=(node,))])

    # 100 path units across a 200px box: the curve's far corner is at 200px, not at ~0.
    assert "path(&#x27;M 0 0 C 100 0 200 50 200 100 Z&#x27;)" in html.slides[0].html


async def test_text_after_a_block_child_gets_its_own_box_below_it() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:360px;font-size:24px;"
        "background:#eeeeee'>Before<div style='height:60px;background:#cc2200'></div>After"
        "<div style='height:30px;background:#0044cc'></div>Last</div>"
    )

    def text_box(word: str) -> int:
        shape = next(
            s for s in ir.shapes if s.text and s.text.paragraphs[0].runs[0].text.strip() == word
        )
        return shape.box.y

    red, blue = _solid_shape(ir, "CC2200"), _solid_shape(ir, "0044CC")
    assert text_box("Before") < red.box.y < text_box("After") < blue.box.y < text_box("Last")
    # The leading text stays the parent's own line (bullets and anchors depend on that).
    parent = next(s for s in ir.shapes if s.text and s.text.paragraphs[0].runs[0].text == "Before")
    assert parent.fill is not None


async def test_details_and_nested_lists_keep_their_text_in_order() -> None:
    ir = await _render_and_extract(
        "<details open style='position:absolute;left:100px;top:100px;width:300px;font-size:24px'>"
        "<summary>Title</summary>Body text</details>"
    )

    boxes = sorted(
        (s.box.y, s.text.paragraphs[0].runs[0].text.strip()) for s in ir.shapes if s.text
    )
    assert [text for _, text in boxes] == ["Title", "Body text"]
    assert boxes[0][0] < boxes[1][0]


async def test_a_text_only_parent_is_left_exactly_as_it_was() -> None:
    ir = await _render_and_extract(
        "<p style='position:absolute;left:100px;top:100px;width:300px;font-size:24px'>"
        "one <b>two</b> three</p>"
    )

    [shape] = [s for s in ir.shapes if s.text]
    assert shape.text is not None
    assert [r.text for r in shape.text.paragraphs[0].runs] == ["one ", "two", " three"]


async def test_superscript_and_subscript_keep_size_and_lift_in_both_directions() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;font-size:40px'>"
        "H<sub>2</sub>O x<sup>2</sup></div>"
    )
    runs = [r for s in ir.shapes if s.text for p in s.text.paragraphs for r in p.runs]
    sub = next(r for r in runs if r.text == "2" and r.baseline < 0)
    sup = next(r for r in runs if r.text == "2" and r.baseline > 0)
    assert sub.baseline == -25_000 and sup.baseline == 30_000
    # Chrome draws these at 5/6 of the parent (30pt of 40px = 30pt -> 25pt).
    assert abs(sup.size_pt - 40 * 0.75 / 1.2) < 0.5

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    assert 'baseline="30000"' in xml and 'baseline="-25000"' in xml
    # PowerPoint draws a lifted run at two thirds of the stored size, so 25pt is stored as 37.5pt.
    assert 'sz="3750"' in xml

    again = [
        r for s in read_pptx(data)[0].shapes if s.text for p in s.text.paragraphs for r in p.runs
    ]
    lifted = [r for r in again if r.baseline]
    assert {r.baseline for r in lifted} == {30_000, -25_000}
    assert all(abs(r.size_pt - sup.size_pt) < 0.1 for r in lifted)
    html = serialize_canvas([read_pptx(data)[0]]).slides[0].html
    assert "vertical-align:super" in html and "vertical-align:sub" in html


async def test_an_absolutely_positioned_child_is_not_pulled_into_an_anonymous_block() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:100px;width:400px;height:300px;"
        "display:flex;align-items:center;justify-content:center'>"
        "<div style='width:100px;height:100px;background:#cc2200'></div>"
        "<h2 style='position:absolute;margin:0;font-size:40px'>Glow</h2></div>"
    )

    glow = next(s for s in ir.shapes if s.text and s.text.paragraphs[0].runs[0].text == "Glow")
    red = _solid_shape(ir, "CC2200")
    # Centred over the box, not dropped below it as an anonymous block would.
    assert abs((glow.box.y + glow.box.height / 2) - (red.box.y + red.box.height / 2)) < px_to_emu(
        20
    )


async def test_table_cell_vertical_alignment_round_trips() -> None:
    ir = await _render_and_extract(
        "<table style='position:absolute;left:50px;top:50px;border-collapse:collapse'><tr>"
        "<td style='height:120px;vertical-align:top'>T</td>"
        "<td style='vertical-align:middle'>M</td>"
        "<td style='vertical-align:bottom'>B</td></tr></table>"
    )
    table = next(n for n in ir.contents if isinstance(n, TableNode))
    assert [c.valign for c in table.rows[0].cells] == ["top", "middle", "bottom"]

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        xml = package.read("ppt/slides/slide1.xml").decode()
    assert 'anchor="ctr"' in xml and 'anchor="b"' in xml
    again = next(n for n in read_pptx(data)[0].contents if isinstance(n, TableNode))
    assert [c.valign for c in again.rows[0].cells] == ["top", "middle", "bottom"]
    html = serialize_canvas([read_pptx(data)[0]]).slides[0].html
    assert "vertical-align:bottom" in html and "vertical-align:middle" in html


async def test_vertical_writing_mode_round_trips_as_bodypr_vert() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:50px;width:80px;height:300px;"
        "font-size:30px;writing-mode:vertical-rl'>Vertical</div>"
    )
    shape = next(s for s in ir.shapes if s.text)
    assert shape.text is not None and shape.text.vertical == "vert"

    data = build_pptx([ir], faces=[])
    with ZipFile(BytesIO(data)) as package:
        assert 'vert="vert"' in package.read("ppt/slides/slide1.xml").decode()
    again = next(s for s in read_pptx(data)[0].shapes if s.text)
    assert again.text is not None and again.text.vertical == "vert"
    assert "writing-mode:vertical-rl" in serialize_canvas([read_pptx(data)[0]]).slides[0].html


async def test_form_controls_are_redrawn_from_their_state_as_shapes() -> None:
    result = await _render_and_extract_result(
        "<progress value='60' max='100' style='position:absolute;left:50px;top:50px;width:300px;"
        "height:20px'></progress>"
        "<meter value='0.9' low='0.5' high='0.8' optimum='0.1' style='position:absolute;left:50px;"
        "top:100px;width:300px;height:20px'></meter>"
        "<input type='checkbox' checked style='position:absolute;left:50px;top:150px;width:20px;"
        "height:20px;margin:0'>"
        "<input type='radio' style='position:absolute;left:90px;top:150px;width:20px;height:20px;"
        "margin:0'>"
        "<input type='range' value='25' style='position:absolute;left:50px;top:200px;width:300px;"
        "height:20px;margin:0'>"
    )

    shapes = result.slide.shapes
    assert not any(isinstance(s.fill, PictureFill) for s in shapes)
    # Progress: pill track half the element's height plus a bar 60% of the width.
    bar = _solid_shape(result.slide, "0075FF")
    assert bar.box.height == px_to_emu(10)
    # A value in the worst region of the meter is the red-orange, not the optimum green.
    assert _solid_shape(result.slide, "D83B01").box.width == px_to_emu(270)
    # A checked checkbox has its check mark; an empty radio has only its ring.
    assert any(s.custom_geom is not None and s.line is not None for s in shapes)
    assert all(item.representation.value in ("native", "decomposed") for item in result.coverage)

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert len(again.shapes) == len(shapes)


async def test_control_edge_cases_follow_direction_zero_maxima_and_opacity() -> None:
    result = await _render_and_extract_result(
        "<div style='opacity:.5'><input type='range' min='-10' max='0' value='-5' "
        "style='position:absolute;left:50px;top:50px;width:300px;height:20px;margin:0'></div>"
        "<progress value='50' max='100' dir='rtl' style='position:absolute;left:50px;top:100px;"
        "width:300px;height:20px'></progress>"
        "<progress style='position:absolute;left:50px;top:150px;width:300px;height:20px'>"
        "</progress>"
        "<input type='checkbox' style='position:absolute;left:50px;top:200px;width:20px;"
        "height:20px;transform:rotate(30deg)'>"
    )

    shapes = result.slide.shapes
    thumb = next(s for s in shapes if s.geom == "ellipse" and s.fill is not None)
    # min -10, max 0, value -5: the thumb is mid-track, not near the start.
    assert abs(thumb.box.x + thumb.box.width / 2 - px_to_emu(200)) < px_to_emu(10)
    assert thumb.opacity == 0.5
    bar = next(
        s
        for s in shapes
        if isinstance(s.fill, SolidFill)
        and s.fill.color.hex == "0075FF"
        and s.box.y == px_to_emu(105)
        and s.box.height == px_to_emu(10)
    )
    assert bar.box.x > px_to_emu(150)  # right-to-left: the 50% bar sits on the right
    # An indeterminate bar and a rotated control keep their raster instead of an upright redraw.
    assert sum(isinstance(s.fill, PictureFill) for s in shapes) == 2


@pytest.mark.parametrize(
    "body",
    [
        "<rect x='-20' y='10' width='60' height='30' fill='#c20'/>",  # past the viewport
        "<rect width='50%' height='50%' fill='#c20'/>",  # percentages need a viewport
        "<path d='M10 50H90' stroke='#000' stroke-width='4' stroke-dasharray='8 4' "
        "stroke-dashoffset='3'/>",
        "<path d='M10 10L20' fill='#c20'/>",  # truncated path data
    ],
)
async def test_svg_the_converter_cannot_reproduce_exactly_stays_a_vector_picture(
    body: str,
) -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>{body}"
        "<circle cx='80' cy='80' r='10' fill='#08f'/></svg>"
    )

    assert not any(s.custom_geom is not None for s in result.slide.shapes)
    assert any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)


async def test_a_rotated_group_turns_its_object_bounding_box_gradient_with_it() -> None:
    result = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'><defs><linearGradient id='g'>"
        "<stop offset='0' stop-color='#ff0000'/><stop offset='1' stop-color='#0000ff'/>"
        "</linearGradient></defs><g transform='translate(50 10) rotate(90)'>"
        "<rect width='60' height='30' fill='url(#g)'/></g></svg>"
    )

    gradient = next(s.fill for s in result.slide.shapes if isinstance(s.fill, GradientFill))
    # Left to right in the rectangle's own frame becomes top to bottom after a quarter turn.
    assert abs(gradient.angle_deg - 180.0) < 1.0


async def test_skew_transform_and_svg_node_paint_are_handled() -> None:
    skewed = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}' viewBox='0 0 100 100'>"
        "<rect x='10' y='10' width='40' height='30' fill='#c20' transform='skewX(20)'/></svg>"
    )
    assert any(s.custom_geom is not None for s in skewed.slide.shapes)

    painted = await _render_and_extract_result(
        f"<svg style='{_SVG_BOX}background:#eeeeee;border:2px solid #000' viewBox='0 0 100 100'>"
        "<path d='M10 10H50V50H10Z' fill='#c20'/><path d='M55 55H95V95H55Z' fill='#08f'/></svg>"
    )
    # The box's own background and border cannot be dropped, so the vector picture keeps them.
    assert not any(
        s.custom_geom is not None and isinstance(s.fill, SolidFill) and s.fill.color.hex == "CC2200"
        for s in painted.slide.shapes
    )
    assert not any("falling back to raster" in w.message for w in skewed.warnings)


async def test_canvas_drawing_with_a_shadow_becomes_a_shape_with_a_native_shadow() -> None:
    from domoxml.core.ir.model import Shadow

    result = await _render_and_extract_result(
        "<canvas id='c' width='300' height='200' style='position:absolute;left:50px;top:50px'>"
        "</canvas><script>const x=document.getElementById('c').getContext('2d');"
        "x.shadowBlur=12;x.shadowColor='rgba(0,0,0,.5)';x.shadowOffsetX=6;x.shadowOffsetY=8;"
        "x.fillStyle='#f80';x.fillRect(40,30,120,80)</script>"
    )

    [shape] = [s for s in result.slide.shapes if s.custom_geom is not None]
    [shadow] = [e for e in shape.effects if isinstance(e, Shadow)]
    assert shadow.color.a == 0.5 and shadow.blur_emu == px_to_emu(12)
    assert abs(shadow.distance_emu - px_to_emu(10)) < px_to_emu(0.1)  # a 6, 8 offset
    assert 50 < shadow.direction_deg < 58
    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert any(isinstance(e, Shadow) for s in again.shapes for e in s.effects)


async def test_canvas_shadow_scales_with_the_display_size_and_respects_the_edge() -> None:
    from domoxml.core.ir.model import Shadow

    scaled = await _render_and_extract_result(
        "<canvas id='c' width='300' height='200' style='position:absolute;left:50px;top:50px;"
        "width:150px;height:100px'></canvas><script>"
        "const x=document.getElementById('c').getContext('2d');x.shadowBlur=20;"
        "x.shadowColor='#000';x.shadowOffsetX=20;x.fillStyle='#f80';x.fillRect(40,40,100,80)"
        "</script>"
    )
    [shape] = [s for s in scaled.slide.shapes if s.custom_geom is not None]
    [shadow] = [e for e in shape.effects if isinstance(e, Shadow)]
    assert shadow.blur_emu == px_to_emu(10) and shadow.distance_emu == px_to_emu(10)

    clipped = await _render_and_extract_result(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px'>"
        "</canvas><script>const x=document.getElementById('c').getContext('2d');"
        "x.shadowBlur=8;x.shadowColor='#000';x.shadowOffsetX=10;x.fillStyle='#f80';"
        "x.fillRect(70,20,30,30)</script>"
    )
    assert any(isinstance(s.fill, PictureFill) for s in clipped.slide.shapes)


async def test_a_rounded_canvas_keeps_its_clip() -> None:
    ir = await _render_and_extract(
        "<canvas id='c' width='100' height='100' style='position:absolute;left:50px;top:50px;"
        "border-radius:50%'></canvas><script>const x=document.getElementById('c').getContext('2d');"
        "x.fillStyle='#f80';x.fillRect(0,0,100,100)</script>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in ir.shapes)
    assert not any(s.custom_geom is not None for s in ir.shapes)


async def test_gradient_border_image_becomes_a_gradient_outline_and_round_trips() -> None:
    ir = await _render_and_extract(
        "<div style='position:absolute;left:100px;top:80px;width:300px;height:160px;"
        "border:8px solid transparent;border-image:linear-gradient(90deg,#c20,#08f) 1'></div>"
    )

    outlined = [s for s in ir.shapes if s.line is not None and s.line.gradient is not None]
    assert len(outlined) == 1 and len(outlined[0].line.gradient.stops) == 2  # type: ignore[union-attr]
    assert not any(isinstance(s.fill, PictureFill) for s in ir.shapes)

    again = read_pptx(build_pptx([ir], faces=[]))[0]
    assert any(s.line is not None and s.line.gradient is not None for s in again.shapes)


async def test_border_image_with_rounded_corners_or_a_sliced_image_is_not_an_outline() -> None:
    for style in (
        "border:8px solid #444;border-radius:20px;border-image:linear-gradient(#c20,#08f) 1",
        "border:8px solid #444;border-image:linear-gradient(#c20,#08f) 30",
        "border:8px solid #444;border-image:linear-gradient(#c20,#08f) 100%",
        "border:8px solid #444;border-radius:0 20px;border-image:linear-gradient(#c20,#08f) 1",
        "border:8px solid #444;border-image:linear-gradient(#c20,#08f) 1 repeat",
    ):
        ir = await _render_and_extract(
            f"<div style='position:absolute;left:100px;top:80px;width:300px;height:160px;{style}'>"
            "</div>"
        )
        assert not any(s.line is not None and s.line.gradient is not None for s in ir.shapes)


_COLUMN_TEXT = " ".join(f"Line number {n} of the text." for n in range(1, 17))


async def test_balanced_columns_shrink_the_text_area_to_the_tallest_column() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:60px;top:60px;width:520px;height:400px;"
        f"columns:2;column-gap:20px;font:20px/28px Arial'>{_COLUMN_TEXT}</div>"
    )

    body = next(s.text for s in result.slide.shapes if s.text and s.text.columns == 2)
    # The text balances to a few lines per column, so most of the 400px box stays empty below.
    assert body.margins[3] > 150 * 9525
    assert not any("balanced CSS columns" in w.message for w in result.warnings)

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert any(s.text and s.text.columns == 2 and s.text.margins[3] > 0 for s in again.shapes)


async def test_sequentially_filled_columns_keep_the_full_text_area() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:60px;top:60px;width:520px;height:120px;"
        f"columns:2;column-fill:auto;column-gap:20px;font:20px/28px Arial'>{_COLUMN_TEXT}</div>"
    )

    body = next(s.text for s in result.slide.shapes if s.text and s.text.columns == 2)
    assert body.margins[3] == 0


async def test_balanced_columns_under_a_transform_keep_the_full_text_area() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:100px;width:520px;height:400px;"
        "transform:rotate(30deg);columns:2;column-gap:20px;font:20px/28px Arial'>"
        f"{_COLUMN_TEXT}</div>"
    )

    body = next(s.text for s in result.slide.shapes if s.text and s.text.columns == 2)
    assert body.margins[3] == 0


async def test_default_text_field_border_is_a_native_hairline_not_a_raster() -> None:
    result = await _render_and_extract_result(
        "<input type='text' value='Hello' style='position:absolute;left:100px;top:100px;"
        "width:300px;height:40px;font-size:20px'>"
    )

    outlined = [s for s in result.slide.shapes if s.line is not None]
    assert len(outlined) == 1 and outlined[0].line.width_emu == 9525  # type: ignore[union-attr]
    assert not any("3D border" in item.reason for item in result.coverage)
    assert all(item.representation.value == "native" for item in result.coverage)


async def test_drop_down_select_gets_its_chevron_and_a_list_box_does_not() -> None:
    result = await _render_and_extract_result(
        "<select style='position:absolute;left:100px;top:100px;width:240px;height:40px'>"
        "<option>One</option></select>"
        "<select multiple style='position:absolute;left:100px;top:200px;width:240px;height:80px'>"
        "<option>One</option></select>"
    )

    arrows = [s for s in result.slide.shapes if s.custom_geom is not None and s.line is not None]
    assert len(arrows) == 1
    assert all(item.representation.value == "native" for item in result.coverage)


async def test_text_fields_and_selects_carry_their_visible_text() -> None:
    result = await _render_and_extract_result(
        "<input type='text' value='Hello' style='position:absolute;left:100px;top:60px;"
        "width:300px;height:40px;font-size:20px'>"
        "<input type='text' placeholder='Your name' style='position:absolute;left:100px;"
        "top:120px;width:300px;height:40px;font-size:20px'>"
        "<input type='password' value='abc' style='position:absolute;left:100px;top:180px;"
        "width:300px;height:40px;font-size:20px'>"
        "<select style='position:absolute;left:100px;top:240px;width:240px;height:40px'>"
        "<option>One</option><option selected>Two</option></select>"
    )

    runs = {
        r.text: r for s in result.slide.shapes if s.text for p in s.text.paragraphs for r in p.runs
    }
    assert set(runs) == {"Hello", "Your name", "•••", "Two"}
    assert runs["Your name"].color != runs["Hello"].color
    fields = [s for s in result.slide.shapes if s.text and s.text.anchor == "middle"]
    assert len(fields) == 4
    assert all(s.text.margins[0] > 0 for s in fields)  # type: ignore[union-attr]

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert {r.text for s in again.shapes if s.text for p in s.text.paragraphs for r in p.runs} >= {
        "Hello",
        "Two",
    }


async def test_custom_styled_select_gets_no_chevron_and_fields_never_wrap() -> None:
    result = await _render_and_extract_result(
        "<select style='appearance:none;position:absolute;left:100px;top:100px;width:240px;"
        "height:40px'><option>One</option></select>"
        "<input type='text' value='A value far too long to fit in this narrow field at all' "
        "style='position:absolute;left:100px;top:200px;width:120px;height:40px'>"
    )

    assert not any(s.custom_geom is not None and s.line is not None for s in result.slide.shapes)
    field = next(
        s.text
        for s in result.slide.shapes
        if s.text and "too long" in s.text.paragraphs[0].runs[0].text
    )
    assert field.wrap == "none"

    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert any(s.text and s.text.wrap == "none" for s in again.shapes)


async def test_generic_monospace_and_serif_become_named_office_fonts() -> None:
    result = await _render_and_extract_result(
        "<pre style='position:absolute;left:100px;top:100px;margin:0;font-size:20px'>code</pre>"
        "<div style='position:absolute;left:100px;top:200px;font:24px serif'>serif text</div>"
        "<div style='position:absolute;left:100px;top:300px;font:24px Georgia, serif'>named</div>"
    )

    families = {
        r.text: r.font_family
        for s in result.slide.shapes
        if s.text
        for p in s.text.paragraphs
        for r in p.runs
    }
    assert families["code"] == "Courier New"
    assert families["serif text"] == "Times New Roman"
    assert families["named"] == "Georgia"

    html = inline_assets(serialize_canvas([result.slide])).slides[0].html
    assert "font-family:Courier New,monospace" in html


async def test_multiply_over_a_solid_shape_becomes_plain_shapes_in_the_blended_colour() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "background:#ffcc00'></div>"
        "<div style='position:absolute;left:300px;top:200px;width:300px;height:200px;"
        "background:#00ccff;mix-blend-mode:multiply'></div>"
    )

    colours = [s.fill.color for s in result.slide.shapes if isinstance(s.fill, SolidFill)]
    # The overlap is yellow x cyan; the rest of the cyan box sits on the white slide.
    assert Rgba(r=0, g=163, b=0) in colours
    assert any((c.r, c.g, c.b) == (0, 204, 255) for c in colours)
    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    assert any(item.representation.value == "decomposed" for item in result.coverage)


async def test_multiply_over_a_picture_still_keeps_its_raster() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "background:linear-gradient(#ffcc00,#cc00ff)'></div>"
        "<div style='position:absolute;left:300px;top:200px;width:300px;height:200px;"
        "background:#00ccff;mix-blend-mode:multiply'></div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)


async def test_screen_over_the_bare_canvas_keeps_its_own_colour() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "background:#336699'></div>"
        "<div style='position:absolute;left:250px;top:200px;width:300px;height:200px;"
        "background:#cc6600;mix-blend-mode:screen'></div>"
    )

    colours = {
        (s.fill.color.r, s.fill.color.g, s.fill.color.b)
        for s in result.slide.shapes
        if isinstance(s.fill, SolidFill)
    }
    assert (204, 102, 0) in colours  # outside the overlap the canvas blends as transparent
    assert (214, 163, 153) in colours  # 1 - (1 - a)(1 - b) per channel inside it


@pytest.mark.parametrize(
    "extra",
    [
        "mask-image:linear-gradient(black,transparent)",
        "",
    ],
)
async def test_a_blended_box_that_is_masked_or_clipped_by_an_ancestor_keeps_its_raster(
    extra: str,
) -> None:
    inner = (
        "<div style='position:absolute;left:100px;top:100px;width:300px;height:200px;"
        "background:#ffcc00'></div>"
        "<div style='position:absolute;left:250px;top:200px;width:300px;height:200px;"
        f"background:#00ccff;mix-blend-mode:multiply;{extra}'></div>"
    )
    html = (
        inner
        if extra
        else f"<div style='position:absolute;left:0;top:0;width:400px;height:300px;"
        f"overflow:hidden'>{inner}</div>"
    )

    result = await _render_and_extract_result(html)

    assert any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)


async def test_summary_gets_a_disclosure_triangle_and_its_text_sits_after_it() -> None:
    result = await _render_and_extract_result(
        "<details open style='position:absolute;left:100px;top:100px;width:400px;font:24px Arial'>"
        "<summary>Title</summary>Body</details>"
        "<details style='position:absolute;left:100px;top:300px;width:400px;font:24px Arial'>"
        "<summary>Closed</summary>Hidden</details>"
    )

    triangles = [s for s in result.slide.shapes if s.custom_geom is not None]
    assert len(triangles) == 2
    down, right = sorted(triangles, key=lambda s: s.box.y)
    assert down.box.width > down.box.height  # open: a triangle pointing down
    assert right.box.height > right.box.width  # closed: pointing right
    title = next(
        s for s in result.slide.shapes if s.text and s.text.paragraphs[0].runs[0].text == "Title"
    )
    assert title.text.paragraphs[0].indent_pt > 18  # type: ignore[union-attr]
    assert title.text.margins[0] == 0  # type: ignore[union-attr]
    again = read_pptx(build_pptx([result.slide], faces=[]))[0]
    assert sum(1 for s in again.shapes if s.custom_geom is not None) == 2


async def test_a_block_summary_has_no_marker_and_no_indent() -> None:
    result = await _render_and_extract_result(
        "<details open style='position:absolute;left:100px;top:100px;width:400px;font:24px Arial'>"
        "<summary style='display:block'>Plain</summary>Body</details>"
    )

    assert not any(s.custom_geom is not None for s in result.slide.shapes)
    plain = next(
        s for s in result.slide.shapes if s.text and s.text.paragraphs[0].runs[0].text == "Plain"
    )
    assert plain.text.paragraphs[0].indent_pt == 0  # type: ignore[union-attr]


async def test_a_child_clipped_by_a_rotated_container_becomes_a_native_cropped_shape() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:300px;top:150px;width:300px;height:200px;"
        "transform:rotate(12deg);overflow:hidden;background:#eee;border-radius:16px'>"
        "<div style='position:absolute;left:-40px;top:20px;width:400px;height:90px;"
        "background:#c20'></div></div>"
    )

    assert not any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
    cropped = next(
        s
        for s in result.slide.shapes
        if isinstance(s.fill, SolidFill) and (s.fill.color.r, s.fill.color.g) == (204, 34)
    )
    assert cropped.custom_geom is not None and cropped.transform is not None
    assert round(cropped.transform.rotation_deg) == 12
    # The red bar is 400px wide but the container clips it to 300: the path stops at the edge.
    xs = [c.to.x for c in cropped.custom_geom.path if isinstance(c, MoveTo | LineTo)]
    assert max(xs) - min(xs) <= 300 * 9525 + 2


async def test_a_child_with_its_own_extra_rotation_in_a_rotated_clip_keeps_its_raster() -> None:
    result = await _render_and_extract_result(
        "<div style='position:absolute;left:300px;top:150px;width:300px;height:200px;"
        "transform:rotate(12deg);overflow:hidden;background:#eee'>"
        "<div style='position:absolute;left:-40px;top:20px;width:400px;height:90px;"
        "transform:rotate(20deg);background:#c20'></div></div>"
    )

    assert any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)


async def test_uneven_corners_or_a_table_in_a_rotated_clip_keep_their_raster() -> None:
    for child in (
        "<div style='position:absolute;left:-40px;top:20px;width:400px;height:90px;"
        "background:#c20;border-radius:40px 0 0 0'></div>",
        "<table style='position:absolute;left:-40px;top:20px;font-size:20px'>"
        "<tr><td>One</td><td>Two</td></tr><tr><td>Three</td><td>Four</td></tr></table>",
    ):
        result = await _render_and_extract_result(
            "<div style='position:absolute;left:300px;top:150px;width:100px;height:100px;"
            f"transform:rotate(12deg);overflow:hidden'>{child}</div>"
        )

        assert any(isinstance(s.fill, PictureFill) for s in result.slide.shapes)
