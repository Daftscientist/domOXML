"""PowerPoint's built-in table styles, resolved to a fill, text colour and borders per cell.

A deck names a built-in style by GUID (``a:tableStyleId``) and its definition lives only inside
PowerPoint, so every consumer carries its own catalogue. This one holds the 11 family templates
and the 74 GUIDs that PowerPoint ships (a family times its accent variants), as public facts
about PowerPoint's styles. A cell takes each property from the highest-priority region that sets
it: last column, first column, last row, first row, banding, then the whole table.

Tints and shades are blended in linear light, which is what PowerPoint draws (the neutral
Medium Style 2 body comes out ``E7E7E7`` and its band ``CBCBCB``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from domoxml.core.ir.model import Line, Rgba, SideLines

_BORDER_EMU = 12_700  # 1 pt, the width every built-in style draws its lines at


@dataclass(frozen=True)
class _Fill:
    ref: str
    tint: float | None = None  # share of the colour kept; the rest is white
    shade: float | None = None  # share of the colour kept; the rest is black
    over: str | None = None  # the colour this one is laid over, at ``alpha`` opacity
    alpha: float = 1.0


@dataclass(frozen=True)
class _Region:
    fill: _Fill | None = None
    text: str | None = None
    top: str | None = None
    bottom: str | None = None
    left: str | None = None
    right: str | None = None
    inside_h: str | None = None
    inside_v: str | None = None


@dataclass(frozen=True)
class _Style:
    whole: _Region = field(default_factory=_Region)
    first_row: _Region = field(default_factory=_Region)
    last_row: _Region = field(default_factory=_Region)
    first_col: _Region = field(default_factory=_Region)
    last_col: _Region = field(default_factory=_Region)
    band_h: _Region = field(default_factory=_Region)
    band_v: _Region = field(default_factory=_Region)


@dataclass(frozen=True)
class ResolvedCellStyle:
    """What a built-in style gives one cell."""

    fill: Rgba | None
    text: Rgba | None
    borders: SideLines | None
    bold: bool


_GUIDS: dict[str, tuple[str, str]] = {
    # Themed Style 1 and 2
    "{2D5ABB26-0587-4C30-8999-92F81FD0307C}": ("themed1", ""),
    "{3C2FFA5D-87B4-456A-9821-1D502468CF0F}": ("themed1", "accent1"),
    "{284E427A-3D55-4303-BF80-6455036E1DE7}": ("themed1", "accent2"),
    "{69C7853C-536D-4A76-A0AE-DD22124D55A5}": ("themed1", "accent3"),
    "{775DCB02-9BB8-47FD-8907-85C794F793BA}": ("themed1", "accent4"),
    "{35758FB7-9AC5-4552-8A53-C91805E547FA}": ("themed1", "accent5"),
    "{08FB837D-C827-4EFA-A057-4D05807E0F7C}": ("themed1", "accent6"),
    "{5940675A-B579-460E-94D1-54222C63F5DA}": ("themed2", ""),
    "{D113A9D2-9D6B-4929-AA2D-F23B5EE8CBE7}": ("themed2", "accent1"),
    "{18603FDC-E32A-4AB5-989C-0864C3EAD2B8}": ("themed2", "accent2"),
    "{306799F8-075E-4A3A-A7F6-7FBC6576F1A4}": ("themed2", "accent3"),
    "{E269D01E-BC32-4049-B463-5C60D7B0CCD2}": ("themed2", "accent4"),
    "{327F97BB-C833-4FB7-BDE5-3F7075034690}": ("themed2", "accent5"),
    "{638B1855-1B75-4FBE-930C-398BA8C253C6}": ("themed2", "accent6"),
    # Light Style 1, 2 and 3
    "{9D7B26C5-4107-4FEC-AEDC-1716B250A1EF}": ("light1", ""),
    "{3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5}": ("light1", "accent1"),
    "{0E3FDE45-AF77-4B5C-9715-49D594BDF05E}": ("light1", "accent2"),
    "{C083E6E3-FA7D-4D7B-A595-EF9225AFEA82}": ("light1", "accent3"),
    "{D27102A9-8310-4765-A935-A1911B00CA55}": ("light1", "accent4"),
    "{5FD0F851-EC5A-4D38-B0AD-8093EC10F338}": ("light1", "accent5"),
    "{68D230F3-CF80-4859-8CE7-A43EE81993B5}": ("light1", "accent6"),
    "{7E9639D4-E3E2-4D34-9284-5A2195B3D0D7}": ("light2", ""),
    "{69012ECD-51FC-41F1-AA8D-1B2483CD663E}": ("light2", "accent1"),
    "{72833802-FEF1-4C79-8D5D-14CF1EAF98D9}": ("light2", "accent2"),
    "{F2DE63D5-997A-4646-A377-4702673A728D}": ("light2", "accent3"),
    "{17292A2E-F333-43FB-9621-5CBBE7FDCDCB}": ("light2", "accent4"),
    "{5A111915-BE36-4E01-A7E5-04B1672EAD32}": ("light2", "accent5"),
    "{912C8C85-51F0-491E-9774-3900AFEF0FD7}": ("light2", "accent6"),
    "{616DA210-FB5B-4158-B5E0-FEB733F419BA}": ("light3", ""),
    "{BC89EF96-8CEA-46FF-86C4-4CE0E7609802}": ("light3", "accent1"),
    "{5DA37D80-6434-44D0-A028-1B22A696006F}": ("light3", "accent2"),
    "{8799B23B-EC83-4686-B30A-512413B5E67A}": ("light3", "accent3"),
    "{ED083AE6-46FA-4A59-8FB0-9F97EB10719F}": ("light3", "accent4"),
    "{BDBED569-4797-4DF1-A0F4-6AAB3CD982D8}": ("light3", "accent5"),
    "{E8B1032C-EA38-4F05-BA0D-38AFFFC7BED3}": ("light3", "accent6"),
    # Medium Style 1, 2, 3 and 4
    "{793D81CF-94F2-401A-BA57-92F5A7B2D0C5}": ("medium1", ""),
    "{B301B821-A1FF-4177-AEE7-76D212191A09}": ("medium1", "accent1"),
    "{9DCAF9ED-07DC-4A11-8D7F-57B35C25682E}": ("medium1", "accent2"),
    "{1FECB4D8-DB02-4DC6-A0A2-4F2EBAE1DC90}": ("medium1", "accent3"),
    "{1E171933-4619-4E11-9A3F-F7608DF75F80}": ("medium1", "accent4"),
    "{FABFCF23-3B69-468F-B69F-88F6DE6A72F2}": ("medium1", "accent5"),
    "{10A1B5D5-9B99-4C35-A422-299274C87663}": ("medium1", "accent6"),
    "{073A0DAA-6AF3-43AB-8588-CEC1D06C72B9}": ("medium2", ""),
    "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}": ("medium2", "accent1"),
    "{21E4AEA4-8DFA-4A89-87EB-49C32662AFE0}": ("medium2", "accent2"),
    "{F5AB1C69-6EDB-4FF4-983F-18BD219EF322}": ("medium2", "accent3"),
    "{00A15C55-8517-42AA-B614-E9B94910E393}": ("medium2", "accent4"),
    "{7DF18680-E054-41AD-8BC1-D1AEF772440D}": ("medium2", "accent5"),
    "{93296810-A885-4BE3-A3E7-6D5BEEA58F35}": ("medium2", "accent6"),
    "{8EC20E35-A176-4012-BC5E-935CFFF8708E}": ("medium3", ""),
    "{6E25E649-3F16-4E02-A733-19D2CDBF48F0}": ("medium3", "accent1"),
    "{85BE263C-DBD7-4A20-BB59-AAB30ACAA65A}": ("medium3", "accent2"),
    "{EB344D84-9AFB-497E-A393-DC336BA19D2E}": ("medium3", "accent3"),
    "{EB9631B5-78F2-41C9-869B-9F39066F8104}": ("medium3", "accent4"),
    "{74C1A8A3-306A-4EB7-A6B1-4F7E0EB9C5D6}": ("medium3", "accent5"),
    "{2A488322-F2BA-4B5B-9748-0D474271808F}": ("medium3", "accent6"),
    "{D7AC3CCA-C797-4891-BE02-D94E43425B78}": ("medium4", ""),
    "{69CF1AB2-1976-4502-BF36-3FF5EA218861}": ("medium4", "accent1"),
    "{8A107856-5554-42FB-B03E-39F5DBC370BA}": ("medium4", "accent2"),
    "{0505E3EF-67EA-436B-97B2-0124C06EBD24}": ("medium4", "accent3"),
    "{C4B1156A-380E-4F78-BDF5-A606A8083BF9}": ("medium4", "accent4"),
    "{22838BEF-8BB2-4498-84A7-C5851F593DF1}": ("medium4", "accent5"),
    "{16D9F66E-5EB9-4882-86FB-DCBF35E3C3E4}": ("medium4", "accent6"),
    # Dark Style 1 and 2 (the second only has the neutral variant and accents 1, 3 and 5)
    "{E8034E78-7F5D-4C2E-B375-FC64B27BC917}": ("dark1", ""),
    "{125E5076-3810-47DD-B79F-674D7AD40C01}": ("dark1", "accent1"),
    "{37CE84F3-28C3-443E-9E96-99CF82512B78}": ("dark1", "accent2"),
    "{D03447BB-5D67-496B-8E87-E561075AD55C}": ("dark1", "accent3"),
    "{E929F9F4-4A8F-4326-A1B4-22849713DDAB}": ("dark1", "accent4"),
    "{8FD4443E-F989-4FC4-A0C8-D5A2AF1F390B}": ("dark1", "accent5"),
    "{AF606853-7671-496A-8E4F-DF71F8EC918B}": ("dark1", "accent6"),
    "{5202B0CA-FC54-4496-8BCA-5EF66A818D29}": ("dark2", ""),
    "{0660B408-B3CF-4A94-85FC-2B1E0A45F4A2}": ("dark2", "accent1"),
    "{91EBBBCC-DAD2-459C-BE2E-F6DE35CF9A28}": ("dark2", "accent3"),
    "{46F890A9-2807-4EBB-B81D-B2AA78EC7F39}": ("dark2", "accent5"),
}


def _themed1(accent: str) -> _Style:
    if not accent:
        return _Style(whole=_Region(text="tx1"))
    return _Style(
        whole=_Region(
            top=accent,
            bottom=accent,
            left=accent,
            right=accent,
            inside_h=accent,
            inside_v=accent,
            text="dk1",
        ),
        first_row=_Region(
            top=accent, bottom="lt1", left=accent, right=accent, fill=_Fill(accent), text="lt1"
        ),
        last_row=_Region(top=accent, bottom=accent, left=accent, right=accent),
        first_col=_Region(top=accent, bottom=accent, left=accent, right=accent, inside_h=accent),
        last_col=_Region(top=accent, bottom=accent, left=accent, right=accent, inside_h=accent),
        band_h=_Region(fill=_Fill(accent, tint=0.4)),
        band_v=_Region(fill=_Fill(accent, tint=0.4)),
    )


def _themed2(accent: str) -> _Style:
    ink = accent or "tx1"
    if not accent:
        return _Style(
            whole=_Region(
                top=ink, bottom=ink, left=ink, right=ink, inside_h="tx1", inside_v="tx1", text="dk1"
            )
        )
    return _Style(
        whole=_Region(top=ink, bottom=ink, left=ink, right=ink, fill=_Fill(accent), text="lt1"),
        first_row=_Region(bottom="lt1", text="lt1"),
        last_row=_Region(top="lt1"),
        first_col=_Region(right="lt1"),
        last_col=_Region(left="lt1"),
        # White at 20% opacity over the accent: a light tint of it, not opaque white.
        band_h=_Region(fill=_Fill("lt1", over=accent, alpha=0.2)),
        band_v=_Region(fill=_Fill("lt1", over=accent, alpha=0.2)),
    )


def _light1(accent: str) -> _Style:
    ink = accent or "tx1"
    band = _Region(fill=_Fill(ink, tint=0.4))  # measured in PowerPoint: a CBCBCB band on black
    return _Style(
        whole=_Region(top=ink, bottom=ink, text="tx1"),
        first_row=_Region(bottom=ink, text="tx1"),
        last_row=_Region(top=ink),
        last_col=_Region(text="tx1"),
        band_h=band,
        band_v=band,
    )


def _light2(accent: str) -> _Style:
    ink = accent or "tx1"
    return _Style(
        whole=_Region(
            top=ink, bottom=ink, left=ink, right=ink, inside_h=ink, inside_v=ink, text="tx1"
        ),
        first_row=_Region(fill=_Fill(ink), text="bg1"),
        last_row=_Region(top=ink),
    )


def _light3(accent: str) -> _Style:
    ink = accent or "tx1"
    band = _Region(fill=_Fill(ink, tint=0.4))  # measured, like Light Style 1
    return _Style(
        whole=_Region(
            top=ink, bottom=ink, left=ink, right=ink, inside_h=ink, inside_v=ink, text="tx1"
        ),
        first_row=_Region(bottom=ink, text=ink),
        last_row=_Region(top=ink),
        band_h=band,
        band_v=band,
    )


def _medium1(accent: str) -> _Style:
    ink = accent or "dk1"
    band = _Region(fill=_Fill(ink, tint=0.2))
    return _Style(
        whole=_Region(
            top=ink, bottom=ink, left=ink, right=ink, inside_h=ink, fill=_Fill("lt1"), text="dk1"
        ),
        first_row=_Region(fill=_Fill(ink), text="lt1"),
        last_row=_Region(top=ink, fill=_Fill("lt1")),
        band_h=band,
        band_v=band,
    )


def _medium2(accent: str) -> _Style:
    ink = accent or "dk1"
    solid = _Region(fill=_Fill(ink), text="lt1")
    band = _Region(fill=_Fill(ink, tint=0.4))
    return _Style(
        whole=_Region(
            top="lt1",
            bottom="lt1",
            left="lt1",
            right="lt1",
            inside_h="lt1",
            inside_v="lt1",
            fill=_Fill(ink, tint=0.2),
            text="dk1",
        ),
        first_row=_Region(fill=_Fill(ink), text="lt1", bottom="lt1@38100"),
        last_row=_Region(fill=_Fill(ink), text="lt1", top="lt1@38100"),
        first_col=solid,
        last_col=solid,
        band_h=band,
        band_v=band,
    )


def _medium3(accent: str) -> _Style:
    ink = accent or "dk1"
    solid = _Region(fill=_Fill(ink), text="lt1")
    band = _Region(fill=_Fill("dk1", tint=0.2))
    return _Style(
        whole=_Region(top="dk1", bottom="dk1", fill=_Fill("lt1"), text="dk1"),
        first_row=_Region(bottom="dk1", fill=_Fill(ink), text="lt1"),
        last_row=_Region(top="dk1", fill=_Fill("lt1")),
        first_col=solid,
        last_col=solid,
        band_h=band,
        band_v=band,
    )


def _medium4(accent: str) -> _Style:
    ink = accent or "dk1"
    pale = _Fill(ink, tint=0.2)
    band = _Region(fill=_Fill(ink, tint=0.4))
    return _Style(
        whole=_Region(
            top=ink,
            bottom=ink,
            left=ink,
            right=ink,
            inside_h=ink,
            inside_v=ink,
            fill=pale,
            text="dk1",
        ),
        first_row=_Region(fill=pale, text=ink),
        last_row=_Region(top="dk1", fill=pale),
        band_h=band,
        band_v=band,
    )


def _dark1(accent: str) -> _Style:
    ink = accent or "dk1"

    def tone(amount: float) -> _Fill:
        # Without an accent the neutral tones are tints of dk1; with one they are shades of it.
        return _Fill(ink, shade=amount) if accent else _Fill(ink, tint=amount)

    return _Style(
        whole=_Region(fill=tone(0.2), text="lt1"),  # measured: white text on the pale body
        first_row=_Region(bottom="lt1", fill=_Fill("dk1"), text="lt1"),
        last_row=_Region(top="lt1", fill=_Fill(ink)),
        first_col=_Region(right="lt1", fill=tone(0.6)),
        last_col=_Region(left="lt1", fill=tone(0.6)),
        band_h=_Region(fill=tone(0.4)),
        band_v=_Region(fill=tone(0.4)),
    )


_PAIRED_HEADER = {"accent1": "accent2", "accent3": "accent4", "accent5": "accent6"}


def _dark2(accent: str) -> _Style:
    ink = accent or "dk1"
    pale = _Fill(ink, tint=0.2)
    band = _Region(fill=_Fill(ink, tint=0.4))
    return _Style(
        whole=_Region(fill=pale, text="dk1"),
        first_row=_Region(fill=_Fill(_PAIRED_HEADER.get(accent, "dk1")), text="lt1"),
        last_row=_Region(top="dk1", fill=pale),
        band_h=band,
        band_v=band,
    )


_FAMILIES = {
    "themed1": _themed1,
    "themed2": _themed2,
    "light1": _light1,
    "light2": _light2,
    "light3": _light3,
    "medium1": _medium1,
    "medium2": _medium2,
    "medium3": _medium3,
    "medium4": _medium4,
    "dark1": _dark1,
    "dark2": _dark2,
}
_ROLES = {"tx1": "dk1", "tx2": "dk2", "bg1": "lt1", "bg2": "lt2"}
_FALLBACK = {"dk1": "000000", "lt1": "FFFFFF"}


def is_builtin(style_id: str) -> bool:
    """Whether ``style_id`` is one of PowerPoint's built-in table styles."""
    return style_id.upper() in _GUIDS


def _colour(ref: str, colors: Mapping[str, str]) -> Rgba | None:
    value = colors.get(ref) or colors.get(_ROLES.get(ref, "")) or _FALLBACK.get(ref, "")
    if len(value) != 6:
        return None
    try:
        return Rgba(r=int(value[:2], 16), g=int(value[2:4], 16), b=int(value[4:], 16))
    except ValueError:
        return None


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _encoded(channel: float) -> int:
    value = channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return round(max(0.0, min(1.0, value)) * 255)


def _blend(color: Rgba, kept: float, toward: float) -> Rgba:
    """``color`` kept at ``kept`` of its light and the rest ``toward`` (1 white, 0 black)."""
    return Rgba(
        r=_encoded(_linear(color.r) * kept + toward * (1 - kept)),
        g=_encoded(_linear(color.g) * kept + toward * (1 - kept)),
        b=_encoded(_linear(color.b) * kept + toward * (1 - kept)),
        a=color.a,
    )


def _fill(spec: _Fill | None, colors: Mapping[str, str]) -> Rgba | None:
    if spec is None:
        return None
    base = _colour(spec.ref, colors)
    if base is None:
        return None
    if spec.over is not None:
        under = _colour(spec.over, colors)
        if under is None:
            return base
        mixed = [
            round(top * spec.alpha + low * (1 - spec.alpha))
            for top, low in ((base.r, under.r), (base.g, under.g), (base.b, under.b))
        ]
        return Rgba(r=mixed[0], g=mixed[1], b=mixed[2])
    if spec.tint is not None:
        return _blend(base, spec.tint, 1.0)
    if spec.shade is not None:
        return _blend(base, spec.shade, 0.0)
    return base


def resolve_cell_style(
    style_id: str,
    *,
    row: int,
    column: int,
    rows: int,
    columns: int,
    flags: Mapping[str, bool],
    colors: Mapping[str, str],
    column_span: int = 1,
    row_span: int = 1,
) -> ResolvedCellStyle | None:
    """The built-in style's fill, text colour, borders and bold for one cell, or ``None``.

    ``flags`` holds the table's ``firstRow``, ``lastRow``, ``firstCol``, ``lastCol``, ``bandRow``
    and ``bandCol`` switches. ``None`` means the id is not a built-in style.
    """
    named = _GUIDS.get(style_id.upper())
    if named is None:
        return None
    style = _FAMILIES[named[0]](named[1])
    first_row = flags.get("firstRow", False) and row == 0
    # A merged cell that reaches the last row or column is in those regions too.
    reaches_bottom = row + row_span - 1 >= rows - 1
    reaches_right = column + column_span - 1 >= columns - 1
    last_row = flags.get("lastRow", False) and reaches_bottom
    first_col = flags.get("firstCol", False) and column == 0
    last_col = flags.get("lastCol", False) and reaches_right
    stack = [style.whole]
    body_row = row - (1 if flags.get("firstRow", False) else 0)
    body_col = column - (1 if flags.get("firstCol", False) else 0)
    if flags.get("bandCol", False) and not first_col and not last_col and body_col % 2 == 0:
        stack.append(style.band_v)
    if (
        flags.get("bandRow", False)
        and not first_row
        and not last_row
        and body_row >= 0
        and body_row % 2 == 0
    ):
        stack.append(style.band_h)
    for active, region in (
        (first_row, style.first_row),
        (last_row, style.last_row),
        (first_col, style.first_col),
        (last_col, style.last_col),
    ):
        if active:
            stack.append(region)

    fill: _Fill | None = None
    text: str | None = None
    edges: dict[str, str | None] = {}
    for region in stack:
        fill = region.fill or fill
        text = region.text or text
        for name in ("top", "bottom", "left", "right", "inside_h", "inside_v"):
            value = getattr(region, name)
            if value is not None:
                edges[name] = value
    top = edges.get("top") if row == 0 else edges.get("inside_h")
    bottom = edges.get("bottom") if reaches_bottom else edges.get("inside_h")
    left = edges.get("left") if column == 0 else edges.get("inside_v")
    right = edges.get("right") if reaches_right else edges.get("inside_v")
    # A header's bottom line, a total row's top line and a first or last column's inner line
    # belong to the region itself, wherever it sits in the table.
    if first_row and style.first_row.bottom is not None:
        bottom = style.first_row.bottom
    if last_row and style.last_row.top is not None:
        top = style.last_row.top
    if first_col and style.first_col.right is not None:
        right = style.first_col.right
    if last_col and style.last_col.left is not None:
        left = style.last_col.left

    def line(ref: str | None) -> Line | None:
        # A reference may carry its own width ("lt1@38100"); the rest draw at one point.
        name, _, width = (ref or "").partition("@")
        colour = _colour(name, colors) if name else None
        if colour is None:
            return None
        return Line(color=colour, width_emu=int(width) if width else _BORDER_EMU)

    sides = SideLines(top=line(top), right=line(right), bottom=line(bottom), left=line(left))
    return ResolvedCellStyle(
        fill=_fill(fill, colors),
        text=_colour(text, colors) if text else None,
        borders=sides if any((sides.top, sides.right, sides.bottom, sides.left)) else None,
        bold=first_row or last_row or first_col or last_col,
    )
