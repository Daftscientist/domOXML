"""A picture in a table cell: PPTX writer, reader and HTML, both ways."""

from __future__ import annotations

import io
import zipfile

from PIL import Image

from domoxml.core.ir.model import (
    Box,
    PictureFill,
    SlideIR,
    TableCell,
    TableNode,
    TableRow,
)
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result

_PX = 9525


def _picture() -> PictureFill:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buffer, "PNG")
    return PictureFill(data=buffer.getvalue(), ext="png")


def _deck() -> bytes:
    table = TableNode(
        box=Box(x=0, y=0, width=400 * _PX, height=100 * _PX),
        col_widths_emu=(200 * _PX, 200 * _PX),
        rows=(TableRow(height_emu=100 * _PX, cells=(TableCell(), TableCell(fill=_picture()))),),
    )
    return build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(table,))], faces=[])


def test_a_cell_picture_is_written_as_a_blip_fill_with_its_image_part() -> None:
    with zipfile.ZipFile(io.BytesIO(_deck())) as package:
        slide = package.read("ppt/slides/slide1.xml").decode()
        rels = package.read("ppt/slides/_rels/slide1.xml.rels").decode()
        media = [n for n in package.namelist() if n.startswith("ppt/media/")]

    assert "<a:blipFill>" in slide and "r:embed=" in slide and "relationships/image" in rels
    assert len(media) == 1


def test_a_cell_picture_reads_back_and_reaches_the_html_as_a_background() -> None:
    deck = _deck()

    [table] = read_pptx_result(deck).slides[0].contents
    assert isinstance(table, TableNode)
    assert isinstance(table.rows[0].cells[1].fill, PictureFill)

    html = pptx_to_html(deck).slides[0].html
    assert "background-image:url(../assets/" in html and "<td" in html


def test_a_cells_text_direction_round_trips_through_its_tcpr() -> None:
    from domoxml.core.ir.model import TextBody, TextParagraph, TextRun

    def cell(direction: str) -> TableCell:
        run = TextRun(text="Vertical", font_family="Arial", size_pt=12.0)
        body = TextBody(paragraphs=(TextParagraph(runs=(run,)),), vertical=direction)  # type: ignore[arg-type]
        return TableCell(text=body)

    table = TableNode(
        box=Box(x=0, y=0, width=300 * _PX, height=100 * _PX),
        col_widths_emu=(100 * _PX, 100 * _PX, 100 * _PX),
        rows=(TableRow(height_emu=100 * _PX, cells=(cell("horz"), cell("vert"), cell("vert270"))),),
    )
    deck = build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(table,))], faces=[])

    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        slide = package.read("ppt/slides/slide1.xml").decode()
    [back] = read_pptx_result(deck).slides[0].contents
    html = pptx_to_html(deck).slides[0].html

    assert 'vert="vert"' in slide and 'vert="vert270"' in slide
    assert isinstance(back, TableNode)
    assert [c.text.vertical for c in back.rows[0].cells if c.text] == ["horz", "vert", "vert270"]
    assert "writing-mode:vertical-rl" in html and "writing-mode:sideways-lr" in html


def _png(width: int, height: int) -> PictureFill:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, "PNG")
    return PictureFill(data=buffer.getvalue(), ext="png")


def _cell_html(fill: PictureFill) -> str:
    table = TableNode(
        box=Box(x=0, y=0, width=400 * _PX, height=100 * _PX),
        col_widths_emu=(400 * _PX,),
        rows=(TableRow(height_emu=100 * _PX, cells=(TableCell(fill=fill),)),),
    )
    deck = build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(table,))], faces=[])
    return pptx_to_html(deck).slides[0].html


def test_a_tiny_picture_stretched_a_long_way_keeps_hard_edges_but_a_modest_one_stays_smooth() -> (
    None
):
    assert "image-rendering:pixelated" in _cell_html(_png(8, 8))  # 50x enlarged
    assert "image-rendering:pixelated" not in _cell_html(_png(300, 80))  # about 1.3x enlarged


def test_a_shape_filled_with_a_tiny_picture_keeps_hard_edges_too() -> None:
    from domoxml.core.ir.model import ShapeNode

    shape = ShapeNode(
        box=Box(x=0, y=0, width=300 * _PX, height=200 * _PX), geom="rect", fill=_png(4, 4)
    )
    deck = build_pptx([SlideIR(width=1280 * _PX, height=720 * _PX, contents=(shape,))], faces=[])

    assert "image-rendering:pixelated" in pptx_to_html(deck).slides[0].html
