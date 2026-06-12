"""Parse embedded fonts from a PPTX package (reverse direction).

Office stores fonts in ``p:embeddedFontLst`` inside ``ppt/presentation.xml``.
Each ``p:embeddedFont`` element has up to four variant slots (regular, bold, italic,
boldItalic) that are relationship IDs pointing to ``.fntdata`` (or ``.odttf``) parts.

Two obfuscation states are handled:

* **Plain TTF/OTF** -- the part starts with the sfnt magic bytes (``\\x00\\x01\\x00\\x00``,
  ``OTTO``, or ``true``) and is used as-is.
* **ODTTF** -- Office XORs the first 32 bytes of the font with the 16-byte GUID derived
  from the part's filename, applied twice (once for each 16-byte block).  The GUID is
  encoded in the part name as ``{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`` or as a bare
  hex string; the byte order follows the Windows ``GUID`` struct layout
  (little-endian int32, int16, int16, then 8 bytes big-endian).

After deobfuscation the magic bytes are validated.  If the font's OS/2 ``fsType`` field
marks the embed as **restricted** (bit 1 set, bits 2-3 clear) a :class:`ConversionWarning`
is emitted and the font is skipped -- we conservatively respect the license flag rather than
leaking a font the rights-holder blocked.
"""

# fontTools ships no type stubs; suppress strict-mode noise.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false, reportAttributeAccessIssue=false
# pyright: reportArgumentType=false

from __future__ import annotations

import re
import struct
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element

from fontTools.ttLib import TTFont

from domoxml.core.opc import OpcPackage
from domoxml.types import ConversionWarning

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"p": _P, "r": _R}
_EMBED = f"{{{_R}}}id"

# Font binary magic bytes that indicate a valid (deobfuscated) sfnt stream.
_TTF_MAGIC = b"\x00\x01\x00\x00"  # TrueType
_OTF_MAGIC = b"OTTO"  # CFF/OpenType
_APPLE_MAGIC = b"true"  # Apple TrueType
_VALID_MAGICS = (_TTF_MAGIC, _OTF_MAGIC, _APPLE_MAGIC)

# GUID regex — matches bare or braced form in a part-path stem.
_GUID_RE = re.compile(
    r"\{?([0-9A-Fa-f]{8})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})"
    r"-([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})"
    r"-([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})"
    r"([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})\}?"
)

# Slot names → CSS font-weight / font-style
_SLOT_CSS: dict[str, tuple[str, str]] = {
    "regular": ("400", "normal"),
    "bold": ("700", "normal"),
    "italic": ("400", "italic"),
    "boldItalic": ("700", "italic"),
}

_FONT_REL_TYPE = f"{_R}/font"


class ReverseFontFace:
    """One usable font face recovered from a PPTX embedded-font part."""

    __slots__ = ("data", "family", "slot")

    def __init__(self, family: str, slot: str, data: bytes) -> None:
        self.family = family
        self.slot = slot  # one of "regular", "bold", "italic", "boldItalic"
        self.data = data  # plain TTF bytes (already deobfuscated if needed)


# ---------------------------------------------------------------------------
# GUID → XOR key
# ---------------------------------------------------------------------------


def _guid_xor_key(part_path: str) -> bytes | None:
    """Derive the 16-byte ODTTF XOR key from a part path containing a GUID.

    Returns ``None`` when no GUID is found in the stem (plain TTF part).
    The byte order follows the Windows GUID struct: the first three components
    are stored little-endian (reversed), the final eight bytes are big-endian.
    """
    stem = PurePosixPath(part_path).stem
    m = _GUID_RE.search(stem)
    if m is None:
        return None
    # Components: (Data1 as 8 hex) (Data2 4) (Data3 4) (Data4[0] 2) (Data4[1] 2) ...
    data1 = int(m.group(1), 16)  # 32-bit, stored LE
    data2 = int(m.group(2), 16)  # 16-bit, stored LE
    data3 = int(m.group(3), 16)  # 16-bit, stored LE
    # remaining bytes are big-endian (no swap)
    data4 = bytes(int(m.group(i), 16) for i in range(4, 12))
    return struct.pack("<IHH", data1, data2, data3) + data4


# ---------------------------------------------------------------------------
# Deobfuscation
# ---------------------------------------------------------------------------


def _deobfuscate(data: bytes, key: bytes) -> bytes:
    """XOR the first 32 bytes of *data* with *key* (16 bytes repeated twice)."""
    if len(data) < 32:  # too short to be a real font — return as-is; validation will reject
        return data
    key32 = key + key  # 32 bytes
    head = bytes(b ^ k for b, k in zip(data[:32], key32, strict=True))
    return head + data[32:]


# ---------------------------------------------------------------------------
# Magic-byte validation
# ---------------------------------------------------------------------------


def _valid_magic(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] in _VALID_MAGICS


# ---------------------------------------------------------------------------
# OS/2 fsType permission check
# ---------------------------------------------------------------------------


def _is_restricted(data: bytes) -> bool:
    """Return ``True`` when the font's OS/2 ``fsType`` marks it as restricted-license.

    Conservative policy: restricted if bit 1 (0x0002) is set **and** neither the
    editable-embedding (0x0008) nor print-and-preview (0x0004) bits are set.  A value of
    0x0000 (installable) and any value with 0x0008 or 0x0004 set are permitted.
    """
    try:
        font = TTFont(BytesIO(data), fontNumber=0, lazy=True)
    except Exception:
        return False  # can't read → let downstream handle
    try:
        if "OS/2" not in font:
            return False
        fs_type: int = font["OS/2"].fsType
        # Mask to the embedding-permission bits only (ignore bitmap-only flag 0x0200).
        perm_bits = fs_type & 0x000E
        return perm_bits == 0x0002  # restricted and nothing higher
    except Exception:
        return False
    finally:
        font.close()


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def read_embedded_fonts(
    package: OpcPackage,
    presentation_root: Element,
    presentation_part: str,
) -> tuple[list[ReverseFontFace], list[ConversionWarning]]:
    """Parse ``p:embeddedFontLst`` and recover each usable font face.

    For each ``p:embeddedFont/p:{slot}`` element the corresponding font part is read,
    deobfuscated if necessary, validated, and checked for embedding permissions.
    Returns ``(faces, warnings)``; warnings cover both license-restricted fonts and
    parts that couldn't be parsed.
    """
    faces: list[ReverseFontFace] = []
    warnings: list[ConversionWarning] = []

    font_lst = presentation_root.find("p:embeddedFontLst", _NS)
    if font_lst is None:
        return faces, warnings

    for embedded in font_lst.findall("p:embeddedFont", _NS):
        font_elem = embedded.find("p:font", _NS)
        family = font_elem.get("typeface", "") if font_elem is not None else ""
        if not family:
            warnings.append(
                ConversionWarning(
                    message="embedded font entry has no typeface name; skipped",
                    element="embeddedFont",
                )
            )
            continue

        for slot in ("regular", "bold", "italic", "boldItalic"):
            slot_elem = embedded.find(f"p:{slot}", _NS)
            if slot_elem is None:
                continue
            rid = slot_elem.get(_EMBED)
            if rid is None:
                continue

            # Resolve the relationship to a part path.
            try:
                part = package.related_part(presentation_part, rid)
            except KeyError:
                warnings.append(
                    ConversionWarning(
                        message=(
                            f"embedded font '{family}' ({slot}): "
                            f"relationship {rid!r} not found; skipped"
                        ),
                        element=family,
                    )
                )
                continue

            # Read the raw bytes.
            try:
                raw = package.read(part)
            except KeyError:
                warnings.append(
                    ConversionWarning(
                        message=(
                            f"embedded font '{family}' ({slot}): part {part!r} missing; skipped"
                        ),
                        element=family,
                    )
                )
                continue

            # Detect and apply ODTTF deobfuscation.
            if not _valid_magic(raw):
                key = _guid_xor_key(part)
                if key is None:
                    warnings.append(
                        ConversionWarning(
                            message=(
                                f"embedded font '{family}' ({slot}): invalid magic bytes "
                                "and no GUID in part name for deobfuscation; skipped"
                            ),
                            element=family,
                        )
                    )
                    continue
                raw = _deobfuscate(raw, key)
                if not _valid_magic(raw):
                    warnings.append(
                        ConversionWarning(
                            message=(
                                f"embedded font '{family}' ({slot}): "
                                "invalid font bytes after ODTTF deobfuscation; skipped"
                            ),
                            element=family,
                        )
                    )
                    continue

            # Respect OS/2 embedding permissions.
            if _is_restricted(raw):
                warnings.append(
                    ConversionWarning(
                        message=(
                            f"embedded font '{family}' ({slot}): "
                            "fsType marks this font as restricted-license; not emitted"
                        ),
                        element=family,
                    )
                )
                continue

            faces.append(ReverseFontFace(family=family, slot=slot, data=raw))

    return faces, warnings


# ---------------------------------------------------------------------------
# CSS @font-face generation
# ---------------------------------------------------------------------------


def font_face_css(faces: list[ReverseFontFace]) -> str:
    """Emit ``@font-face`` rules for *faces*; empty string when the list is empty."""
    rules: list[str] = []
    for face in faces:
        weight, style = _SLOT_CSS.get(face.slot, ("400", "normal"))
        rules.append(
            f"@font-face{{"
            f"font-family:{_css_string(face.family)};"
            f"src:url(../assets/fonts/{font_asset_name(face)});"
            f"font-weight:{weight};"
            f"font-style:{style}"
            f"}}"
        )
    return "".join(rules)


def _css_string(value: str) -> str:
    """Wrap a CSS string value in double-quotes, escaping embedded quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def font_asset_name(face: ReverseFontFace) -> str:
    """Stable asset filename for a font face: ``{family}-{slot}.ttf``."""
    safe_family = re.sub(r"[^A-Za-z0-9_-]", "_", face.family)
    return f"{safe_family}-{face.slot}.ttf"
