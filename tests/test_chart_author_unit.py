"""Charts authored from a ``data-chart`` spec: native chart parts, both directions."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from domoxml.core.chart_author import chart_part_xml, parse_chart_spec
from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import PreservedNode
from domoxml.core.render import BrowserSession, compose_page
from domoxml.presentation import pptx_to_html
from domoxml.slides.pptx import build_pptx
from domoxml.slides.read import read_pptx_result
from domoxml.types import Theme

_COLUMN = {
    "type": "column",
    "title": "Revenue",
    "categories": ["Q1", "Q2", "Q3"],
    "series": [
        {"name": "2025", "values": [12, 19, 14], "color": "#4472c4"},
        {"name": "2026", "values": [15, 21, 18]},
    ],
}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps({"type": "radar", "categories": ["a"], "series": [{"values": [1]}]}),
        json.dumps({"type": "bar", "categories": ["a", "b"], "series": [{"values": [1]}]}),
        json.dumps({"type": "bar", "categories": ["a"], "series": [{"values": ["x"]}]}),
        json.dumps(
            {"type": "pie", "categories": ["a"], "series": [{"values": [1]}, {"values": [2]}]}
        ),
    ],
)
def test_a_malformed_spec_is_not_a_chart(raw: str) -> None:
    assert parse_chart_spec(raw) is None


def test_a_spec_becomes_a_chart_part_with_its_series_literals_and_colours() -> None:
    spec = parse_chart_spec(json.dumps(_COLUMN))
    assert spec is not None

    xml = chart_part_xml(spec).decode()

    assert "<c:barChart>" in xml and '<c:barDir val="col"/>' in xml
    assert xml.count("<c:ser>") == 2 and "4472C4" in xml
    assert "<c:v>Revenue</c:v>" not in xml and ">Revenue<" in xml
    assert "<c:v>19.0</c:v>" in xml and "<c:legend>" in xml


@pytest.mark.integration
async def test_a_data_chart_block_becomes_a_native_chart_and_reads_back_as_one() -> None:
    html = (
        f"<div data-chart='{json.dumps(_COLUMN)}' style='position:absolute;left:40px;top:30px;"
        "width:580px;height:300px'></div>"
    )
    page = compose_page(html, css=None, theme=Theme(), width_px=1280, height_px=720)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    result = extract_slide(rendered)

    [node] = result.slide.contents
    assert isinstance(node, PreservedNode) and node.fallback is not None
    deck = build_pptx([result.slide], faces=[])
    with zipfile.ZipFile(io.BytesIO(deck)) as package:
        names = package.namelist()
        assert any(n.startswith("ppt/charts/chart") for n in names)
        assert "graphicFrame" in package.read("ppt/slides/slide1.xml").decode()
    back = read_pptx_result(deck)
    [read] = back.slides[0].contents
    assert isinstance(read, PreservedNode) and read.fallback is not None
    assert "<svg" in pptx_to_html(deck).slides[0].html.lower() or read.fallback.svg_data


@pytest.mark.integration
async def test_a_turned_data_chart_block_is_not_placed_upright() -> None:
    html = (
        f"<div data-chart='{json.dumps(_COLUMN)}' style='position:absolute;left:40px;top:30px;"
        "width:580px;height:300px;transform:rotate(10deg)'></div>"
    )
    page = compose_page(html, css=None, theme=Theme(), width_px=1280, height_px=720)
    async with BrowserSession() as session:
        rendered = await session.render(page, width=1280, height=720)

    assert not any(isinstance(n, PreservedNode) for n in extract_slide(rendered).slide.contents)
