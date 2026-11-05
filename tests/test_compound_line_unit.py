"""Compound outlines (``a:ln cmpd``): double and triple lines survive every direction."""

from __future__ import annotations

import re
from xml.etree.ElementTree import fromstring

from domoxml.core.drawingml.shape import line_xml
from domoxml.core.drawingml.table_xml import _tc_border_xml  # pyright: ignore[reportPrivateUsage]
from domoxml.core.html import (
    _border_side_css,  # pyright: ignore[reportPrivateUsage]
    serialize_canvas,
)
from domoxml.core.ir.model import Box, Line, Rgba, ShapeNode, SlideIR
from domoxml.core.ir.parse import parse_border_side
from domoxml.slides.appearance_read import line_element

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_BLACK = Rgba(r=0, g=0, b=0)
_SOLID = '<a:solidFill><a:srgbClr val="000000"/></a:solidFill>'


def _read(cmpd: str) -> Line | None:
    element = fromstring(
        f'<a:ln xmlns:a="{_A}" w="76200" cmpd="{cmpd}"><a:solidFill><a:srgbClr val="1D3557"/>'
        "</a:solidFill></a:ln>"
    )
    return line_element(element, {})


def test_the_reader_keeps_the_compound_type() -> None:
    for kind in ("dbl", "tri", "thickThin", "thinThick"):
        line = _read(kind)
        assert line is not None and line.compound == kind
    plain = line_element(
        fromstring(f'<a:ln xmlns:a="{_A}" w="9525">{_SOLID}</a:ln>'),
        {},
    )
    assert plain is not None and plain.compound == "sng"


def test_the_writer_emits_cmpd_only_for_a_compound_line() -> None:
    assert ' cmpd="tri"' in line_xml(Line(color=_BLACK, width_emu=76200, compound="tri"))
    assert "cmpd" not in line_xml(Line(color=_BLACK, width_emu=76200))


def test_html_draws_a_compound_line_as_a_css_double_border_and_reads_it_back() -> None:
    node = ShapeNode(
        box=Box(x=0, y=0, width=2_000_000, height=1_000_000),
        line=Line(color=_BLACK, width_emu=76200, compound="dbl"),
    )
    slide = SlideIR(width=12_192_000, height=6_858_000, shapes=(node,))
    html = serialize_canvas([slide]).slides[0].html

    assert re.search(r"border:[\d.]+px double rgba\(0,0,0,1\)", html)
    line, warning = parse_border_side("8px", "double", "rgb(0, 0, 0)")
    assert line is not None and line.compound == "dbl" and warning is None


def test_table_cell_borders_keep_their_compound_type_in_both_directions() -> None:
    double = Line(color=_BLACK, width_emu=38100, compound="dbl")

    assert ' cmpd="dbl"' in _tc_border_xml("lnL", double)
    assert "cmpd" not in _tc_border_xml("lnL", Line(color=_BLACK, width_emu=38100))
    assert _border_side_css(double).split()[1] == "double"
    assert _border_side_css(Line(color=_BLACK, width_emu=38100)).split()[1] == "solid"


def test_an_unknown_compound_token_is_a_single_line() -> None:
    line = _read("somethingNew")

    assert line is not None and line.compound == "sng"
