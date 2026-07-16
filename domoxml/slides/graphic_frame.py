"""Reverse adapters for PresentationML ``p:graphicFrame`` nodes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import (
    Box,
    Fill,
    Line,
    Rgba,
    SideLines,
    SolidFill,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
    TextParagraph,
    TextRun,
)

TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"
DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}
_ALIGN_FROM_OOXML: dict[str, Literal["left", "center", "right", "justify"]] = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
}
_POWERPOINT_DEFAULT_TABLE_STYLE = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
_DEFAULT_CELL_MARGINS = (91_440, 45_720, 91_440, 45_720)
_DEFAULT_TABLE_BORDER_WIDTH = 12_700

type FillParser = Callable[[Element], Fill | None]
type LineParser = Callable[[Element], Line | None]
type TextRunParser = Callable[[Element], TextRun | None]


@dataclass(frozen=True)
class GraphicFrameRead:
    """A native table node or the reason its source frame must be preserved."""

    table: TableNode | None = None
    reason: str | None = None


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, str(default)))
    except ValueError:
        return default


def graphic_frame_uri(element: Element) -> str:
    """Return a graphic frame's DrawingML content URI, or an empty string."""
    graphic_data = element.find("a:graphic/a:graphicData", _NS)
    return graphic_data.get("uri", "") if graphic_data is not None else ""


def preservation_reason(uri: str) -> str:
    """Describe why a non-native graphic frame is being preserved."""
    if uri == DIAGRAM_URI:
        return "p:graphicFrame (SmartArt/diagram) has no HTML mapping; preserved as fragment"
    return (
        "p:graphicFrame (chart/table/unsupported graphic) has no HTML mapping; "
        "preserved as fragment"
    )


def _text_body(
    cell: Element,
    text_run_for: TextRunParser,
    *,
    default_color: Rgba | None = None,
    default_bold: bool = False,
) -> TextBody | None:
    body = cell.find("a:txBody", _NS)
    if body is None:
        return None
    paragraphs: list[TextParagraph] = []
    for paragraph in body.findall("a:p", _NS):
        properties = paragraph.find("a:pPr", _NS)
        alignment = _ALIGN_FROM_OOXML.get(
            properties.get("algn", "l") if properties is not None else "l", "left"
        )
        runs: list[TextRun] = []
        for element in paragraph.findall("a:r", _NS):
            run = text_run_for(element)
            if run is None:
                continue
            properties = element.find("a:rPr", _NS)
            update: dict[str, object] = {}
            if default_color is not None and (
                properties is None or properties.find("a:solidFill", _NS) is None
            ):
                update["color"] = default_color
            if default_bold and (properties is None or properties.get("b") is None):
                update["bold"] = True
            runs.append(run.model_copy(update=update) if update else run)
        if runs:
            paragraphs.append(TextParagraph(runs=tuple(runs), align=alignment))
    return TextBody(paragraphs=tuple(paragraphs)) if paragraphs else None


def _theme_color(colors: Mapping[str, str], slot: str) -> Rgba | None:
    value = colors.get(slot, "")
    if len(value) != 6:
        return None
    try:
        return Rgba(r=int(value[:2], 16), g=int(value[2:4], 16), b=int(value[4:], 16))
    except ValueError:
        return None


def _tint(color: Rgba, amount: float) -> Rgba:
    def to_linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    def to_srgb(channel: float) -> int:
        value = channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
        return round(max(0.0, min(1.0, value)) * 255)

    return Rgba(
        r=to_srgb(to_linear(color.r) * amount + (1 - amount)),
        g=to_srgb(to_linear(color.g) * amount + (1 - amount)),
        b=to_srgb(to_linear(color.b) * amount + (1 - amount)),
        a=color.a,
    )


def _default_table_style(
    table: Element,
    row_index: int,
    colors: Mapping[str, str],
) -> tuple[SolidFill | None, SideLines | None, Rgba | None, bool]:
    properties = table.find("a:tblPr", _NS)
    style_id = (
        properties.findtext("a:tableStyleId", default="", namespaces=_NS)
        if properties is not None
        else ""
    )
    if style_id.upper() != _POWERPOINT_DEFAULT_TABLE_STYLE:
        return None, None, None, False

    accent = _theme_color(colors, "accent1")
    light = _theme_color(colors, "lt1") or Rgba(r=255, g=255, b=255)
    if accent is None:
        return None, None, None, False

    first_row = properties is not None and properties.get("firstRow") == "1"
    band_rows = properties is not None and properties.get("bandRow") == "1"
    is_header = first_row and row_index == 0
    body_index = row_index - (1 if first_row else 0)
    is_band = band_rows and body_index >= 0 and body_index % 2 == 0
    fill = SolidFill(color=accent if is_header else _tint(accent, 0.4 if is_band else 0.2))
    border = Line(color=light, width_emu=_DEFAULT_TABLE_BORDER_WIDTH)
    borders = SideLines(left=border, right=border, top=border, bottom=border)
    return fill, borders, light if is_header else None, is_header


def _borders(properties: Element, line_for: LineParser) -> SideLines | None:
    lines = {
        side: line_for(element)
        if (element := properties.find(f"a:{tag}", _NS)) is not None
        else None
        for side, tag in (("left", "lnL"), ("right", "lnR"), ("top", "lnT"), ("bottom", "lnB"))
    }
    return SideLines(**lines) if any(lines.values()) else None  # type: ignore[arg-type]


def parse_table(
    element: Element,
    *,
    fill_for: FillParser,
    line_for: LineParser,
    text_run_for: TextRunParser,
    theme_colors: Mapping[str, str] | None = None,
) -> TableNode | None:
    """Parse a table ``p:graphicFrame`` using caller-provided style resolvers."""
    transform = element.find("p:xfrm", _NS)
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if offset is None or extent is None:
        return None
    table = element.find("a:graphic/a:graphicData/a:tbl", _NS)
    if table is None:
        return None
    column_widths = tuple(
        _int_attr(column, "w") for column in table.findall("a:tblGrid/a:gridCol", _NS)
    )
    if not column_widths:
        return None

    rows: list[TableRow] = []
    for row_index, row in enumerate(table.findall("a:tr", _NS)):
        style_fill, style_borders, style_text_color, style_bold = _default_table_style(
            table, row_index, theme_colors or {}
        )
        cells: list[TableCell] = []
        for cell in row.findall("a:tc", _NS):
            if cell.get("hMerge") == "1" or cell.get("vMerge") == "1":
                continue
            properties = cell.find("a:tcPr", _NS)
            margins = _DEFAULT_CELL_MARGINS
            if properties is not None:
                margins = (
                    _int_attr(properties, "marL", _DEFAULT_CELL_MARGINS[0]),
                    _int_attr(properties, "marT", _DEFAULT_CELL_MARGINS[1]),
                    _int_attr(properties, "marR", _DEFAULT_CELL_MARGINS[2]),
                    _int_attr(properties, "marB", _DEFAULT_CELL_MARGINS[3]),
                )
            explicit_fill = fill_for(properties) if properties is not None else None
            explicit_borders = _borders(properties, line_for) if properties is not None else None
            cells.append(
                TableCell(
                    text=_text_body(
                        cell,
                        text_run_for,
                        default_color=style_text_color,
                        default_bold=style_bold,
                    ),
                    fill=explicit_fill or style_fill,
                    borders=explicit_borders or style_borders,
                    margins=margins,
                    col_span=max(1, _int_attr(cell, "gridSpan", 1)),
                    row_span=max(1, _int_attr(cell, "rowSpan", 1)),
                )
            )
        if cells:
            rows.append(TableRow(height_emu=_int_attr(row, "h"), cells=tuple(cells)))
    if not rows:
        return None
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=max(_int_attr(extent, "cx"), sum(column_widths)),
        height=max(_int_attr(extent, "cy"), sum(row.height_emu for row in rows)),
    )
    return TableNode(box=box, col_widths_emu=column_widths, rows=tuple(rows))


def read_graphic_frame(
    element: Element,
    *,
    fill_for: FillParser,
    line_for: LineParser,
    text_run_for: TextRunParser,
    theme_colors: Mapping[str, str] | None = None,
) -> GraphicFrameRead:
    """Read a supported graphic frame or classify it for explicit preservation."""
    uri = graphic_frame_uri(element)
    if uri == TABLE_URI:
        table = parse_table(
            element,
            fill_for=fill_for,
            line_for=line_for,
            text_run_for=text_run_for,
            theme_colors=theme_colors,
        )
        if table is not None:
            return GraphicFrameRead(table=table)
    return GraphicFrameRead(reason=preservation_reason(uri))
