"""Slides-backend unit tests: build a .pptx from IR and prove it's valid (no browser)."""

from __future__ import annotations

import io
import zipfile

import pytest
from pptx import Presentation as PptxRead  # test-only validator

from domoxml.core.ir.model import (
    Box,
    Hyperlink,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides import build_pptx

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _slide_xml(pptx: bytes, name: str = "ppt/slides/slide1.xml") -> str:
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        return archive.read(name).decode("utf-8")


def _slide_rels(pptx: bytes, name: str = "ppt/slides/_rels/slide1.xml.rels") -> str:
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        return archive.read(name).decode("utf-8")


def _decorated_run(**kw: object) -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=3_000_000, height=1_000_000),
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(TextRun(text="x", font_family="Inter", size_pt=18, **kw),)  # type: ignore[arg-type]
                        ),
                    )
                ),
            ),
        ),
    )


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


def test_run_underline_and_strike_emit_both_attrs() -> None:
    xml = _slide_xml(build_pptx([_decorated_run(underline=True, strike=True)], faces=[]))
    assert 'u="sng"' in xml
    assert 'strike="sngStrike"' in xml


def test_run_caps_uppercase_emits_cap_all_and_keeps_raw_text() -> None:
    # The IR run text is the authored text; PowerPoint applies the cap. We must NOT pre-uppercase.
    ir = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=3_000_000, height=1_000_000),
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(
                                TextRun(text="Hello", font_family="Inter", size_pt=18, caps="all"),
                            )
                        ),
                    )
                ),
            ),
        ),
    )
    xml = _slide_xml(build_pptx([ir], faces=[]))
    assert 'cap="all"' in xml
    assert "<a:t>Hello</a:t>" in xml  # raw text, not "HELLO"
    assert "HELLO" not in xml


def test_run_small_caps_and_letter_spacing_emit_cap_small_and_spc() -> None:
    xml = _slide_xml(build_pptx([_decorated_run(caps="small", letter_spacing_pt=2.0)], faces=[]))
    assert 'cap="small"' in xml
    assert 'spc="200"' in xml  # 2.0pt → 200 (1/100 pt)


def test_external_hyperlink_emits_hlinkclick_and_external_rel() -> None:
    pptx = build_pptx([_decorated_run(hyperlink=Hyperlink(url="https://example.com"))], faces=[])
    xml = _slide_xml(pptx)
    rels = _slide_rels(pptx)
    assert "<a:hlinkClick" in xml and 'r:id="' in xml
    assert 'Target="https://example.com" TargetMode="External"' in rels
    assert "/relationships/hyperlink" in rels


def test_out_of_range_slide_jump_is_dropped_with_warning() -> None:
    # A rel targeting a slide part that doesn't exist makes PowerPoint repair the file.
    deck = [_decorated_run(hyperlink=Hyperlink(slide_index=1))]  # only 1 slide in deck
    with pytest.warns(UserWarning, match="targets slide 2"):
        pptx = build_pptx(deck, faces=[])
    assert 'Target="slide2.xml"' not in _slide_rels(pptx)
    assert "hlinksldjump" not in _slide_xml(pptx)


def test_slide_jump_hyperlink_emits_jump_action_and_internal_slide_rel() -> None:
    deck = [
        _decorated_run(hyperlink=Hyperlink(slide_index=1)),
        SlideIR(width=12_192_000, height=6_858_000, shapes=()),
    ]
    pptx = build_pptx(deck, faces=[])
    xml = _slide_xml(pptx)
    rels = _slide_rels(pptx)
    assert 'action="ppaction://hlinksldjump"' in xml
    assert 'Target="slide2.xml"' in rels
    assert "/relationships/slide" in rels
