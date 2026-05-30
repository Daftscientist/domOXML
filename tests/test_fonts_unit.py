"""Unit tests for font embedding (no fontconfig/browser needed for the generic paths)."""
# tests legitimately probe internal helpers
# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from domoxml.core.fontconvert import to_embeddable_ttf
from domoxml.core.fonts import FontFace, load_faces
from domoxml.core.ir.model import Box, ShapeNode, SlideIR, TextRun
from domoxml.slides import build_pptx
from domoxml.slides.pptx import _embedded_font_lst, _font_slot

_OTF = Path("/usr/share/fonts/opentype/inter/Inter-Thin.otf")


def _slide_with_font(family: str, *, bold: bool = False) -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=100, height=100),
                text=TextRun(text="x", font_family=family, size_pt=24.0, bold=bold),
            ),
        ),
    )


def test_generic_families_are_never_resolved() -> None:
    assert load_faces([_slide_with_font("sans-serif")]) == []
    assert load_faces([_slide_with_font("monospace")]) == []


def test_generic_font_deck_embeds_nothing() -> None:
    data = build_pptx([_slide_with_font("sans-serif")])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert not any(name.startswith("ppt/fonts/") for name in archive.namelist())
        presentation = archive.read("ppt/presentation.xml").decode()
    assert "embeddedFontLst" not in presentation
    assert "embedTrueTypeFonts" not in presentation


def test_font_slot_mapping() -> None:
    def face(bold: bool, italic: bool) -> FontFace:
        return FontFace(family="X", bold=bold, italic=italic, data=b"")

    assert _font_slot(face(False, False)) == "regular"
    assert _font_slot(face(True, False)) == "bold"
    assert _font_slot(face(False, True)) == "italic"
    assert _font_slot(face(True, True)) == "boldItalic"


def test_embedded_font_lst_groups_variants_by_family() -> None:
    regular = FontFace(family="Inter", bold=False, italic=False, data=b"")
    bold = FontFace(family="Inter", bold=True, italic=False, data=b"")
    xml = _embedded_font_lst(
        [(regular, "ppt/fonts/font1.fntdata", "rId5"), (bold, "ppt/fonts/font2.fntdata", "rId6")]
    )
    assert xml.count("<p:embeddedFont>") == 1  # one family, two variant slots
    assert '<p:font typeface="Inter"/>' in xml
    assert '<p:regular r:id="rId5"/>' in xml
    assert '<p:bold r:id="rId6"/>' in xml


def test_embedded_font_lst_empty() -> None:
    assert _embedded_font_lst([]) == ""


def test_otf_is_converted_to_glyf_truetype() -> None:
    # OOXML embedding is TrueType-only; a CFF/OTF must come out as a glyf-flavoured TTF or
    # real Office rejects the deck. (Skips if the test font isn't installed.)
    if not _OTF.is_file():
        pytest.skip("Inter OTF not installed")
    ttf = to_embeddable_ttf(_OTF.read_bytes())
    assert ttf is not None
    assert ttf[:4] == b"\x00\x01\x00\x00"  # TrueType sfnt version, not 'OTTO'

    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(ttf))
    assert "glyf" in font and "CFF " not in font
    font.close()
