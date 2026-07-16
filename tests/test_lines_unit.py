"""Unit tests for line/stroke parity: per-side decomposition, dash attrs, cap/join,
reverse-reader variants, gradient stroke, and arrowheads."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

from defusedxml import ElementTree
from PIL import Image

from domoxml.core.drawingml.shape import shape_xml
from domoxml.core.html import serialize_canvas
from domoxml.core.ir import extract_slide
from domoxml.core.ir.model import (
    Arrowhead,
    Box,
    GradientFill,
    GradientStop,
    Line,
    Rgba,
    ShapeNode,
    SlideIR,
    SolidFill,
)
from domoxml.core.ir.parse import parse_border_side
from domoxml.core.render.browser import RenderedNode, RenderedSlide
from domoxml.slides.appearance_read import line as _line
from domoxml.types import Editability, Representation

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _rendered_slide(*nodes: RenderedNode) -> RenderedSlide:
    return RenderedSlide(png=_png(), width=200, height=150, scale=2.0, nodes=nodes)


# --------------------------------------------------------------------------- parse_border_side


def test_parse_border_side_returns_tuple() -> None:
    line, warn = parse_border_side("2px", "solid", "rgb(10,20,30)")
    assert line is not None
    assert line.dash == "solid"
    assert warn is None


def test_parse_border_side_double_warns() -> None:
    line, warn = parse_border_side("3px", "double", "rgb(0,0,0)")
    assert line is not None and line.dash == "solid"
    assert warn is not None and "double" in warn


def test_parse_border_side_groove_warns() -> None:
    for style in ("groove", "ridge", "inset", "outset"):
        _line, warn = parse_border_side("2px", style, "rgb(0,0,0)")
        assert _line is not None and _line.dash == "solid", f"dash not solid for {style}"
        assert warn is not None and style in warn, f"missing warning for {style}"


# --------------------------------------------------------------------------- per-side fwd decomp


def _node_with_borders(**border_styles: str) -> RenderedNode:
    """RenderedNode for a 100x80 px div with arbitrary inline border styles."""
    styles: dict[str, str] = {
        "borderTopWidth": "0px",
        "borderTopStyle": "none",
        "borderTopColor": "rgba(0,0,0,0)",
        "borderRightWidth": "0px",
        "borderRightStyle": "none",
        "borderRightColor": "rgba(0,0,0,0)",
        "borderBottomWidth": "0px",
        "borderBottomStyle": "none",
        "borderBottomColor": "rgba(0,0,0,0)",
        "borderLeftWidth": "0px",
        "borderLeftStyle": "none",
        "borderLeftColor": "rgba(0,0,0,0)",
        "backgroundColor": "rgba(0,0,0,0)",
        **border_styles,
    }
    return RenderedNode(tag="div", x=10, y=20, width=100, height=80, styles=styles)


def test_uniform_border_emits_single_shape_with_line() -> None:
    node = _node_with_borders(
        borderTopWidth="4px",
        borderTopStyle="solid",
        borderTopColor="rgb(0,0,255)",
        borderRightWidth="4px",
        borderRightStyle="solid",
        borderRightColor="rgb(0,0,255)",
        borderBottomWidth="4px",
        borderBottomStyle="solid",
        borderBottomColor="rgb(0,0,255)",
        borderLeftWidth="4px",
        borderLeftStyle="solid",
        borderLeftColor="rgb(0,0,255)",
    )
    result = extract_slide(_rendered_slide(node))
    # Uniform → one shape with a line, no extra border rects.
    assert len(result.slide.shapes) == 1
    shape = result.slide.shapes[0]
    assert shape.line is not None
    assert shape.line.dash == "solid"


def test_per_side_decomposition_left_only() -> None:
    """A border-left-only div → 1 border rect + 1 main shape, no a:ln on main."""
    node = _node_with_borders(
        borderLeftWidth="6px",
        borderLeftStyle="solid",
        borderLeftColor="rgb(220,38,38)",
    )
    result = extract_slide(_rendered_slide(node))
    # 2 shapes: the border rect and the main body rect
    assert len(result.slide.shapes) == 2
    border_rect, main_shape = result.slide.shapes
    # Border rect has solid fill (the border color) and no line
    assert isinstance(border_rect.fill, SolidFill)
    assert border_rect.fill.color.r == 220
    assert border_rect.line is None
    # Main shape has no line
    assert main_shape.line is None


def test_per_side_decomposition_exact_geometry_top_bottom() -> None:
    """Verify EMU offsets for top and bottom decomposition on a known box.

    Box: x=10, y=20, width=100, height=80 (px); top border 4px, bottom border 2px.
    Conversion: 1px = 9525 EMU.
    Expected top rect:    x=95250, y=190500, width=952500, height=38100
    Expected bottom rect: x=95250, y=190500+762000-19050=933450, width=952500, height=19050
    """
    from domoxml.core.units import px_to_emu

    node = _node_with_borders(
        borderTopWidth="4px",
        borderTopStyle="solid",
        borderTopColor="rgb(255,0,0)",
        borderBottomWidth="2px",
        borderBottomStyle="solid",
        borderBottomColor="rgb(0,255,0)",
    )
    result = extract_slide(_rendered_slide(node))
    # Should have 3 shapes: top rect, bottom rect, main body
    assert len(result.slide.shapes) == 3
    assert result.coverage[0].representation is Representation.DECOMPOSED
    assert result.coverage[0].editability is Editability.COMPONENTS
    assert result.coverage[0].output_count == 3
    top_rect, bottom_rect, _main = result.slide.shapes

    top_w_emu = px_to_emu(4)
    bot_w_emu = px_to_emu(2)
    box_x = px_to_emu(10)
    box_y = px_to_emu(20)
    box_w = px_to_emu(100)
    box_h = px_to_emu(80)

    assert top_rect.box == Box(x=box_x, y=box_y, width=box_w, height=top_w_emu)
    assert bottom_rect.box == Box(
        x=box_x, y=box_y + box_h - bot_w_emu, width=box_w, height=bot_w_emu
    )


def test_per_side_decomposition_left_right_clipped_to_interior() -> None:
    """Left/right rects span only the interior height (between top and bottom borders)."""
    from domoxml.core.units import px_to_emu

    node = _node_with_borders(
        borderTopWidth="4px",
        borderTopStyle="solid",
        borderTopColor="rgb(255,0,0)",
        borderBottomWidth="4px",
        borderBottomStyle="solid",
        borderBottomColor="rgb(255,0,0)",
        borderLeftWidth="8px",
        borderLeftStyle="solid",
        borderLeftColor="rgb(0,0,255)",
        borderRightWidth="8px",
        borderRightStyle="solid",
        borderRightColor="rgb(0,0,255)",
    )
    result = extract_slide(_rendered_slide(node))
    # 5 shapes: top, bottom, left, right, main
    assert len(result.slide.shapes) == 5
    assert result.coverage[0].representation is Representation.DECOMPOSED
    assert result.coverage[0].output_count == 5
    top_r, bottom_r, left_r, right_r, _main = result.slide.shapes
    _ = top_r, bottom_r  # verified via assert len above

    top_w = px_to_emu(4)
    bot_w = px_to_emu(4)
    left_w = px_to_emu(8)
    right_w = px_to_emu(8)
    box_x = px_to_emu(10)
    box_y = px_to_emu(20)
    box_w = px_to_emu(100)
    box_h = px_to_emu(80)

    interior_y = box_y + top_w
    interior_h = box_h - top_w - bot_w
    assert left_r.box == Box(x=box_x, y=interior_y, width=left_w, height=interior_h)
    assert right_r.box == Box(
        x=box_x + box_w - right_w, y=interior_y, width=right_w, height=interior_h
    )


def test_radius_plus_per_side_falls_back_to_heaviest_and_warns() -> None:
    """border-radius + non-uniform borders → approximation warning (no decomposition)."""
    node = _node_with_borders(
        borderTopWidth="4px",
        borderTopStyle="solid",
        borderTopColor="rgb(255,0,0)",
        borderRightWidth="4px",
        borderRightStyle="solid",
        borderRightColor="rgb(255,0,0)",
        borderBottomWidth="4px",
        borderBottomStyle="solid",
        borderBottomColor="rgb(255,0,0)",
        borderLeftWidth="8px",
        borderLeftStyle="solid",
        borderLeftColor="rgb(0,0,255)",
        borderRadius="8px",
    )
    result = extract_slide(_rendered_slide(node))
    # radius+non-uniform: single shape with line (heaviest) + warning
    assert len(result.slide.shapes) == 1
    assert result.slide.shapes[0].line is not None
    assert result.coverage[0].representation is Representation.APPROXIMATED
    messages = [w.message for w in result.warnings]
    assert any("approximated" in m for m in messages)


# --------------------------------------------------------------------------- dash emission (fwd)


def _line_xml_for(line: Line) -> str:
    """Build a shape_xml just to extract the a:ln element."""
    shape = ShapeNode(
        box=Box(x=0, y=0, width=100_000, height=100_000),
        line=line,
    )
    return shape_xml(shape, shape_id=1)


def test_dash_emission_dotted() -> None:
    line = Line(color=Rgba(r=0, g=0, b=0), width_emu=9525, dash="dot")
    xml = _line_xml_for(line)
    assert 'val="sysDot"' in xml


def test_dash_emission_dashed() -> None:
    line = Line(color=Rgba(r=0, g=0, b=0), width_emu=9525, dash="dash")
    xml = _line_xml_for(line)
    assert 'val="dash"' in xml


def test_dash_emission_lgDash() -> None:
    line = Line(color=Rgba(r=0, g=0, b=0), width_emu=9525, dash="lgDash")
    xml = _line_xml_for(line)
    assert 'val="lgDash"' in xml


def test_cap_join_emission() -> None:
    line = Line(
        color=Rgba(r=0, g=0, b=0),
        width_emu=9525,
        dash="solid",
        cap="round",
        join="bevel",
    )
    xml = _line_xml_for(line)
    assert 'cap="rnd"' in xml
    assert "<a:bevel/>" in xml


def test_miter_join_emission() -> None:
    line = Line(
        color=Rgba(r=0, g=0, b=0),
        width_emu=9525,
        dash="solid",
        cap="square",
        join="miter",
    )
    xml = _line_xml_for(line)
    assert 'cap="sq"' in xml
    assert '<a:miter lim="800000"/>' in xml


def test_gradient_stroke_emission() -> None:
    gradient = GradientFill(
        stops=(
            GradientStop(pos=0.0, color=Rgba(r=255, g=0, b=0)),
            GradientStop(pos=1.0, color=Rgba(r=0, g=0, b=255)),
        ),
        angle_deg=90.0,
    )
    line = Line(
        color=Rgba(r=128, g=0, b=0),
        width_emu=19050,
        gradient=gradient,
    )
    xml = _line_xml_for(line)
    assert "<a:gradFill>" in xml
    assert "<a:solidFill>" not in xml.split("<a:ln")[1].split("</a:ln>")[0]


def test_arrowhead_emission() -> None:
    line = Line(
        color=Rgba(r=0, g=0, b=0),
        width_emu=9525,
        head=Arrowhead(type="triangle", width="med", length="med"),
        tail=Arrowhead(type="stealth", width="lg", length="sm"),
    )
    xml = _line_xml_for(line)
    assert '<a:headEnd type="triangle"' in xml
    assert '<a:tailEnd type="stealth"' in xml
    assert 'w="lg"' in xml
    assert 'len="sm"' in xml


# --------------------------------------------------------------------------- reverse reader


def _make_ln_element(xml_body: str) -> ET.Element:
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    result: ET.Element = ElementTree.fromstring(f"<a:spPr {ns}>{xml_body}</a:spPr>")  # type: ignore[assignment]
    return result


def test_reverse_reads_cap_and_join() -> None:
    spPr = _make_ln_element(
        '<a:ln w="19050" cap="rnd"><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:bevel/></a:ln>'
    )
    line = _line(spPr, {})
    assert line is not None
    assert line.cap == "round"
    assert line.join == "bevel"


def test_reverse_reads_miter_join() -> None:
    spPr = _make_ln_element(
        '<a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>'
    )
    line = _line(spPr, {})
    assert line is not None
    assert line.join == "miter"


def test_reverse_reads_extended_dash_presets() -> None:
    for preset, expected in [
        ("lgDash", "lgDash"),
        ("dashDot", "dashDot"),
        ("lgDashDot", "dashDot"),
        ("sysDot", "dot"),
        ("sysDash", "sysDash"),
    ]:
        spPr = _make_ln_element(
            f'<a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
            f'<a:prstDash val="{preset}"/></a:ln>'
        )
        line = _line(spPr, {})
        assert line is not None, f"line is None for preset={preset}"
        assert line.dash == expected, f"dash={line.dash!r} for preset={preset}"


def test_reverse_reads_gradient_stroke() -> None:
    spPr = _make_ln_element(
        '<a:ln w="19050">'
        "<a:gradFill><a:gsLst>"
        '<a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="0000FF"/></a:gs>'
        "</a:gsLst>"
        '<a:lin ang="5400000" scaled="1"/>'
        "</a:gradFill>"
        '<a:prstDash val="solid"/>'
        "</a:ln>"
    )
    line = _line(spPr, {})
    assert line is not None
    assert line.gradient is not None
    assert len(line.gradient.stops) == 2
    assert line.gradient.stops[0].color.hex == "FF0000"
    assert line.gradient.stops[1].color.hex == "0000FF"
    # Flat color should be first-stop fallback
    assert line.color.hex == "FF0000"


def test_reverse_reads_arrowheads() -> None:
    spPr = _make_ln_element(
        '<a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
        '<a:prstDash val="solid"/>'
        '<a:headEnd type="triangle" w="med" len="lg"/>'
        '<a:tailEnd type="stealth" w="sm" len="med"/>'
        "</a:ln>"
    )
    line = _line(spPr, {})
    assert line is not None
    assert line.head is not None and line.head.type == "triangle"
    assert line.head.length == "lg"
    assert line.tail is not None and line.tail.type == "stealth"
    assert line.tail.width == "sm"


# --------------------------------------------------------------------------- gradient stroke → html


def test_gradient_stroke_emits_border_image_css() -> None:
    gradient = GradientFill(
        stops=(
            GradientStop(pos=0.0, color=Rgba(r=255, g=0, b=0)),
            GradientStop(pos=1.0, color=Rgba(r=0, g=0, b=255)),
        ),
        angle_deg=90.0,
    )
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=1_000_000, height=500_000),
                fill=SolidFill(color=Rgba(r=255, g=255, b=255)),
                line=Line(
                    color=Rgba(r=128, g=0, b=0),
                    width_emu=19050,
                    gradient=gradient,
                ),
            ),
        ),
    )
    result = serialize_canvas([slide])
    html = result.slides[0].html
    assert "border-image:" in html
    assert "linear-gradient" in html
    # Warning should note approximation
    msgs = [w.message for w in result.warnings]
    assert any("gradient stroke" in m for m in msgs)


def test_arrowhead_emits_warning_in_html() -> None:
    slide = SlideIR(
        width=12_192_000,
        height=6_858_000,
        shapes=(
            ShapeNode(
                box=Box(x=0, y=0, width=500_000, height=100_000),
                line=Line(
                    color=Rgba(r=0, g=0, b=0),
                    width_emu=9525,
                    head=Arrowhead(type="triangle", width="med", length="med"),
                ),
            ),
        ),
    )
    result = serialize_canvas([slide])
    msgs = [w.message for w in result.warnings]
    assert any("arrowhead" in m for m in msgs)
