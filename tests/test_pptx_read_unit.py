"""PresentationML reader tests against deterministic domOXML-generated decks."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from defusedxml import ElementTree

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
from domoxml.slides import build_pptx, read_pptx
from domoxml.slides.read import _rgba

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


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
