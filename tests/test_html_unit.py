"""Canvas-IR to HTML serialization and artifact saving without a browser."""

from __future__ import annotations

from pathlib import Path

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    Box,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.types import CoverageReport, RenderResult


def _slide() -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=914_400, y=914_400, width=1_828_800, height=914_400),
                fill=SolidFill(color=Rgba(r=79, g=70, b=229)),
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
            ),
        ),
    )


def test_serialize_canvas_emits_stable_slide_html_css_and_assets() -> None:
    html = serialize_canvas([_slide()])
    assert len(html.slides) == 1
    slide = html.slides[0]
    assert (slide.width_px, slide.height_px) == (1280, 720)
    assert "left:96px" in slide.html
    assert "background-color:rgba(79,70,229,1)" in slide.html
    assert "Coffee " in slide.html and "calm" in slide.html
    assert "font-style:italic" in slide.html
    assert len(html.assets) == 1
    assert html.assets[0].path.startswith("assets/")
    assert f"url(../{html.assets[0].path})" in slide.html


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
