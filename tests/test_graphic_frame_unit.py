"""Contract tests for reverse ``p:graphicFrame`` adapters."""

from __future__ import annotations

from xml.etree.ElementTree import Element, fromstring

from domoxml.core.ir.model import Line, Rgba, SolidFill, TextRun
from domoxml.slides.graphic_frame import (
    DIAGRAM_URI,
    TABLE_URI,
    graphic_frame_uri,
    parse_table,
    preservation_reason,
    read_graphic_frame,
)

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _table_frame() -> Element:
    return fromstring(
        f'<p:graphicFrame xmlns:p="{_P}" xmlns:a="{_A}">'
        '<p:xfrm><a:off x="10" y="20"/><a:ext cx="300" cy="200"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="{TABLE_URI}"><a:tbl>'
        '<a:tblGrid><a:gridCol w="100"/><a:gridCol w="200"/></a:tblGrid>'
        '<a:tr h="80"><a:tc gridSpan="2" rowSpan="3">'
        '<a:txBody><a:p><a:pPr algn="ctr"/><a:r><a:t>Value</a:t></a:r></a:p></a:txBody>'
        '<a:tcPr marL="1" marT="2" marR="3" marB="4">'
        '<a:solidFill><a:srgbClr val="112233"/></a:solidFill>'
        '<a:lnL w="5"><a:solidFill><a:srgbClr val="445566"/></a:solidFill></a:lnL>'
        "</a:tcPr></a:tc></a:tr></a:tbl></a:graphicData></a:graphic>"
        "</p:graphicFrame>"
    )


def test_graphic_frame_uri_and_preservation_reason() -> None:
    frame = _table_frame()

    assert graphic_frame_uri(frame) == TABLE_URI
    assert "SmartArt" in preservation_reason(DIAGRAM_URI)
    assert "chart/table/unsupported" in preservation_reason("urn:example:chart")


def test_parse_table_delegates_styles_and_builds_grid() -> None:
    fills: list[Element] = []
    lines: list[Element] = []

    def parse_fill(properties: Element) -> SolidFill:
        fills.append(properties)
        return SolidFill(color=Rgba(r=0x11, g=0x22, b=0x33))

    def parse_line(element: Element) -> Line:
        lines.append(element)
        return Line(color=Rgba(r=0x44, g=0x55, b=0x66), width_emu=5)

    def parse_run(element: Element) -> TextRun:
        return TextRun(
            text=element.findtext(f"{{{_A}}}t", default=""),
            font_family="sans-serif",
            size_pt=12,
        )

    table = parse_table(
        _table_frame(),
        fill_for=parse_fill,
        line_for=parse_line,
        text_run_for=parse_run,
    )

    assert table is not None
    assert table.box.model_dump() == {"x": 10, "y": 20, "width": 300, "height": 200}
    assert table.col_widths_emu == (100, 200)
    assert len(table.rows) == 1
    cell = table.rows[0].cells[0]
    assert (cell.col_span, cell.row_span) == (2, 3)
    assert cell.margins == (1, 2, 3, 4)
    assert cell.text is not None
    assert cell.text.paragraphs[0].align == "center"
    assert cell.text.paragraphs[0].runs[0].text == "Value"
    assert len(fills) == 1
    assert [line.tag for line in lines] == [f"{{{_A}}}lnL"]


def test_graphic_frame_reader_classifies_non_table_frames() -> None:
    frame = fromstring(
        f'<p:graphicFrame xmlns:p="{_P}" xmlns:a="{_A}">'
        f'<a:graphic><a:graphicData uri="{DIAGRAM_URI}"/></a:graphic>'
        "</p:graphicFrame>"
    )

    result = read_graphic_frame(
        frame,
        fill_for=lambda _element: None,
        line_for=lambda _element: None,
        text_run_for=lambda _element: None,
    )

    assert result.table is None
    assert result.reason is not None
    assert "SmartArt" in result.reason
