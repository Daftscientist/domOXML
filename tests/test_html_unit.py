"""Canvas-IR to HTML serialization and artifact saving without a browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    ClosePath,
    Connector,
    CubicTo,
    CustomGeometry,
    Glow,
    GroupNode,
    Hyperlink,
    Line,
    LineSpacing,
    PictureFill,
    Point,
    PortableFallback,
    PreservationPart,
    PreservationPayload,
    PreservedNode,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SolidFill,
    SourceProvenance,
    TextBody,
    TextParagraph,
    TextRun,
    Transform,
)
from domoxml.core.ir.text_payload import decode_text_body, encode_text_body
from domoxml.core.opc import decode_payload
from domoxml.types import ConversionWarning, CoverageReport, PreservedFragment, RenderResult


def _slide() -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
                fill=SolidFill(color=Rgba(r=79, g=70, b=229)),
                opacity=0.5,
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(
                                    text="Coffee ",
                                    font_family="Inter",
                                    size_pt=24,
                                ),
                                TextRun(
                                    text="calm",
                                    font_family="Inter",
                                    size_pt=24,
                                    italic=True,
                                ),
                            )
                        ),
                    )
                ),
            ),
            ShapeNode(
                box=Box(x=0, y=0, width=100, height=100),
                fill=PictureFill(data=b"png", ext="png"),
                opacity=0.5,
            ),
        ),
    )


def test_serialize_canvas_emits_stable_slide_html_css_and_assets() -> None:
    html = serialize_canvas([_slide()])
    assert len(html.slides) == 1
    slide = html.slides[0]
    assert (slide.width_px, slide.height_px) == (1280, 720)
    assert "left:96px" in slide.html
    assert "background-color:rgba(79,70,229,0.5)" in slide.html
    assert "Coffee " in slide.html and "calm" in slide.html
    assert "font-style:italic" in slide.html
    assert len(html.assets) == 1
    assert html.assets[0].path.startswith("assets/")
    assert f"url(../{html.assets[0].path})" in slide.html
    assert slide.html.count("opacity:0.5") == 1


def test_serialize_canvas_visibly_flattens_groups_outside_the_proven_html_boundary() -> None:
    shape = ShapeNode(
        box=Box(x=0, y=0, width=500_000, height=500_000),
        fill=SolidFill(color=Rgba(r=239, g=68, b=68)),
    )
    groups = (
        (
            GroupNode(
                box=Box(x=1_000_000, y=1_000_000, width=1_000_000, height=1_000_000),
                child_box=Box(x=0, y=0, width=500_000, height=500_000),
                children=(shape,),
                transform=Transform(rotation_deg=15),
            ),
            "transformed group",
            "rotate(15deg)",
        ),
        (
            GroupNode(
                box=Box(x=1_000_000, y=1_000_000, width=1_000_000, height=1_000_000),
                child_box=Box(x=0, y=0, width=500_000, height=500_000),
                children=(
                    Connector(
                        start=Point(x=0, y=0),
                        end=Point(x=500_000, y=500_000),
                        line=Line(color=Rgba(r=15, g=23, b=42), width_emu=12_700),
                    ),
                ),
            ),
            "connector group child",
            "<svg",
        ),
    )

    for group, reason, visible_marker in groups:
        result = serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(group,))])
        html = result.slides[0].html
        assert visible_marker in html
        assert 'data-domoxml-group="' in html
        assert "data-domoxml-group-flattened=" in html
        assert any(reason in warning.message for warning in result.warnings)

    invalid = GroupNode(
        box=Box(x=1_000_000, y=1_000_000, width=0, height=1_000_000),
        child_box=Box(x=0, y=0, width=500_000, height=500_000),
        children=(shape,),
    )
    with pytest.raises(ValueError, match="group extent must be positive"):
        serialize_canvas([SlideIR(width=12_192_000, height=6_858_000, contents=(invalid,))])


def test_serialize_canvas_carries_exact_text_body_payload() -> None:
    source = _slide().shapes[0].text
    assert source is not None

    html = serialize_canvas([_slide()]).slides[0].html

    assert "data-domoxml-text-payload=" in html
    assert decode_text_body(encode_text_body(source)) == source
    assert decode_text_body("not-json") is None


def test_serialize_canvas_emits_identity_and_provenance_metadata() -> None:
    node = ShapeNode(
        node_id="hero-title",
        provenance=SourceProvenance(
            source_format="pptx",
            source_id="7",
            source_part="ppt/slides/slide1.xml",
            owner_node_id="hero",
            role="title",
        ),
        box=Box(x=0, y=0, width=100, height=100),
    )

    html = serialize_canvas([SlideIR(width=100, height=100, contents=(node,))]).slides[0].html

    assert 'data-domoxml-node-id="hero-title"' in html
    assert 'data-domoxml-source-format="pptx"' in html
    assert 'data-domoxml-source-id="7"' in html
    assert 'data-domoxml-source-part="ppt/slides/slide1.xml"' in html
    assert 'data-domoxml-owner-node-id="hero"' in html
    assert 'data-domoxml-layer-role="title"' in html


def test_serialize_canvas_emits_pure_svg_picture_as_an_image() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    node = ShapeNode(
        node_id="vector",
        box=Box(x=0, y=0, width=100, height=100),
        fill=PictureFill(data=b"png", ext="png", svg_data=svg),
    )

    html = serialize_canvas([SlideIR(width=100, height=100, contents=(node,))])

    assert '<img class="domoxml-shape"' in html.slides[0].html
    assert 'data-domoxml-node-id="vector"' in html.slides[0].html
    assert '.svg" alt=""' in html.slides[0].html
    assert html.assets[0].data == svg


def test_serialize_canvas_keeps_tiled_svg_picture_on_background_path() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    node = ShapeNode(
        box=Box(x=0, y=0, width=100, height=100),
        fill=PictureFill(data=b"png", ext="png", svg_data=svg, mode="tile"),
    )

    html = serialize_canvas([SlideIR(width=100, height=100, contents=(node,))])

    assert '<img class="domoxml-shape"' not in html.slides[0].html
    assert "background-image:url(../assets/" in html.slides[0].html


def test_custom_geometry_stroke_keeps_physical_width_in_svg_viewbox() -> None:
    geometry = CustomGeometry(
        width_emu=1_905_000,
        height_emu=952_500,
        path=(
            CubicTo(
                c1=Point(x=0, y=0),
                c2=Point(x=1_905_000, y=0),
                to=Point(x=1_905_000, y=952_500),
            ),
            ClosePath(),
        ),
    )
    node = ShapeNode(
        box=Box(x=0, y=0, width=1_905_000, height=952_500),
        custom_geom=geometry,
        line=Line(
            color=Rgba(r=31, g=78, b=121),
            width_emu=38_100,
            dash="dashDot",
            cap="square",
            join="miter",
        ),
    )

    html = serialize_canvas([SlideIR(width=1_905_000, height=952_500, contents=(node,))])

    assert 'stroke-width="4"' in html.slides[0].html
    assert 'stroke-dasharray="16 12 4 12"' in html.slides[0].html
    assert 'stroke-linecap="square"' in html.slides[0].html
    assert 'stroke-linejoin="miter"' in html.slides[0].html
    assert 'vector-effect="non-scaling-stroke"' in html.slides[0].html


def test_custom_geometry_emits_path_aware_shadow_and_glow_filters() -> None:
    geometry = CustomGeometry(
        width_emu=1_905_000,
        height_emu=952_500,
        path=(
            CubicTo(
                c1=Point(x=0, y=0),
                c2=Point(x=1_905_000, y=0),
                to=Point(x=1_905_000, y=952_500),
            ),
            ClosePath(),
        ),
    )
    node = ShapeNode(
        box=Box(x=0, y=0, width=1_905_000, height=952_500),
        custom_geom=geometry,
        effects=(
            Shadow(
                color=Rgba(r=10, g=20, b=30, a=0.4),
                blur_emu=114_300,
                distance_emu=95_250,
                direction_deg=0,
            ),
            Glow(color=Rgba(r=68, g=114, b=196, a=0.6), radius_emu=76_200),
        ),
    )

    html = serialize_canvas([SlideIR(width=1_905_000, height=952_500, contents=(node,))])

    assert (
        "filter:drop-shadow(10px 0px 12px rgba(10,20,30,0.5333)) "
        "drop-shadow(0px 0px 7.2727px rgba(68,114,196,1))"
    ) in html.slides[0].html
    assert "data-domoxml-effects=" in html.slides[0].html
    assert "data-domoxml-custom-geometry=" in html.slides[0].html


def test_custom_geometry_portable_fallback_is_visible_with_exact_bounds() -> None:
    geometry = CustomGeometry(
        width_emu=1_905_000,
        height_emu=952_500,
        path=(
            CubicTo(
                c1=Point(x=0, y=0),
                c2=Point(x=1_905_000, y=0),
                to=Point(x=1_905_000, y=952_500),
            ),
            ClosePath(),
        ),
    )
    node = ShapeNode(
        box=Box(x=952_500, y=762_000, width=1_905_000, height=952_500),
        custom_geom=geometry,
        fill=SolidFill(color=Rgba(r=37, g=99, b=235)),
        effects=(
            Shadow(
                color=Rgba(r=15, g=23, b=42, a=0.55),
                blur_emu=190_500,
                distance_emu=260_000,
            ),
            Shadow(
                color=Rgba(r=255, g=255, b=255, a=0.7),
                blur_emu=95_250,
                distance_emu=47_625,
                inset=True,
            ),
            Shadow(
                color=Rgba(r=225, g=29, b=72, a=0.65),
                blur_emu=285_750,
                distance_emu=430_000,
            ),
        ),
        native_effect_projection="schema_subset",
        portable_fallback=PortableFallback(
            box=Box(x=762_000, y=666_750, width=2_381_250, height=1_333_500),
            picture=PictureFill(data=b"exact-custom-effect-layer", ext="png"),
        ),
    )

    html = serialize_canvas([SlideIR(width=4_000_000, height=3_000_000, contents=(node,))])
    markup = html.slides[0].html

    assert 'data-domoxml-raster-bounds="80 70 250 140"' in markup
    assert '<image data-domoxml-render-layer="true"' in markup
    assert 'x="-190500" y="-95250" width="2381250" height="1333500"' in markup
    assert "<path " in markup and 'opacity="0"' in markup
    assert "filter:" not in markup
    assert html.assets[0].data == b"exact-custom-effect-layer"
    assert any("exact portable effect layer" in warning.message for warning in html.warnings)


def test_custom_geometry_unsupported_effect_warnings_name_the_shape() -> None:
    geometry = CustomGeometry(
        width_emu=100,
        height_emu=100,
        path=(CubicTo(c1=Point(x=0, y=0), c2=Point(x=100, y=0), to=Point(x=100, y=100)),),
    )
    node = ShapeNode(
        node_id="custom-path-7",
        box=Box(x=0, y=0, width=100, height=100),
        custom_geom=geometry,
        effects=(
            Shadow(
                color=Rgba(r=0, g=0, b=0),
                blur_emu=10,
                distance_emu=20,
                spread_emu=5,
            ),
            Reflection(),
        ),
    )

    html = serialize_canvas([SlideIR(width=100, height=100, contents=(node,))])

    assert len(html.warnings) == 2
    assert {warning.element for warning in html.warnings} == {"custom-path-7"}


def test_serialize_canvas_embeds_attached_preservation_payload() -> None:
    payload = PreservationPayload(
        kind="graphicFrame",
        root_xml="<p:graphicFrame/>",
        parts=(
            PreservationPart(
                name="ppt/embeddings/data.xlsx",
                content_type="application/xlsx",
                data=b"\x00binary\xff",
            ),
        ),
    )
    node = PreservedNode(
        node_id="chart-1",
        box=Box(x=100, y=200, width=300, height=400),
        payload=payload,
    )

    html = serialize_canvas([SlideIR(width=1_000, height=1_000, contents=(node,))]).slides[0].html
    marker = 'data-domoxml-preserved-payload="'
    encoded = html.split(marker, 1)[1].split('"', 1)[0]

    assert 'class="domoxml-preserved"' in html
    assert 'data-domoxml-node-id="chart-1"' in html
    assert decode_payload(encoded) == payload


def test_serialize_canvas_makes_preserved_fallback_visible_as_an_asset() -> None:
    payload = PreservationPayload(kind="graphicFrame", root_xml="<p:graphicFrame/>")
    node = PreservedNode(
        node_id="chart-1",
        box=Box(x=100, y=200, width=300, height=400),
        payload=payload,
        fallback=PictureFill(data=b"fallback-png", ext="png"),
    )

    result = serialize_canvas([SlideIR(width=1_000, height=1_000, contents=(node,))])

    assert '<img class="domoxml-preserved"' in result.slides[0].html
    assert 'data-domoxml-representation="element-layer"' in result.slides[0].html
    assert "opacity:0" not in result.slides[0].html
    assert result.assets[0].data == b"fallback-png"


def test_serialize_canvas_places_slide_fallback_above_retained_contents() -> None:
    payload = PreservationPayload(kind="sp", root_xml="<p:sp/>")
    preserved = PreservedNode(
        node_id="shadow-source",
        box=Box(x=100, y=200, width=300, height=400),
        payload=payload,
    )
    sibling = ShapeNode(
        box=Box(x=500, y=600, width=200, height=100),
        fill=SolidFill(color=Rgba(r=239, g=68, b=68, a=0.55)),
    )
    result = serialize_canvas(
        [
            SlideIR(
                width=1_000,
                height=1_000,
                contents=(preserved, sibling),
                renderer_fallback=PictureFill(data=b"slide-png", ext="png"),
                renderer_fallback_owner_node_id="shadow-source",
            )
        ]
    )

    html = result.slides[0].html
    assert html.index('data-domoxml-node-id="shadow-source"') < html.index(
        'data-domoxml-slide-fallback="rasterized"'
    )
    assert 'class="domoxml-slide-fallback"' in html
    assert 'data-domoxml-owner-node-id="shadow-source"' in html
    assert "z-index:2147483647" in html
    assert result.assets[-1].data == b"slide-png"


def test_render_result_save_writes_every_artifact(tmp_path: Path) -> None:
    html = serialize_canvas([_slide()])
    result = RenderResult(
        pptx=b"pptx",
        pngs=(b"png-1",),
        html=html,
        coverage=CoverageReport(items=()),
        warnings=(),
    )
    result.save(tmp_path)

    assert (tmp_path / "deck.pptx").read_bytes() == b"pptx"
    assert (tmp_path / "slide-01.png").read_bytes() == b"png-1"
    assert (tmp_path / "html" / "shared.css").read_text()
    assert "Coffee " in (tmp_path / "html" / "slides" / "slide-01.html").read_text()
    assert (tmp_path / "html" / html.assets[0].path).read_bytes() == b"png"


def test_html_presentation_save_writes_reverse_metadata(tmp_path: Path) -> None:
    html = serialize_canvas(
        [_slide()],
        warnings=(ConversionWarning(message="preserved unsupported node", element="slide1:pic"),),
        preserved=(PreservedFragment(part="ppt/slides/slide1.xml", kind="pic", xml="<p:pic/>"),),
    )
    html.save(tmp_path)
    metadata = (tmp_path / "metadata.json").read_text()
    assert "preserved unsupported node" in metadata
    assert "<p:pic/>" in metadata


def _decorated_slide() -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=3_000_000, height=1_000_000),
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(
                                    text="deco",
                                    font_family="Inter",
                                    size_pt=18,
                                    underline=True,
                                    strike=True,
                                    caps="all",
                                    letter_spacing_pt=2.0,
                                ),
                                TextRun(text="sc", font_family="Inter", size_pt=18, caps="small"),
                                TextRun(
                                    text="ext",
                                    font_family="Inter",
                                    size_pt=18,
                                    hyperlink=Hyperlink(url="https://example.com"),
                                ),
                                TextRun(
                                    text="jump",
                                    font_family="Inter",
                                    size_pt=18,
                                    hyperlink=Hyperlink(slide_index=2),
                                ),
                            )
                        ),
                    )
                ),
            ),
        ),
    )


def test_serialize_canvas_emits_run_decorations() -> None:
    html = serialize_canvas([_decorated_slide()]).slides[0].html
    assert 'data-domoxml-text-body="true"' in html
    assert "text-decoration-line:underline line-through" in html
    assert "text-transform:uppercase" in html
    assert "font-variant-caps:small-caps" in html
    assert "letter-spacing:2pt" in html


def test_serialize_canvas_wraps_runs_in_hyperlinks() -> None:
    html = serialize_canvas([_decorated_slide()]).slides[0].html
    assert '<a href="https://example.com">' in html
    # slide_index=2 → 1-based #slide-3 authoring convention.
    assert '<a href="#slide-3">' in html


# --------------------------------------------------------------------------- list reconstruction


def _list_slide(*paragraphs: TextParagraph) -> SlideIR:
    """Wrap paragraphs in a minimal SlideIR for HTML serialization."""
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=3_000_000, height=1_000_000),
                text=TextBody(paragraphs=paragraphs),
            ),
        ),
    )


def _run(text: str) -> TextRun:
    return TextRun(text=text, font_family="Arial", size_pt=12)


def test_html_rejects_active_and_unknown_hyperlink_schemes() -> None:
    runs = tuple(
        TextRun(text=url, font_family="Arial", size_pt=12, hyperlink=Hyperlink(url=url))
        for url in (
            "javascript:alert(1)",
            "data:text/html,bad",
            "file:///etc/passwd",
            "relative/path",
        )
    )
    html = serialize_canvas([_list_slide(TextParagraph(runs=runs))]).slides[0].html

    assert "<a href=" not in html
    assert "javascript:" in html


def test_html_allows_safe_and_internal_hyperlink_schemes() -> None:
    urls = (
        "https://example.com",
        "http://example.com",
        "mailto:a@example.com",
        "tel:+44123",
        "#slide-2",
    )
    runs = tuple(
        TextRun(text=url, font_family="Arial", size_pt=12, hyperlink=Hyperlink(url=url))
        for url in urls
    )
    html = serialize_canvas([_list_slide(TextParagraph(runs=runs))]).slides[0].html

    for url in urls:
        assert f'<a href="{url}">' in html


def test_html_char_bullets_emit_ul_and_li() -> None:
    """CharBullet paragraphs → <ul>…<li>…</li></ul>."""
    slide = _list_slide(
        TextParagraph(runs=(_run("Apple"),), bullet=CharBullet(char="•")),
        TextParagraph(runs=(_run("Banana"),), bullet=CharBullet(char="•")),
    )
    html = serialize_canvas([slide]).slides[0].html
    assert "<ul" in html
    assert "<li" in html
    assert "Apple" in html and "Banana" in html
    assert "</ul>" in html
    assert "data-domoxml-text-body" not in html


def test_html_bullet_gutter_is_on_list_container() -> None:
    slide = _list_slide(
        TextParagraph(
            runs=(_run("Indented"),),
            bullet=CharBullet(char="•"),
            indent_pt=-12.75,
            left_margin_pt=13.5,
        )
    )

    html = serialize_canvas([slide]).slides[0].html

    assert '<ul style="list-style-type:disc;padding-left:13.5pt">' in html
    assert "text-indent" not in html
    assert html.count("padding-left") == 1


def test_html_autonum_bullets_emit_ol_and_li() -> None:
    """AutoNumberBullet paragraphs → <ol>…<li>…</li></ol>."""
    slide = _list_slide(
        TextParagraph(runs=(_run("First"),), bullet=AutoNumberBullet(scheme="arabicPeriod")),
        TextParagraph(runs=(_run("Second"),), bullet=AutoNumberBullet(scheme="arabicPeriod")),
    )
    html = serialize_canvas([slide]).slides[0].html
    assert "<ol" in html
    assert "<li" in html
    assert "First" in html and "Second" in html
    assert "</ol>" in html


def test_html_nested_bullets_emit_nested_ul() -> None:
    """level=0 and level=1 bullets produce nested <ul> structure."""
    slide = _list_slide(
        TextParagraph(runs=(_run("Top"),), bullet=CharBullet(char="•"), level=0),
        TextParagraph(runs=(_run("Nested"),), bullet=CharBullet(char="○"), level=1),
        TextParagraph(runs=(_run("Back"),), bullet=CharBullet(char="•"), level=0),
    )
    html = serialize_canvas([slide]).slides[0].html
    # Two separate <ul> opens: one outer, one inner for nested
    assert html.count("<ul") >= 2
    assert "Nested" in html
    assert "</ul>" in html


def test_html_plain_para_closes_open_lists() -> None:
    """A non-bullet paragraph after bullets closes any open list tags."""
    slide = _list_slide(
        TextParagraph(runs=(_run("Item"),), bullet=CharBullet(char="•")),
        TextParagraph(runs=(_run("Plain"),)),
    )
    html = serialize_canvas([slide]).slides[0].html
    # The </ul> must appear before the plain paragraph content
    ul_close = html.find("</ul>")
    plain_pos = html.find("Plain")
    assert ul_close < plain_pos, "</ul> should precede the plain paragraph"


def test_html_line_spacing_emits_line_height() -> None:
    """line_spacing(percent=1.6) → line-height:1.6 in div/li style."""
    slide = _list_slide(
        TextParagraph(
            runs=(_run("x"),),
            line_spacing=LineSpacing(percent=1.6),
        )
    )
    html = serialize_canvas([slide]).slides[0].html
    assert "line-height:1.6" in html


def test_html_space_before_after_emits_margins() -> None:
    """space_before_pt=9/space_after_pt=18 → margin-top:9pt;margin-bottom:18pt."""
    slide = _list_slide(
        TextParagraph(
            runs=(_run("x"),),
            space_before_pt=9.0,
            space_after_pt=18.0,
        )
    )
    html = serialize_canvas([slide]).slides[0].html
    assert "margin-top:9pt" in html
    assert "margin-bottom:18pt" in html
