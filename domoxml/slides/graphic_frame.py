"""Reverse adapters for PresentationML ``p:graphicFrame`` nodes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import (
    Box,
    Fill,
    Line,
    SideLines,
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


def _text_body(cell: Element, text_run_for: TextRunParser) -> TextBody | None:
    body = cell.find("a:txBody", _NS)
    if body is None:
        return None
    paragraphs: list[TextParagraph] = []
    for paragraph in body.findall("a:p", _NS):
        properties = paragraph.find("a:pPr", _NS)
        alignment = _ALIGN_FROM_OOXML.get(
            properties.get("algn", "l") if properties is not None else "l", "left"
        )
        runs = tuple(
            run
            for element in paragraph.findall("a:r", _NS)
            if (run := text_run_for(element)) is not None
        )
        if runs:
            paragraphs.append(TextParagraph(runs=runs, align=alignment))
    return TextBody(paragraphs=tuple(paragraphs)) if paragraphs else None


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
) -> TableNode | None:
    """Parse a table ``p:graphicFrame`` using caller-provided style resolvers."""
    transform = element.find("p:xfrm", _NS)
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if offset is None or extent is None:
        return None
    box = Box(
        x=_int_attr(offset, "x"),
        y=_int_attr(offset, "y"),
        width=_int_attr(extent, "cx"),
        height=_int_attr(extent, "cy"),
    )
    table = element.find("a:graphic/a:graphicData/a:tbl", _NS)
    if table is None:
        return None
    column_widths = tuple(
        _int_attr(column, "w") for column in table.findall("a:tblGrid/a:gridCol", _NS)
    )
    if not column_widths:
        return None

    rows: list[TableRow] = []
    for row in table.findall("a:tr", _NS):
        cells: list[TableCell] = []
        for cell in row.findall("a:tc", _NS):
            if cell.get("hMerge") == "1" or cell.get("vMerge") == "1":
                continue
            properties = cell.find("a:tcPr", _NS)
            margins = (0, 0, 0, 0)
            if properties is not None:
                margins = (
                    _int_attr(properties, "marL"),
                    _int_attr(properties, "marT"),
                    _int_attr(properties, "marR"),
                    _int_attr(properties, "marB"),
                )
            cells.append(
                TableCell(
                    text=_text_body(cell, text_run_for),
                    fill=fill_for(properties) if properties is not None else None,
                    borders=_borders(properties, line_for) if properties is not None else None,
                    margins=margins,
                    col_span=max(1, _int_attr(cell, "gridSpan", 1)),
                    row_span=max(1, _int_attr(cell, "rowSpan", 1)),
                )
            )
        if cells:
            rows.append(TableRow(height_emu=_int_attr(row, "h"), cells=tuple(cells)))
    return TableNode(box=box, col_widths_emu=column_widths, rows=tuple(rows)) if rows else None


def read_graphic_frame(
    element: Element,
    *,
    fill_for: FillParser,
    line_for: LineParser,
    text_run_for: TextRunParser,
) -> GraphicFrameRead:
    """Read a supported graphic frame or classify it for explicit preservation."""
    uri = graphic_frame_uri(element)
    if uri == TABLE_URI:
        table = parse_table(
            element,
            fill_for=fill_for,
            line_for=line_for,
            text_run_for=text_run_for,
        )
        if table is not None:
            return GraphicFrameRead(table=table)
    return GraphicFrameRead(reason=preservation_reason(uri))
