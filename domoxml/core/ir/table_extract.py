"""Rendered HTML table to native canvas-IR table extraction."""

from __future__ import annotations

from collections.abc import Callable

from domoxml.core.ir.model import (
    Box,
    Fill,
    Line,
    SideLines,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
)
from domoxml.core.ir.parse import parse_length_px
from domoxml.core.render.browser import RenderedNode
from domoxml.core.units import px_to_emu

type FillResolver = Callable[[RenderedNode], Fill | None]
type BorderResolver = Callable[
    [dict[str, str]],
    tuple[tuple[Line | None, Line | None, Line | None, Line | None], list[str]],
]
type TextResolver = Callable[[RenderedNode], TextBody | None]


def _margins(styles: dict[str, str]) -> tuple[int, int, int, int]:
    return (
        px_to_emu(parse_length_px(styles.get("paddingLeft")) or 0.0),
        px_to_emu(parse_length_px(styles.get("paddingTop")) or 0.0),
        px_to_emu(parse_length_px(styles.get("paddingRight")) or 0.0),
        px_to_emu(parse_length_px(styles.get("paddingBottom")) or 0.0),
    )


def extract_table(
    node: RenderedNode,
    nodes: tuple[RenderedNode, ...],
    children: dict[int, list[int]],
    *,
    fill_for: FillResolver,
    borders_for: BorderResolver,
    text_for: TextResolver,
) -> TableNode | None:
    """Convert one rendered ``<table>`` subtree into a native table node."""
    by_index = {item.index: item for item in nodes}

    def effective_cell_fill(cell: RenderedNode, row: RenderedNode) -> Fill | None:
        fill = fill_for(cell)
        if fill is not None:
            return fill
        current: RenderedNode | None = row
        while current is not None:
            fill = fill_for(current)
            if fill is not None:
                return fill
            if current.index == node.index:
                break
            current = by_index.get(current.parent)
        return None

    def descendants_with_tag(root: int, tag: str) -> list[int]:
        found: list[int] = []
        for child_index in children.get(root, []):
            child = by_index.get(child_index)
            if child is None:
                continue
            if child.tag == tag:
                found.append(child_index)
            elif child.tag != "table":
                found.extend(descendants_with_tag(child_index, tag))
        return found

    def cell_text(cell: RenderedNode) -> TextBody | None:
        direct = text_for(cell)
        if direct is not None:
            return direct
        stack = list(reversed(children.get(cell.index, [])))
        while stack:
            child_index = stack.pop()
            child = by_index.get(child_index)
            if child is None:
                continue
            nested = text_for(child)
            if nested is not None:
                return nested
            stack.extend(reversed(children.get(child_index, [])))
        return None

    row_indices = descendants_with_tag(node.index, "tr")
    if not row_indices:
        return None
    rows: list[TableRow] = []
    maximum_columns = 0
    for row_index in row_indices:
        row_node = by_index[row_index]
        cells: list[TableCell] = []
        column_count = 0
        for cell_index in children.get(row_index, []):
            cell_node = by_index.get(cell_index)
            if cell_node is None or cell_node.tag not in {"td", "th"}:
                continue
            column_span = max(1, int(cell_node.styles.get("domoxmlColSpan", "1")))
            row_span = max(1, int(cell_node.styles.get("domoxmlRowSpan", "1")))
            (top, right, bottom, left), _warnings = borders_for(cell_node.styles)
            borders = (
                SideLines(top=top, right=right, bottom=bottom, left=left)
                if any((top, right, bottom, left))
                else None
            )
            cells.append(
                TableCell(
                    text=cell_text(cell_node),
                    fill=effective_cell_fill(cell_node, row_node),
                    borders=borders,
                    margins=_margins(cell_node.styles),
                    row_span=row_span,
                    col_span=column_span,
                )
            )
            column_count += column_span
        if cells:
            maximum_columns = max(maximum_columns, column_count)
            rows.append(TableRow(height_emu=px_to_emu(row_node.height), cells=tuple(cells)))
    if not rows or maximum_columns == 0:
        return None

    box = Box(
        x=px_to_emu(node.x),
        y=px_to_emu(node.y),
        width=px_to_emu(node.width),
        height=px_to_emu(node.height),
    )
    base_width = box.width // maximum_columns
    column_widths = [base_width] * maximum_columns
    column_widths[-1] += box.width - base_width * maximum_columns
    return TableNode(box=box, col_widths_emu=tuple(column_widths), rows=tuple(rows))
