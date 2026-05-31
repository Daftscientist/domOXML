"""PresentationML reader tests against deterministic domOXML-generated decks."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from io import BytesIO

from defusedxml import ElementTree
from PIL import Image
from pptx import Presentation as PptxPresentation
from pptx.util import Inches

from domoxml import Presentation, pptx_to_html
from domoxml.core.ir.model import (
    Box,
    GradientFill,
    GradientStop,
    Line,
    PictureFill,
    Rgba,
    Shadow,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.core.opc import OpcPackage, write_package
from domoxml.slides import build_pptx, read_pptx
from domoxml.slides.read import _rgba, _slide_colors

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _sample_ir() -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=914_400, y=914_400, width=3_657_600, height=1_828_800),
                geom="roundRect",
                fill=SolidFill(color=Rgba(r=79, g=70, b=229, a=0.75)),
                line=Line(color=Rgba(r=1, g=2, b=3), width_emu=19_050, dash="dash"),
                shadow=Shadow(
                    color=Rgba(r=0, g=0, b=0, a=0.4),
                    blur_emu=20_000,
                    distance_emu=10_000,
                    direction_deg=90,
                ),
                corner_radius_emu=76_200,
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(text="Coffee ", font_family="Inter", size_pt=24),
                                TextRun(
                                    text="calm",
                                    font_family="Inter",
                                    size_pt=24,
                                    italic=True,
                                    color=Rgba(r=255, g=255, b=255),
                                ),
                            ),
                            align="center",
                        ),
                    )
                ),
            ),
            ShapeNode(
                box=Box(x=0, y=0, width=100, height=100),
                fill=GradientFill(
                    stops=(
                        GradientStop(pos=0, color=Rgba(r=0, g=0, b=0)),
                        GradientStop(pos=1, color=Rgba(r=255, g=255, b=255)),
                    ),
                    angle_deg=90,
                ),
            ),
            ShapeNode(
                box=Box(x=100, y=100, width=200, height=200),
                fill=PictureFill(data=b"png-bytes", ext="png"),
            ),
        ),
    )


def test_reads_generated_pptx_into_canvas_ir() -> None:
    [slide] = read_pptx(build_pptx([_sample_ir()], faces=[]))
    assert (slide.width, slide.height) == (12_192_000, 6_858_000)
    assert len(slide.shapes) == 3

    rich, gradient, picture = slide.shapes
    assert rich.box.x == 914_400 and rich.geom == "roundRect"
    assert isinstance(rich.fill, SolidFill) and rich.fill.color.a == 0.75
    assert rich.line is not None and rich.line.dash == "dash"
    assert rich.shadow is not None and rich.shadow.direction_deg == 90
    assert rich.text is not None
    assert "".join(run.text for run in rich.text.paragraphs[0].runs) == "Coffee calm"
    assert rich.text.paragraphs[0].runs[1].italic is True

    assert isinstance(gradient.fill, GradientFill)
    assert gradient.fill.angle_deg == 90
    assert isinstance(picture.fill, PictureFill)
    assert picture.fill.data == b"png-bytes"


def test_exposes_generated_pptx_as_html() -> None:
    pptx = build_pptx([_sample_ir()], faces=[])
    html = pptx_to_html(pptx)
    assert len(html.slides) == 1
    assert "Coffee " in html.slides[0].html and "calm" in html.slides[0].html
    assert len(html.assets) == 1
    assert Presentation.from_pptx(pptx) == html


def test_resolves_theme_system_and_preset_colors() -> None:
    scheme = ElementTree.fromstring(
        f'<a:solidFill xmlns:a="{_A}"><a:schemeClr val="accent1">'
        '<a:alpha val="50000"/></a:schemeClr></a:solidFill>'
    )
    system = ElementTree.fromstring(
        f'<a:solidFill xmlns:a="{_A}"><a:sysClr val="window" lastClr="102030"/></a:solidFill>'
    )
    preset = ElementTree.fromstring(
        f'<a:solidFill xmlns:a="{_A}"><a:prstClr val="red"/></a:solidFill>'
    )
    assert _rgba(scheme, {"accent1": "112233"}) == Rgba(r=17, g=34, b=51, a=0.5)
    assert _rgba(system, {}) == Rgba(r=16, g=32, b=48)
    assert _rgba(preset, {}) == Rgba(r=255, g=0, b=0)


def test_resolves_slide_theme_through_layout_master_chain_and_color_maps() -> None:
    package = OpcPackage.from_bytes(
        write_package(
            {
                "ppt/slides/slide1.xml": (
                    f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:clrMapOvr>'
                    '<a:overrideClrMapping accent1="accent2"/></p:clrMapOvr></p:sld>'
                ),
                "ppt/slides/_rels/slide1.xml.rels": (
                    f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
                    f'Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                    "</Relationships>"
                ),
                "ppt/slideLayouts/slideLayout1.xml": (
                    f'<p:sldLayout xmlns:p="{_P}" xmlns:a="{_A}"><p:clrMapOvr>'
                    '<a:overrideClrMapping tx1="accent1"/></p:clrMapOvr></p:sldLayout>'
                ),
                "ppt/slideLayouts/_rels/slideLayout1.xml.rels": (
                    f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
                    f'Type="{_R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
                    "</Relationships>"
                ),
                "ppt/slideMasters/slideMaster1.xml": (
                    f'<p:sldMaster xmlns:p="{_P}"><p:clrMap tx1="dk1" accent1="accent1"/>'
                    "</p:sldMaster>"
                ),
                "ppt/slideMasters/_rels/slideMaster1.xml.rels": (
                    f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
                    f'Type="{_R}/theme" Target="../theme/theme1.xml"/></Relationships>'
                ),
                "ppt/theme/theme0.xml": (
                    f'<a:theme xmlns:a="{_A}"><a:themeElements><a:clrScheme name="wrong">'
                    '<a:accent1><a:srgbClr val="FFFFFF"/></a:accent1>'
                    "</a:clrScheme></a:themeElements></a:theme>"
                ),
                "ppt/theme/theme1.xml": (
                    f'<a:theme xmlns:a="{_A}"><a:themeElements><a:clrScheme name="right">'
                    '<a:dk1><a:srgbClr val="000000"/></a:dk1>'
                    '<a:accent1><a:srgbClr val="112233"/></a:accent1>'
                    '<a:accent2><a:srgbClr val="445566"/></a:accent2>'
                    "</a:clrScheme></a:themeElements></a:theme>"
                ),
            }
        )
    )
    colors = _slide_colors(package, "ppt/slides/slide1.xml")
    assert colors["tx1"] == "112233"
    assert colors["accent1"] == "445566"


def test_preserves_unsupported_slide_nodes_with_warning() -> None:
    package = OpcPackage.from_bytes(build_pptx([_sample_ir()], faces=[]))
    parts: dict[str, bytes | str] = {part: package.read(part) for part in package.parts}
    slide_part = "ppt/slides/slide1.xml"
    slide_xml = parts[slide_part]
    assert isinstance(slide_xml, bytes)
    parts[slide_part] = slide_xml.replace(
        b"</p:spTree>", b"<p:graphicFrame><p:nvGraphicFramePr/></p:graphicFrame></p:spTree>"
    )

    html = pptx_to_html(write_package(parts))

    assert len(html.preserved) == 1
    assert html.preserved[0].part == slide_part
    assert html.preserved[0].kind == "graphicFrame"
    assert "graphicFrame" in html.preserved[0].xml
    assert len(html.warnings) == 1
    assert "unsupported reverse slide node" in html.warnings[0].message


def test_reads_native_powerpoint_picture() -> None:
    image = BytesIO()
    Image.new("RGB", (10, 10), "#4472C4").save(image, format="PNG")
    image.seek(0)
    deck = PptxPresentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(image, Inches(1), Inches(1), Inches(2), Inches(1))
    pptx = BytesIO()
    deck.save(pptx)

    [result] = read_pptx(pptx.getvalue())

    assert len(result.shapes) == 1
    fill = result.shapes[0].fill
    assert isinstance(fill, PictureFill)
    assert fill.ext == "png"
