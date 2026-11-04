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
from domoxml.slides.table_styles import is_builtin, resolve_cell_style

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
_ANCHOR: dict[str, Literal["top", "middle", "bottom"]] = {
    "t": "top",
    "ctr": "middle",
    "b": "bottom",
}
_DEFAULT_CELL_MARGINS = (91_440, 45_720, 91_440, 45_720)
_DEFAULT_TABLE_FONT_SIZE_PT = 18.0

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


def _has_attribute(primary: Element | None, fallback: Element | None, name: str) -> bool:
    return (primary is not None and primary.get(name) is not None) or (
        fallback is not None and fallback.get(name) is not None
    )


def _has_child(primary: Element | None, fallback: Element | None, tag: str) -> bool:
    return (primary is not None and primary.find(tag, _NS) is not None) or (
        fallback is not None and fallback.find(tag, _NS) is not None
    )


_CELL_DIRECTION: dict[str, Literal["vert", "vert270"]] = {
    "vert": "vert",
    "eaVert": "vert",
    "wordArtVert": "vert",
    "vert270": "vert270",
}


def _text_body(
    cell: Element,
    text_run_for: TextRunParser,
    *,
    default_color: Rgba | None = None,
    default_bold: bool = False,
    default_font_family: str = "sans-serif",
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
        for element in paragraph:
            if element.tag not in {f"{{{_A}}}r", f"{{{_A}}}fld"}:
                continue
            run = text_run_for(element)
            if run is None:
                continue
            run_properties = element.find("a:rPr", _NS)
            default_properties = (
                properties.find("a:defRPr", _NS) if properties is not None else None
            )
            update: dict[str, object] = {}
            if not _has_attribute(run_properties, default_properties, "sz"):
                update["size_pt"] = _DEFAULT_TABLE_FONT_SIZE_PT
            if not _has_child(run_properties, default_properties, "a:latin"):
                update["font_family"] = default_font_family
            if default_color is not None and not _has_child(
                run_properties, default_properties, "a:solidFill"
            ):
                update["color"] = default_color
            if default_bold and not _has_attribute(run_properties, default_properties, "b"):
                update["bold"] = True
                update["bold_inherited"] = True
            runs.append(run.model_copy(update=update) if update else run)
        if runs:
            paragraphs.append(TextParagraph(runs=tuple(runs), align=alignment))
    return TextBody(paragraphs=tuple(paragraphs)) if paragraphs else None


def _borders(
    properties: Element, line_for: LineParser, defaults: SideLines | None = None
) -> SideLines | None:
    lines: dict[str, Line | None] = {}
    for side, tag in (("left", "lnL"), ("right", "lnR"), ("top", "lnT"), ("bottom", "lnB")):
        element = properties.find(f"a:{tag}", _NS)
        lines[side] = line_for(element) if element is not None else getattr(defaults, side, None)
    return SideLines(**lines) if any(lines.values()) else None  # type: ignore[arg-type]


def parse_table(
    element: Element,
    *,
    fill_for: FillParser,
    line_for: LineParser,
    text_run_for: TextRunParser,
    theme_colors: Mapping[str, str] | None = None,
    default_font_family: str = "sans-serif",
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
    table_properties = table.find("a:tblPr", _NS)
    style_id = (
        table_properties.findtext("a:tableStyleId", default="", namespaces=_NS) or None
        if table_properties is not None
        else None
    )
    column_widths = tuple(
        _int_attr(column, "w") for column in table.findall("a:tblGrid/a:gridCol", _NS)
    )
    if not column_widths:
        return None

    rows: list[TableRow] = []
    row_elements = table.findall("a:tr", _NS)
    flags = {
        name: table_properties is not None and table_properties.get(name) in {"1", "true"}
        for name in ("firstRow", "lastRow", "firstCol", "lastCol", "bandRow", "bandCol")
    }
    for row_index, row in enumerate(row_elements):
        cells: list[TableCell] = []
        column_index = 0
        for cell in row.findall("a:tc", _NS):
            column = column_index
            # A cell merged into the one to its left sits in a slot that cell's span already counts.
            if cell.get("hMerge") != "1":
                column_index += max(1, _int_attr(cell, "gridSpan", 1))
            if cell.get("hMerge") == "1" or cell.get("vMerge") == "1":
                continue
            resolved = (
                resolve_cell_style(
                    style_id,
                    row=row_index,
                    column=column,
                    rows=len(row_elements),
                    columns=len(column_widths),
                    flags=flags,
                    colors=theme_colors or {},
                )
                if style_id
                else None
            )
            style_fill = SolidFill(color=resolved.fill) if resolved and resolved.fill else None
            style_borders = resolved.borders if resolved else None
            style_text_color = resolved.text if resolved else None
            style_bold = resolved.bold if resolved else False
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
            has_explicit_no_fill = (
                properties is not None and properties.find("a:noFill", _NS) is not None
            )
            fill = None if has_explicit_no_fill else explicit_fill or style_fill
            borders = (
                _borders(properties, line_for, style_borders)
                if properties is not None
                else style_borders
            )
            cell_text = _text_body(
                cell,
                text_run_for,
                default_color=style_text_color,
                default_bold=style_bold,
                default_font_family=default_font_family,
            )
            # The cell's own text direction lives on its tcPr, not on a bodyPr.
            direction = _CELL_DIRECTION.get(
                properties.get("vert", "") if properties is not None else ""
            )
            if cell_text is not None and direction is not None:
                cell_text = cell_text.model_copy(update={"vertical": direction})
            cells.append(
                TableCell(
                    text=cell_text,
                    fill=fill,
                    borders=borders,
                    margins=margins,
                    valign=_ANCHOR.get(
                        properties.get("anchor", "t") if properties is not None else "t", "top"
                    ),
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

    def enabled(name: str) -> bool:
        return table_properties is not None and table_properties.get(name) in {"1", "true"}

    return TableNode(
        box=box,
        col_widths_emu=column_widths,
        rows=tuple(rows),
        style_id=style_id,
        first_row=enabled("firstRow"),
        last_row=enabled("lastRow"),
        first_col=enabled("firstCol"),
        last_col=enabled("lastCol"),
        band_row=enabled("bandRow"),
        band_col=enabled("bandCol"),
        header_bold_inherited=(bool(style_id) and is_builtin(style_id) and enabled("firstRow")),
    )


def read_graphic_frame(
    element: Element,
    *,
    fill_for: FillParser,
    line_for: LineParser,
    text_run_for: TextRunParser,
    theme_colors: Mapping[str, str] | None = None,
    default_font_family: str = "sans-serif",
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
            default_font_family=default_font_family,
        )
        if table is not None:
            return GraphicFrameRead(table=table)
    return GraphicFrameRead(reason=preservation_reason(uri))
