"""Unit tests for font embedding (no fontconfig/browser needed for the generic paths)."""
# tests legitimately probe internal helpers
# pyright: reportPrivateUsage=false, reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportAttributeAccessIssue=false

from __future__ import annotations

import io
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fontTools import ttLib
from fontTools.fontBuilder import FontBuilder

from domoxml.core.fontconvert import to_embeddable_ttf
from domoxml.core.fonts import FontFace, load_faces
from domoxml.core.fontsread import (
    _deobfuscate,
    _guid_xor_key,
    _valid_magic,
    font_face_css,
    read_embedded_fonts,
)
from domoxml.core.ir.model import Box, ShapeNode, SlideIR, TextBody, TextParagraph, TextRun
from domoxml.core.opc import OpcPackage, write_package
from domoxml.presentation import pptx_to_html
from domoxml.slides import build_pptx, read_pptx_result
from domoxml.slides.pptx import _embedded_font_lst, _font_slot

_OTF = Path("/usr/share/fonts/opentype/inter/Inter-Thin.otf")

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


# ---------------------------------------------------------------------------
# Fixture: minimal TTF generator
# ---------------------------------------------------------------------------


def _make_ttf(*, family: str = "TestFont", fs_type: int = 0) -> bytes:
    """Build the smallest valid TrueType font with *family* and the given *fs_type*."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef"])
    fb.setupCharacterMap({})
    fb.setupGlyf({".notdef": ttLib.tables._g_l_y_f.Glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        sTypoLineGap=0,
        usWinAscent=800,
        usWinDescent=200,
        fsType=fs_type,
    )
    fb.setupPost()
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupHead(unitsPerEm=1000)
    buf = BytesIO()
    fb.font.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixture: minimal PPTX builder with an embedded font
# ---------------------------------------------------------------------------

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PML = "application/vnd.openxmlformats-officedocument.presentationml"
_PML_PRES = f"{_PML}.presentation.main+xml"
_PML_MASTER = f"{_PML}.slideMaster+xml"
_PML_LAYOUT = f"{_PML}.slideLayout+xml"
_PML_SLIDE = f"{_PML}.slide+xml"
_PML_THEME = "application/vnd.openxmlformats-officedocument.theme+xml"
_PML_RELS = "application/vnd.openxmlformats-package.relationships+xml"


def _content_types_xml() -> str:
    return (
        f'{_XML_DECL}<Types xmlns="{_CT_NS}">'
        f'<Default Extension="rels" ContentType="{_PML_RELS}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="fntdata" ContentType="application/x-fontdata"/>'
        '<Default Extension="odttf" ContentType="application/x-fontdata"/>'
        f'<Override PartName="/ppt/presentation.xml" ContentType="{_PML_PRES}"/>'
        f'<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="{_PML_MASTER}"/>'
        f'<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="{_PML_LAYOUT}"/>'
        f'<Override PartName="/ppt/theme/theme1.xml" ContentType="{_PML_THEME}"/>'
        f'<Override PartName="/ppt/slides/slide1.xml" ContentType="{_PML_SLIDE}"/>'
        "</Types>"
    )


def _pptx_with_embedded_font(
    font_data: bytes,
    *,
    family: str = "EmbedTest",
    part_name: str = "ppt/fonts/font1.fntdata",
    slot: str = "regular",
) -> bytes:
    """Build a minimal PPTX that embeds *font_data* under the given *part_name*."""
    from domoxml.slides._templates import (
        ROOT_RELS,
        SLIDE_LAYOUT,
        SLIDE_LAYOUT_RELS,
        SLIDE_MASTER,
        SLIDE_MASTER_RELS,
        THEME,
    )

    slide_xml = (
        f"{_XML_DECL}"
        f'<p:sld xmlns:p="{_P}"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        "</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )
    rel_target = part_name.removeprefix("ppt/")
    pres_xml = (
        f"{_XML_DECL}"
        f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
        '<p:sldSz cx="12192000" cy="6858000"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        "<p:embeddedFontLst>"
        "<p:embeddedFont>"
        f'<p:font typeface="{family}"/>'
        f'<p:{slot} r:id="rId3"/>'
        "</p:embeddedFont>"
        "</p:embeddedFontLst>"
        "</p:presentation>"
    )
    pres_rels = (
        f"{_XML_DECL}"
        f'<Relationships xmlns="{_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideMaster"'
        ' Target="slideMasters/slideMaster1.xml"/>'
        f'<Relationship Id="rId2" Type="{_R}/slide" Target="slides/slide1.xml"/>'
        f'<Relationship Id="rId3" Type="{_R}/font" Target="{rel_target}"/>'
        "</Relationships>"
    )
    slide_rels = (
        f"{_XML_DECL}"
        f'<Relationships xmlns="{_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideLayout"'
        ' Target="../slideLayouts/slideLayout1.xml"/>'
        "</Relationships>"
    )
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types_xml(),
        "_rels/.rels": ROOT_RELS,
        "ppt/presentation.xml": pres_xml,
        "ppt/_rels/presentation.xml.rels": pres_rels,
        "ppt/theme/theme1.xml": THEME,
        "ppt/slideMasters/slideMaster1.xml": SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": SLIDE_LAYOUT_RELS,
        "ppt/slides/slide1.xml": slide_xml,
        "ppt/slides/_rels/slide1.xml.rels": slide_rels,
        part_name: font_data,
    }
    return write_package(parts)


def _slide_with_font(family: str, *, bold: bool = False) -> SlideIR:
    return SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=100, height=100),
                text=TextBody(
                    paragraphs=(
                        TextParagraph(
                            runs=(TextRun(text="x", font_family=family, size_pt=24.0, bold=bold),)
                        ),
                    )
                ),
            ),
        ),
    )


def test_generic_families_are_never_resolved() -> None:
    assert load_faces([_slide_with_font("sans-serif")]) == []
    assert load_faces([_slide_with_font("monospace")]) == []


def test_multi_word_system_family_resolves() -> None:
    # Regression: token-splitting the fc-match family rejected every multi-word
    # family ("DejaVu Sans" is not a token of ["dejavu", "sans"]).
    from domoxml.core.fonts import _resolve_system_file  # pyright: ignore[reportPrivateUsage]

    if _resolve_system_file("DejaVu Sans", bold=False, italic=False) is None:
        pytest.skip("DejaVu Sans not installed")
    faces = load_faces([_slide_with_font("DejaVu Sans")])
    assert [f.family for f in faces] == ["DejaVu Sans"]


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


# ---------------------------------------------------------------------------
# Reverse-direction: ODTTF deobfuscation unit tests
# ---------------------------------------------------------------------------


def test_guid_xor_key_from_odttf_part_path() -> None:
    """GUID in a part path is decoded into the correct 16-byte XOR key."""
    # Data1 = 12345678 → stored little-endian: 78 56 34 12
    # Data2 = 1234 → stored LE: 34 12
    # Data3 = 5678 → stored LE: 78 56
    # Data4 = 9ABC → stored as-is (big-endian): 9A BC
    # Remaining bytes: DE F0 12 34 56 78 90 AB
    guid = "12345678-1234-5678-9ABC-DEF012345678"
    key = _guid_xor_key(f"ppt/fonts/{guid}.odttf")
    assert key is not None
    assert len(key) == 16
    # Verify Data1 bytes reversed
    assert key[0] == 0x78
    assert key[1] == 0x56
    assert key[2] == 0x34
    assert key[3] == 0x12
    # Data2 reversed
    assert key[4] == 0x34
    assert key[5] == 0x12
    # Data3 reversed
    assert key[6] == 0x78
    assert key[7] == 0x56
    # Data4 big-endian
    assert key[8] == 0x9A
    assert key[9] == 0xBC


def test_guid_xor_key_none_for_plain_fntdata() -> None:
    """No GUID in 'font1.fntdata' → returns None (plain TTF, no deobfuscation needed)."""
    assert _guid_xor_key("ppt/fonts/font1.fntdata") is None


def test_valid_magic_detects_ttf_otf_apple() -> None:
    assert _valid_magic(b"\x00\x01\x00\x00" + bytes(32))
    assert _valid_magic(b"OTTO" + bytes(32))
    assert _valid_magic(b"true" + bytes(32))
    assert not _valid_magic(b"\x00\x00\x00\x00" + bytes(32))


def test_odttf_deobfuscation_is_symmetric() -> None:
    """XOR is its own inverse: encrypt(decrypt(x)) == x."""
    guid = "AABBCCDD-1122-3344-AABB-CCDDEEFF0011"
    key = _guid_xor_key(f"ppt/fonts/{guid}.odttf")
    assert key is not None
    data = b"\x00\x01\x00\x00" + bytes(range(28)) + bytes(100)
    encrypted = _deobfuscate(data, key)
    assert encrypted[:4] != data[:4]  # magic is obscured
    decrypted = _deobfuscate(encrypted, key)
    assert decrypted == data  # round-trip recovers original


# ---------------------------------------------------------------------------
# Reverse-direction: plain TTF embedded font
# ---------------------------------------------------------------------------


def test_read_plain_embedded_font_from_pptx() -> None:
    """A plain (non-obfuscated) TTF stored in a .fntdata part is recovered correctly."""
    ttf = _make_ttf(family="EmbedTest")
    pptx = _pptx_with_embedded_font(ttf, family="EmbedTest")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    face = result.embedded_fonts[0]
    assert face.family == "EmbedTest"
    assert face.slot == "regular"
    assert face.data == ttf
    assert not result.warnings


def test_read_odttf_obfuscated_embedded_font() -> None:
    """An ODTTF-obfuscated font is correctly deobfuscated and recovered."""
    ttf = _make_ttf(family="ObfTest")
    guid = "DEADBEEF-CAFE-BABE-DEAD-BEEFCAFEBABE"
    part_name = f"ppt/fonts/{guid}.odttf"
    key = _guid_xor_key(part_name)
    assert key is not None
    obfuscated = _deobfuscate(ttf, key)
    assert not _valid_magic(obfuscated)  # magic is now hidden

    pptx = _pptx_with_embedded_font(obfuscated, family="ObfTest", part_name=part_name)
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    face = result.embedded_fonts[0]
    assert face.family == "ObfTest"
    assert face.data[:4] == b"\x00\x01\x00\x00"  # magic recovered
    assert not result.warnings


# ---------------------------------------------------------------------------
# Reverse-direction: restricted fsType → warning + skip
# ---------------------------------------------------------------------------


def test_restricted_fstype_emits_warning_and_skips_font() -> None:
    """A font with fsType=0x0002 (restricted) must emit a warning and not be emitted."""
    ttf = _make_ttf(family="RestrictedFont", fs_type=0x0002)
    pptx = _pptx_with_embedded_font(ttf, family="RestrictedFont")
    result = read_pptx_result(pptx)
    # No font face should be produced.
    assert len(result.embedded_fonts) == 0
    # A warning must be present mentioning the font and the restriction.
    assert len(result.warnings) == 1
    msg = result.warnings[0].message
    assert "restricted" in msg.lower()
    assert result.warnings[0].element == "RestrictedFont"


def test_editable_fstype_allows_font() -> None:
    """A font with fsType=0x0008 (editable embedding) is permitted."""
    ttf = _make_ttf(family="EditableFont", fs_type=0x0008)
    pptx = _pptx_with_embedded_font(ttf, family="EditableFont")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    assert not result.warnings


def test_installable_fstype_allows_font() -> None:
    """A font with fsType=0x0000 (installable embedding) is freely permitted."""
    ttf = _make_ttf(family="InstallFont", fs_type=0x0000)
    pptx = _pptx_with_embedded_font(ttf, family="InstallFont")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    assert not result.warnings


# ---------------------------------------------------------------------------
# Reverse-direction: bold/italic slots → correct @font-face weight/style
# ---------------------------------------------------------------------------


def test_bold_slot_produces_font_weight_700() -> None:
    ttf = _make_ttf(family="BoldTest")
    pptx = _pptx_with_embedded_font(ttf, family="BoldTest", slot="bold")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    assert result.embedded_fonts[0].slot == "bold"
    css = font_face_css(list(result.embedded_fonts))
    assert "font-weight:700" in css
    assert "font-style:normal" in css


def test_italic_slot_produces_font_style_italic() -> None:
    ttf = _make_ttf(family="ItalicTest")
    pptx = _pptx_with_embedded_font(ttf, family="ItalicTest", slot="italic")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    assert result.embedded_fonts[0].slot == "italic"
    css = font_face_css(list(result.embedded_fonts))
    assert "font-weight:400" in css
    assert "font-style:italic" in css


def test_bold_italic_slot_produces_correct_css() -> None:
    ttf = _make_ttf(family="BoldItalicTest")
    pptx = _pptx_with_embedded_font(ttf, family="BoldItalicTest", slot="boldItalic")
    result = read_pptx_result(pptx)
    assert len(result.embedded_fonts) == 1
    css = font_face_css(list(result.embedded_fonts))
    assert "font-weight:700" in css
    assert "font-style:italic" in css


def test_regular_slot_produces_weight_400_normal() -> None:
    ttf = _make_ttf(family="RegTest")
    pptx = _pptx_with_embedded_font(ttf, family="RegTest", slot="regular")
    result = read_pptx_result(pptx)
    css = font_face_css(list(result.embedded_fonts))
    assert "font-weight:400" in css
    assert "font-style:normal" in css


# ---------------------------------------------------------------------------
# Reverse-direction: pptx_to_html integration
# ---------------------------------------------------------------------------


def test_pptx_to_html_emits_font_face_css_and_asset() -> None:
    """pptx_to_html emits @font-face in shared CSS and the font bytes as an asset."""
    ttf = _make_ttf(family="HtmlTest")
    face = FontFace(family="HtmlTest", bold=False, italic=False, data=ttf)
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(ShapeNode(box=Box(x=0, y=0, width=100, height=100)),),
    )
    pptx = build_pptx([slide], faces=[face])
    html = pptx_to_html(pptx)

    assert "@font-face" in html.css
    assert '"HtmlTest"' in html.css
    assert "font-weight:400" in html.css
    assert "font-style:normal" in html.css

    font_assets = [a for a in html.assets if "fonts" in a.path]
    assert len(font_assets) == 1
    assert font_assets[0].path == "assets/fonts/HtmlTest-regular.ttf"
    assert font_assets[0].data == ttf
    assert not html.warnings


def test_pptx_to_html_restricted_font_warns_and_omits_asset() -> None:
    """A restricted font must not appear in assets and must produce a warning in html result."""
    ttf = _make_ttf(family="RestHTML", fs_type=0x0002)
    face = FontFace(family="RestHTML", bold=False, italic=False, data=ttf)
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(ShapeNode(box=Box(x=0, y=0, width=100, height=100)),),
    )
    pptx = build_pptx([slide], faces=[face])
    html = pptx_to_html(pptx)

    font_assets = [a for a in html.assets if "fonts" in a.path]
    assert len(font_assets) == 0
    assert len(html.warnings) == 1
    assert "restricted" in html.warnings[0].message.lower()


def test_read_embedded_fonts_no_font_lst() -> None:
    """Presentations without p:embeddedFontLst return empty lists, no warnings."""
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(ShapeNode(box=Box(x=0, y=0, width=100, height=100)),),
    )
    pptx = build_pptx([slide], faces=[])
    result = read_pptx_result(pptx)
    assert result.embedded_fonts == ()
    assert result.warnings == ()


def test_read_embedded_fonts_warns_on_missing_relationship() -> None:
    """A p:embeddedFont slot with a dangling rId emits a warning and is skipped."""
    from defusedxml import ElementTree

    pptx = _pptx_with_embedded_font(_make_ttf(), family="Dangler")
    pkg = OpcPackage.from_bytes(pptx)
    pres_part = "ppt/presentation.xml"
    root = ElementTree.fromstring(pkg.read(pres_part))
    # Patch: remove the actual font part from the package while keeping the XML reference.
    parts_dict = {p: pkg.read(p) for p in pkg.parts}
    del parts_dict["ppt/fonts/font1.fntdata"]
    pkg2 = OpcPackage(parts_dict)  # type: ignore[call-arg]
    faces, warnings = read_embedded_fonts(pkg2, root, pres_part)
    assert faces == []
    assert len(warnings) == 1
    assert "missing" in warnings[0].message.lower() or "not found" in warnings[0].message.lower()
