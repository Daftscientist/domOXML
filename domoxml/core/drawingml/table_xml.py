"""Emit a DrawingML ``a:tbl`` (table) inside a ``p:graphicFrame``.

ECMA-376 §21.1.3 — Table.

Child order per the schema:
  a:tbl
    a:tblPr
    a:tblGrid
      a:gridCol (one per column)
    a:tr (one per row)
      a:tc (one per logical column slot)
        a:txBody
        a:tcPr
          a:lnL / a:lnR / a:lnT / a:lnB  (optional border lines)
          a:solidFill / a:noFill          (cell fill)

The IR :class:`TableNode` stores only logical cells (origin cells carry col_span/row_span ≥ 1;
the grid has no continuation-cell placeholders). The writer reconstructs the full rectangular
grid (required by OOXML) and emits ``hMerge``/``vMerge`` placeholder ``a:tc`` elements for
every cell slot covered by a multi-span origin cell.
"""

from __future__ import annotations

from domoxml.core.drawingml.identity import node_identity_xml
from domoxml.core.drawingml.shape import (
    _CAP_TO_OOXML,  # pyright: ignore[reportPrivateUsage]
    _DASH_TO_OOXML,  # pyright: ignore[reportPrivateUsage]
    _JOIN_OOXML_TAG,  # pyright: ignore[reportPrivateUsage]
    HyperlinkRid,
    _fill_xml,  # pyright: ignore[reportPrivateUsage]
    _no_hyperlink_rid,  # pyright: ignore[reportPrivateUsage]
    _paragraph,  # pyright: ignore[reportPrivateUsage]
    _solid_fill,  # pyright: ignore[reportPrivateUsage]
)
from domoxml.core.ir.model import (
    Fill,
    Line,
    SideLines,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
)

# The DrawingML namespace URI for table data.
_TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"


def _tc_border_xml(tag: str, line: Line | None) -> str:
    """Emit ``<a:lnL/>`` / ``<a:lnR/>`` / ``<a:lnT/>`` / ``<a:lnB/>`` inside ``a:tcPr``."""
    if line is None:
        return f"<a:{tag}><a:noFill/></a:{tag}>"
    cap = _CAP_TO_OOXML.get(line.cap, "flat")
    dash = _DASH_TO_OOXML.get(line.dash, "solid")
    join_tag = _JOIN_OOXML_TAG.get(line.join, "<a:round/>")
    fill_xml = _solid_fill(line.color)
    return (
        f'<a:{tag} w="{line.width_emu}" cap="{cap}">'
        f"{fill_xml}"
        f'<a:prstDash val="{dash}"/>'
        f"{join_tag}"
        f"</a:{tag}>"
    )


def _tc_pr_xml(
    fill: Fill | None,
    borders: SideLines | None,
    margins: tuple[int, int, int, int],
) -> str:
    """Emit ``<a:tcPr>`` with margins, borders, and fill.

    Attribute order per ECMA-376: marL, marR, marT, marB (all EMU).
    Child order: a:lnL, a:lnR, a:lnT, a:lnB, then fill.
    """
    mar_l, mar_t, mar_r, mar_b = margins
    attrs = ""
    if mar_l:
        attrs += f' marL="{mar_l}"'
    if mar_r:
        attrs += f' marR="{mar_r}"'
    if mar_t:
        attrs += f' marT="{mar_t}"'
    if mar_b:
        attrs += f' marB="{mar_b}"'

    # Border lines (all four sides, always emitted — absence means no border).
    ln_l = _tc_border_xml("lnL", borders.left if borders else None)
    ln_r = _tc_border_xml("lnR", borders.right if borders else None)
    ln_t = _tc_border_xml("lnT", borders.top if borders else None)
    ln_b = _tc_border_xml("lnB", borders.bottom if borders else None)

    # Cell fill.
    fill_xml = _fill_xml(fill, opacity=1.0, blip_rid=None)

    return f"<a:tcPr{attrs}>{ln_l}{ln_r}{ln_t}{ln_b}{fill_xml}</a:tcPr>"


def _tx_body_xml(body: TextBody | None, hyperlink_rid: HyperlinkRid) -> str:
    """Emit ``<a:txBody>`` for a table cell."""
    if body is None:
        return (
            '<a:txBody><a:bodyPr wrap="square"/><a:lstStyle/>'
            '<a:p><a:pPr algn="l"/></a:p></a:txBody>'
        )
    paragraphs = "".join(_paragraph(p, hyperlink_rid) for p in body.paragraphs)
    return f'<a:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{paragraphs}</a:txBody>'


def _merge_continuation_tc() -> str:
    """Emit a minimal ``hMerge``/``vMerge`` continuation placeholder cell."""
    return (
        '<a:tc hMerge="1" vMerge="1">'
        "<a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody>"
        "<a:tcPr/>"
        "</a:tc>"
    )


def _hmrg_tc() -> str:
    """Emit a horizontal-merge continuation cell (same row, covered column)."""
    return '<a:tc hMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>'


def _vmrg_tc() -> str:
    """Emit a vertical-merge continuation cell (same column, covered row)."""
    return '<a:tc vMerge="1"><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>'


def _build_full_grid(
    rows: tuple[TableRow, ...],
    n_cols: int,
) -> tuple[list[list[TableCell | None]], dict[tuple[int, int], tuple[int, int]]]:
    """Expand the IR logical rows into a full rectangular grid.

    The IR has one :class:`TableCell` per logical column position (origin cells only, no
    continuation placeholders). This function reconstructs the ``n_rows x n_cols`` grid
    inserting ``None`` for every cell slot that is covered by a multi-span origin.

    Returns:
        ``(grid, occupied)`` where ``grid[row][col]`` is the origin :class:`TableCell` or
        ``None`` for a continuation slot, and ``occupied`` maps ``(r, c)`` → ``(orig_r, orig_c)``.
    """
    n_rows = len(rows)
    # grid[r][c] = origin TableCell if (r,c) is the top-left of that cell, else None.
    grid: list[list[TableCell | None]] = [[None] * n_cols for _ in range(n_rows)]

    # Track which (r, c) slots are already occupied by a span.
    # Value is (origin_row, origin_col) so we can determine hMerge/vMerge kind.
    occupied: dict[tuple[int, int], tuple[int, int]] = {}

    for row_idx, row in enumerate(rows):
        col_cursor = 0
        for cell in row.cells:
            # Advance past occupied (continuation) slots.
            while col_cursor < n_cols and (row_idx, col_cursor) in occupied:
                col_cursor += 1
            if col_cursor >= n_cols:
                break
            grid[row_idx][col_cursor] = cell
            # Mark all slots this cell spans.
            cs = max(1, cell.col_span)
            rs = max(1, cell.row_span)
            for dr in range(rs):
                for dc in range(cs):
                    if dr == 0 and dc == 0:
                        continue
                    occupied[(row_idx + dr, col_cursor + dc)] = (row_idx, col_cursor)
            col_cursor += cs

    return grid, occupied


def table_xml(node: TableNode, *, shape_id: int) -> str:
    """Build the ``<p:graphicFrame>`` wrapping a DrawingML ``<a:tbl>`` for one table node.

    ``shape_id`` must be unique within the slide (the caller assigns it).
    """
    n_cols = len(node.col_widths_emu)

    # ---------- graphicFrame non-visual properties ----------
    nv = (
        f"<p:nvGraphicFramePr>"
        f'<p:cNvPr id="{shape_id}" name="Table {shape_id}"/>'
        f'<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
        f"<p:nvPr>{node_identity_xml(node)}</p:nvPr>"
        f"</p:nvGraphicFramePr>"
    )

    # ---------- transform ----------
    xfrm = (
        f"<p:xfrm>"
        f'<a:off x="{node.box.x}" y="{node.box.y}"/>'
        f'<a:ext cx="{node.box.width}" cy="{node.box.height}"/>'
        f"</p:xfrm>"
    )

    # ---------- tblGrid ----------
    grid_cols = "".join(f'<a:gridCol w="{w}"/>' for w in node.col_widths_emu)
    tbl_grid = f"<a:tblGrid>{grid_cols}</a:tblGrid>"

    # ---------- expand logical rows into full grid ----------
    full_grid, occupied = _build_full_grid(node.rows, n_cols)

    # ---------- rows ----------
    rows_xml = ""
    for row_idx, row in enumerate(node.rows):
        cells_xml = ""
        for col_idx in range(n_cols):
            origin = full_grid[row_idx][col_idx]
            if origin is None:
                # Continuation slot — use origin position to decide merge kind.
                orig_r, orig_c = occupied[(row_idx, col_idx)]
                same_row = orig_r == row_idx
                same_col = orig_c == col_idx
                if same_row and not same_col:
                    # Extra column in the same row → hMerge only
                    cells_xml += _hmrg_tc()
                elif not same_row and same_col:
                    # Extra row in the same column → vMerge only
                    cells_xml += _vmrg_tc()
                else:
                    # Both row and column differ → both hMerge and vMerge
                    cells_xml += _merge_continuation_tc()
                continue

            cell = origin
            span_attrs = ""
            if cell.col_span > 1:
                span_attrs += f' gridSpan="{cell.col_span}"'
            if cell.row_span > 1:
                span_attrs += f' rowSpan="{cell.row_span}"'

            tx = _tx_body_xml(cell.text, _no_hyperlink_rid)
            tc_pr = _tc_pr_xml(cell.fill, cell.borders, cell.margins)
            cells_xml += f"<a:tc{span_attrs}>{tx}{tc_pr}</a:tc>"

        rows_xml += f'<a:tr h="{row.height_emu}">{cells_xml}</a:tr>'

    # ---------- tbl ----------
    tbl = f"<a:tbl><a:tblPr/>{tbl_grid}{rows_xml}</a:tbl>"

    # ---------- graphic ----------
    graphic = f'<a:graphic><a:graphicData uri="{_TABLE_URI}">{tbl}</a:graphicData></a:graphic>'

    return f"<p:graphicFrame>{nv}{xfrm}{graphic}</p:graphicFrame>"
