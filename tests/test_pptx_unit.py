"""Slides-backend unit tests: build a .pptx from IR and prove it's valid (no browser)."""

from __future__ import annotations

import io
import zipfile

import pytest
from pptx import Presentation as PptxRead  # test-only validator

from domoxml.core.ir.model import (
    AutoNumberBullet,
    Box,
    CharBullet,
    Hyperlink,
    LineSpacing,
    PictureFill,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
    SrcRect,
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


def test_pure_picture_fill_emits_native_picture_with_crop() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=100, y=200, width=300, height=400),
                fill=PictureFill(data=b"png", crop=SrcRect(left=1 / 3, right=1 / 3)),
            ),
        ),
    )

    xml = _slide_xml(build_pptx([slide], faces=[]))

    assert "<p:pic>" in xml
    assert "<p:blipFill>" in xml
    assert '<a:srcRect l="33333" r="33333"/>' in xml


def test_repeated_bitmap_reuses_one_media_relationship() -> None:
    picture = PictureFill(data=b"same-png")
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(box=Box(x=0, y=0, width=100, height=100), fill=picture),
            ShapeNode(box=Box(x=100, y=0, width=100, height=100), fill=picture),
        ),
    )

    pptx = build_pptx([slide], faces=[])
    xml = _slide_xml(pptx)
    rels = _slide_rels(pptx)
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        media = [name for name in archive.namelist() if name.startswith("ppt/media/")]

    assert xml.count('r:embed="rId2"') == 2
    assert rels.count("/relationships/image") == 1
    assert media == ["ppt/media/image1.png"]


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


# --------------------------------------------------------------------------- paragraph pPr tests


def _para_ir(paragraph: TextParagraph) -> SlideIR:
    """Helper: wrap a single paragraph in a minimal SlideIR."""
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=3_000_000, height=1_000_000),
                text=TextBody(paragraphs=(paragraph,)),
            ),
        ),
    )


def test_ppr_line_spacing_percent_emits_spc_pct() -> None:
    """line_spacing(percent=1.5) → <a:lnSpc><a:spcPct val="150000"/></a:lnSpc>."""
    para = TextParagraph(
        runs=(TextRun(text="x", font_family="Arial", size_pt=12),),
        line_spacing=LineSpacing(percent=1.5),
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert '<a:lnSpc><a:spcPct val="150000"/></a:lnSpc>' in xml


def test_ppr_line_spacing_points_emits_spc_pts() -> None:
    """line_spacing(points=18.0) → <a:lnSpc><a:spcPts val="1800"/></a:lnSpc>."""
    para = TextParagraph(
        runs=(TextRun(text="x", font_family="Arial", size_pt=12),),
        line_spacing=LineSpacing(points=18.0),
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert '<a:lnSpc><a:spcPts val="1800"/></a:lnSpc>' in xml


def test_ppr_space_before_after_emits_spc_bef_aft() -> None:
    """space_before_pt=9 → <a:spcBef><a:spcPts val="900"/>; space_after_pt=18 → val="1800"."""
    para = TextParagraph(
        runs=(TextRun(text="x", font_family="Arial", size_pt=12),),
        space_before_pt=9.0,
        space_after_pt=18.0,
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert '<a:spcBef><a:spcPts val="900"/></a:spcBef>' in xml
    assert '<a:spcAft><a:spcPts val="1800"/></a:spcAft>' in xml


def test_ppr_mar_l_and_indent_emit_emu_attrs() -> None:
    """left_margin_pt=36 → marL="457200"; indent_pt=18 → indent="228600" (1pt=12700 EMU)."""
    para = TextParagraph(
        runs=(TextRun(text="x", font_family="Arial", size_pt=12),),
        left_margin_pt=36.0,  # 36 * 12700 = 457200
        indent_pt=18.0,  # 18 * 12700 = 228600
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert 'marL="457200"' in xml
    assert 'indent="228600"' in xml


def test_ppr_bu_char_emits_buchar_element() -> None:
    """CharBullet(char='•') → <a:buChar char="•"/>."""
    para = TextParagraph(
        runs=(TextRun(text="item", font_family="Arial", size_pt=12),),
        bullet=CharBullet(char="•"),
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert '<a:buChar char="&#x2022;"/>' in xml or '<a:buChar char="•"/>' in xml


def test_ppr_bu_autonum_emits_buautonum_element() -> None:
    """AutoNumberBullet(scheme='arabicPeriod') → <a:buAutoNum type="arabicPeriod" startAt="1"/>."""
    para = TextParagraph(
        runs=(TextRun(text="item", font_family="Arial", size_pt=12),),
        bullet=AutoNumberBullet(scheme="arabicPeriod"),
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    assert 'type="arabicPeriod"' in xml
    assert "a:buAutoNum" in xml


def test_ppr_child_order_lnspc_before_spcbef_before_buchar() -> None:
    """ECMA-376 child order: lnSpc < spcBef < spcAft < buChar within a:pPr."""
    para = TextParagraph(
        runs=(TextRun(text="item", font_family="Arial", size_pt=12),),
        line_spacing=LineSpacing(percent=1.2),
        space_before_pt=6.0,
        space_after_pt=3.0,
        bullet=CharBullet(char="•"),
    )
    xml = _slide_xml(build_pptx([_para_ir(para)], faces=[]))
    lnspc_pos = xml.find("<a:lnSpc>")
    spcbef_pos = xml.find("<a:spcBef>")
    spcaft_pos = xml.find("<a:spcAft>")
    buchar_pos = xml.find("<a:buChar")
    assert lnspc_pos < spcbef_pos < spcaft_pos < buchar_pos, (
        "ECMA child order violated: lnSpc must precede spcBef, spcAft, then buChar"
    )


def test_ppr_lvl_attr_emitted_for_nonzero_level() -> None:
    """level=2 → lvl="2" in a:pPr; level=0 → no lvl attr."""
    para_lvl2 = TextParagraph(
        runs=(TextRun(text="deep", font_family="Arial", size_pt=12),),
        level=2,
        bullet=CharBullet(char="•"),
    )
    para_lvl0 = TextParagraph(
        runs=(TextRun(text="top", font_family="Arial", size_pt=12),),
        level=0,
    )
    xml_lvl2 = _slide_xml(build_pptx([_para_ir(para_lvl2)], faces=[]))
    xml_lvl0 = _slide_xml(build_pptx([_para_ir(para_lvl0)], faces=[]))
    assert 'lvl="2"' in xml_lvl2
    assert 'lvl="0"' not in xml_lvl0
