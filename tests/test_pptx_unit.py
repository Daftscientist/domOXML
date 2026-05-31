"""Slides-backend unit tests: build a .pptx from IR and prove it's valid (no browser)."""

from __future__ import annotations

import io
import zipfile

import pytest
from pptx import Presentation as PptxRead  # test-only validator

from domoxml.core.ir.model import (
    Box,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides import build_pptx


def _sample_ir() -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=914_400, y=914_400, width=3_657_600, height=1_828_800),
                fill=SolidFill(color=Rgba(r=79, g=70, b=229)),
                corner_radius_emu=76_200,
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(
                                    text="Driftwood",
                                    font_family="Inter",
                                    size_pt=24.0,
                                    bold=True,
                                    color=Rgba(r=255, g=255, b=255),
                                ),
                            ),
                            align="center",
                        ),
                    )
                ),
            ),
            ShapeNode(box=Box(x=0, y=0, width=100, height=100)),  # plain, no fill/text
        ),
    )


def test_build_pptx_is_a_zip_with_required_parts() -> None:
    data = build_pptx([_sample_ir()])
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/theme/theme1.xml",
        "ppt/slides/slide1.xml",
    }
    assert required <= names


def test_build_pptx_opens_and_keeps_text_editable() -> None:
    prs = PptxRead(io.BytesIO(build_pptx([_sample_ir()])))
    assert len(prs.slides) == 1
    texts: list[str] = []
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame:
            texts.append(shape.text_frame.text)  # pyright: ignore  (python-pptx stubs)
    assert "Driftwood" in texts  # real editable text run, not a rasterised image


def test_build_pptx_requires_a_slide() -> None:
    with pytest.raises(ValueError, match="at least one slide"):
        build_pptx([])


def test_build_pptx_rejects_mismatched_slide_sizes() -> None:
    a = SlideIR(width=12_192_000, height=6_858_000, shapes=())
    b = SlideIR(width=9_144_000, height=6_858_000, shapes=())  # 4:3 — different width
    with pytest.raises(ValueError, match="share one size"):
        build_pptx([a, b])
