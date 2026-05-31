"""Normalise any font file to embeddable TrueType bytes, and read a face's identity.

OOXML font embedding (``embedTrueTypeFonts``) is TrueType-based: real PowerPoint refuses
CFF/OpenType (``.otf``) and compressed (woff/woff2) embeds. So we decompress woff/woff2 and
convert CFF outlines to quadratic ``glyf`` outlines (via fontTools' ``cu2qu``) before
embedding — no font format is silently dropped.
"""

# fontTools ships no type information; keep its dynamic surface from drowning strict mode.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false, reportAttributeAccessIssue=false
# pyright: reportArgumentType=false

from __future__ import annotations

from io import BytesIO

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

_MAX_ERR = 1.0  # max approximation error (font units) for cubic→quadratic conversion


def _glyphs_to_quadratic(glyph_set: object, max_err: float) -> dict[str, object]:
    quad: dict[str, object] = {}
    for name in list(glyph_set.keys()):  # type: ignore[attr-defined]
        tt_pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(tt_pen, max_err, reverse_direction=True))  # type: ignore[index]
        quad[name] = tt_pen.glyph()
    return quad


def _cff_to_glyf(font: TTFont) -> None:
    """Replace a font's CFF outlines with TrueType ``glyf`` outlines, in place."""
    glyph_order = font.getGlyphOrder()
    font["loca"] = newTable("loca")
    glyf = font["glyf"] = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = _glyphs_to_quadratic(font.getGlyphSet(), _MAX_ERR)
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    for name in glyph_order:
        glyf.glyphs[name].recalcBounds(glyf)  # TTGlyphPen output has no bbox yet

    # Promote maxp to TrueType (1.0): set the hint-zone fields (no TT instructions in a
    # CFF-derived font), then recalc fills the glyf-derived fields (maxPoints, maxContours…).
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for field, value in (
        ("maxZones", 1),
        ("maxTwilightPoints", 0),
        ("maxStorage", 0),
        ("maxFunctionDefs", 0),
        ("maxInstructionDefs", 0),
        ("maxStackElements", 0),
        ("maxSizeOfInstructions", 0),
    ):
        setattr(maxp, field, value)
    maxp.recalc(font)

    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = glyph_order
    font.sfntVersion = "\x00\x01\x00\x00"


def to_embeddable_ttf(data: bytes) -> bytes | None:
    """Return uncompressed TrueType bytes for ``data`` (ttf/otf/woff/woff2), or ``None`` if
    it can't be read or converted."""
    try:
        font = TTFont(BytesIO(data), fontNumber=0, recalcBBoxes=False, recalcTimestamp=False)
    except Exception:  # malformed/unsupported font: skip, never crash
        return None
    try:
        if font.sfntVersion == "OTTO" and "CFF " in font:
            _cff_to_glyf(font)
        if font.sfntVersion == "OTTO":
            return None  # CFF2/other OTTO we can't convert → don't emit a font Office refuses
        font.flavor = None  # strip woff/woff2 compression → bare sfnt
        buffer = BytesIO()
        font.save(buffer, reorderTables=False)
        return buffer.getvalue()
    except Exception:
        return None
    finally:
        font.close()


def face_identity(data: bytes) -> tuple[str, bool, bool] | None:
    """Read ``(family, bold, italic)`` from a font's name/OS2/head tables, or ``None``."""
    try:
        font = TTFont(BytesIO(data), fontNumber=0, lazy=True)
    except Exception:
        return None
    try:
        name_table = font["name"]
        family = name_table.getBestFamilyName() or name_table.getDebugName(1)
        if not family:
            return None
        bold = italic = False
        if "OS/2" in font:
            selection = font["OS/2"].fsSelection
            bold, italic = bool(selection & 0x20), bool(selection & 0x01)
        elif "head" in font:
            mac_style = font["head"].macStyle
            bold, italic = bool(mac_style & 0x1), bool(mac_style & 0x2)
        return str(family), bold, italic
    except Exception:
        return None
    finally:
        font.close()
