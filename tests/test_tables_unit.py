"""Unit tests for native table forward+reverse support.

Covers:
  - Forward (IR→XML): ``table_xml()`` emits valid ``p:graphicFrame``/``a:tbl`` XML
  - Reverse (XML→IR): PPTX round-trip recovers ``TableNode`` from generated PPTX bytes
  - HTML: ``serialize_canvas()`` emits semantic ``<table>`` HTML from ``TableNode``
  - Round-trip: ``build_pptx`` → ``pptx_to_html`` keeps node count and structure
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from domoxml.core.html import serialize_canvas
from domoxml.core.ir.model import (
    Box,
    Line,
    Rgba,
    SideLines,
    SlideIR,
    SolidFill,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides import build_pptx

_TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"


# --------------------------------------------------------------------------- helpers


def _slide_xml(pptx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        return archive.read("ppt/slides/slide1.xml").decode("utf-8")


def _simple_table(*, n_rows: int = 2, n_cols: int = 3) -> TableNode:
    """A uniform table with plain text cells and no merges."""
    col_w = 1_000_000
    row_h = 500_000
    rows = tuple(
        TableRow(
            height_emu=row_h,
            cells=tuple(
                TableCell(
                    text=TextBody(
                        paragraphs=(
                            TextParagraph(
                                runs=(TextRun(text=f"r{r}c{c}", font_family="Arial", size_pt=12),)
                            ),
                        )
                    )
                )
                for c in range(n_cols)
            ),
        )
        for r in range(n_rows)
    )
    return TableNode(
        box=Box(x=500_000, y=500_000, width=col_w * n_cols, height=row_h * n_rows),
        col_widths_emu=tuple(col_w for _ in range(n_cols)),
        rows=rows,
    )


def _merge_table() -> TableNode:
    """2x2 table where top-left cell spans 2 columns (one origin + one continuation)."""
    col_w = 1_000_000
    row_h = 500_000
    rows = (
        TableRow(
            height_emu=row_h,
            cells=(
                # Origin cell spanning 2 columns.
                TableCell(
                    text=TextBody(
                        paragraphs=(
                            TextParagraph(
                                runs=(TextRun(text="wide", font_family="Arial", size_pt=12),)
                            ),
                        )
                    ),
                    col_span=2,
                ),
                # Second row has 2 normal cells.
            ),
        ),
        TableRow(
            height_emu=row_h,
            cells=(
                TableCell(
                    text=TextBody(
                        paragraphs=(
                            TextParagraph(
                                runs=(TextRun(text="A", font_family="Arial", size_pt=12),)
                            ),
                        )
                    )
                ),
                TableCell(
                    text=TextBody(
                        paragraphs=(
                            TextParagraph(
                                runs=(TextRun(text="B", font_family="Arial", size_pt=12),)
                            ),
                        )
                    )
                ),
            ),
        ),
    )
    return TableNode(
        box=Box(x=500_000, y=500_000, width=col_w * 2, height=row_h * 2),
        col_widths_emu=(col_w, col_w),
        rows=rows,
    )


def _slide_with_table(table: TableNode) -> SlideIR:
    return SlideIR(width=12_192_000, height=6_858_000, shapes=(), nodes=(table,))


# --------------------------------------------------------------------------- forward (IR→XML)


def test_table_xml_emits_graphic_frame() -> None:
    """``table_xml()`` produces a ``p:graphicFrame`` wrapping an ``a:tbl``."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _simple_table()
    xml = table_xml(node, shape_id=2)
    assert "<p:graphicFrame>" in xml
    assert f'uri="{_TABLE_URI}"' in xml
    assert "<a:tbl>" in xml


def test_table_xml_emits_tblgrid_and_gridcol() -> None:
    """Column widths are encoded as ``a:tblGrid``/``a:gridCol`` elements."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _simple_table(n_cols=3)
    xml = table_xml(node, shape_id=2)
    assert xml.count("<a:gridCol") == 3
    assert 'w="1000000"' in xml


def test_table_xml_emits_rows_and_cells() -> None:
    """Row/cell counts in the XML match the IR."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _simple_table(n_rows=2, n_cols=3)
    xml = table_xml(node, shape_id=2)
    assert xml.count("<a:tr ") == 2
    # 6 origin cells + 0 continuation cells.
    assert xml.count("<a:tc>") + xml.count("<a:tc ") == 6


def test_table_xml_emits_hmrg_for_colspan() -> None:
    """A ``col_span=2`` origin cell produces one ``hMerge="1"`` continuation cell."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _merge_table()
    xml = table_xml(node, shape_id=2)
    assert 'hMerge="1"' in xml
    assert 'gridSpan="2"' in xml


def test_table_xml_cell_text() -> None:
    """Cell text content is emitted inside ``a:txBody``."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _simple_table(n_rows=1, n_cols=1)
    xml = table_xml(node, shape_id=2)
    assert "r0c0" in xml


def test_table_xml_cell_fill() -> None:
    """A ``SolidFill`` on a cell emits ``a:solidFill`` inside ``a:tcPr``."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    cell = TableCell(
        fill=SolidFill(color=Rgba(r=255, g=0, b=0)),
    )
    node = TableNode(
        box=Box(x=0, y=0, width=1_000_000, height=500_000),
        col_widths_emu=(1_000_000,),
        rows=(TableRow(height_emu=500_000, cells=(cell,)),),
    )
    xml = table_xml(node, shape_id=2)
    assert "<a:solidFill>" in xml


def test_table_xml_cell_borders() -> None:
    """Border lines on a cell emit ``a:lnL``/``a:lnR``/``a:lnT``/``a:lnB`` inside ``a:tcPr``."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    border_line = Line(color=Rgba(r=0, g=0, b=0), width_emu=9525)
    cell = TableCell(
        borders=SideLines(left=border_line, right=border_line, top=border_line, bottom=border_line),
    )
    node = TableNode(
        box=Box(x=0, y=0, width=1_000_000, height=500_000),
        col_widths_emu=(1_000_000,),
        rows=(TableRow(height_emu=500_000, cells=(cell,)),),
    )
    xml = table_xml(node, shape_id=2)
    for tag in ("lnL", "lnR", "lnT", "lnB"):
        assert f"<a:{tag} " in xml


def test_table_xml_shape_id_appears_in_cnvpr() -> None:
    """The ``shape_id`` argument is reflected in ``p:cNvPr id``."""
    from domoxml.core.drawingml import table_xml  # pyright: ignore[reportPrivateUsage]

    node = _simple_table()
    xml = table_xml(node, shape_id=7)
    assert 'id="7"' in xml


def test_build_pptx_includes_table_in_slide() -> None:
    """``build_pptx`` serializes ``TableNode`` instances in ``slide.nodes`` into the slide XML."""
    slide = _slide_with_table(_simple_table())
    pptx = build_pptx([slide], faces=[])
    xml = _slide_xml(pptx)
    assert "<p:graphicFrame>" in xml
    assert "<a:tbl>" in xml


def test_build_pptx_table_is_valid_xml() -> None:
    """The generated slide XML is well-formed and contains parseable table elements."""
    slide = _slide_with_table(_simple_table())
    pptx = build_pptx([slide], faces=[])
    xml = _slide_xml(pptx)
    root = ElementTree.fromstring(xml)
    tbl_els = root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl")
    assert len(tbl_els) == 1


# --------------------------------------------------------------------------- reverse (XML→IR)


def test_reverse_reads_table_node_from_pptx() -> None:
    """Round-trip: built PPTX round-trips back to a ``TableNode`` in ``slide.nodes``."""
    from domoxml.slides.read import read_pptx_result

    slide = _slide_with_table(_simple_table(n_rows=2, n_cols=3))
    pptx = build_pptx([slide], faces=[])
    result = read_pptx_result(pptx)
    assert len(result.slides) == 1
    nodes = result.slides[0].nodes
    assert len(nodes) == 1
    table = nodes[0]
    assert isinstance(table, TableNode)


def test_reverse_reads_correct_box() -> None:
    """Reversed ``TableNode`` preserves the bounding box from the forward IR."""
    from domoxml.slides.read import read_pptx_result

    orig = _simple_table()
    pptx = build_pptx([_slide_with_table(orig)], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    assert table.box == orig.box


def test_reverse_reads_col_widths() -> None:
    """Column widths survive the round-trip."""
    from domoxml.slides.read import read_pptx_result

    orig = _simple_table(n_cols=3)
    pptx = build_pptx([_slide_with_table(orig)], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    assert table.col_widths_emu == orig.col_widths_emu


def test_reverse_reads_row_and_cell_counts() -> None:
    """Row count and per-row cell count survive the round-trip (merges are logical)."""
    from domoxml.slides.read import read_pptx_result

    orig = _simple_table(n_rows=2, n_cols=3)
    pptx = build_pptx([_slide_with_table(orig)], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    assert len(table.rows) == 2
    for row in table.rows:
        assert len(row.cells) == 3


def test_reverse_reads_merged_cell_colspan() -> None:
    """A ``col_span=2`` cell is recovered with the correct span after round-trip."""
    from domoxml.slides.read import read_pptx_result

    orig = _merge_table()
    pptx = build_pptx([_slide_with_table(orig)], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    # Row 0 has one logical cell (spanning 2 cols); row 1 has two normal cells.
    assert len(table.rows[0].cells) == 1
    assert table.rows[0].cells[0].col_span == 2
    assert len(table.rows[1].cells) == 2


def test_reverse_reads_cell_text() -> None:
    """Cell text content is preserved through the round-trip."""
    from domoxml.slides.read import read_pptx_result

    orig = _simple_table(n_rows=1, n_cols=1)
    pptx = build_pptx([_slide_with_table(orig)], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    body = table.rows[0].cells[0].text
    assert body is not None
    text = " ".join(run.text for p in body.paragraphs for run in p.runs)
    assert "r0c0" in text


# --------------------------------------------------------------------------- HTML (TableNode→HTML)


def test_html_emits_table_element() -> None:
    """``serialize_canvas`` emits a ``<table>`` for a slide containing a ``TableNode``."""
    slide = _slide_with_table(_simple_table())
    html = serialize_canvas([slide]).slides[0].html
    assert "<table" in html


def test_html_table_has_correct_cell_count() -> None:
    """The HTML table has the expected number of ``<td>`` cells."""
    slide = _slide_with_table(_simple_table(n_rows=2, n_cols=3))
    html = serialize_canvas([slide]).slides[0].html
    # 2 rows x 3 cols = 6 cells.
    assert html.count("<td") == 6


def test_html_table_colspan_on_merged_cell() -> None:
    """A ``col_span=2`` cell emits a ``colspan="2"`` attribute on the ``<td>``."""
    slide = _slide_with_table(_merge_table())
    html = serialize_canvas([slide]).slides[0].html
    assert 'colspan="2"' in html


def test_html_table_cell_contains_text() -> None:
    """Cell text content is present in the HTML output."""
    slide = _slide_with_table(_simple_table(n_rows=1, n_cols=1))
    html = serialize_canvas([slide]).slides[0].html
    assert "r0c0" in html


def test_html_table_has_colgroup() -> None:
    """The HTML table emits a ``<colgroup>`` with ``<col>`` widths."""
    slide = _slide_with_table(_simple_table(n_cols=3))
    html = serialize_canvas([slide]).slides[0].html
    assert "<colgroup" in html
    assert html.count("<col ") == 3


# --------------------------------------------------------------------------- full round-trip


def test_round_trip_table_survives_as_node() -> None:
    """``build_pptx`` + ``read_pptx_result`` recovers one ``TableNode`` in the slide."""
    from domoxml.slides.read import read_pptx_result

    slide = _slide_with_table(_simple_table(n_rows=3, n_cols=4))
    pptx = build_pptx([slide], faces=[])
    result = read_pptx_result(pptx)
    table = result.slides[0].nodes[0]
    assert isinstance(table, TableNode)
    assert len(table.rows) == 3
    for row in table.rows:
        assert len(row.cells) == 4
