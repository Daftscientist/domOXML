"""Canvas-IR to HTML serialization and artifact saving without a browser."""

from __future__ import annotations

from pathlib import Path

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    Hyperlink,
    LineSpacing,
    PictureFill,
    PreservationPart,
    PreservationPayload,
    PreservedNode,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    SourceProvenance,
    TextBody,
    TextParagraph,
    TextRun,
)
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
