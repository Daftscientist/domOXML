# pyright: reportPrivateUsage=false
"""Unit tests for custom geometry (SVG paths) and connectors — forward and reverse."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from domoxml.core.ir.model import (
    ClosePath,
    CubicTo,
    CustomGeometry,
    Fill,
    LineTo,
    MoveTo,
    PathCommand,
    Point,
    QuadTo,
    Rgba,
    SolidFill,
)
from domoxml.core.render.browser import RenderedNode
from domoxml.core.svg_path import commands_to_svg_d, parse_svg_path, scale_path_to_emu

# ---------------------------------------------------------------------------
# Group 1 - SVG d-parser
# ---------------------------------------------------------------------------


def test_parse_absolute_move_line_close() -> None:
    parsed = parse_svg_path("M 10 20 L 30 40 Z")
    assert parsed.bail_reason is None
    assert len(parsed.commands) == 3
    assert isinstance(parsed.commands[0], MoveTo)
    assert parsed.commands[0].to == Point(x=10, y=20)
    assert isinstance(parsed.commands[1], LineTo)
    assert parsed.commands[1].to == Point(x=30, y=40)
    assert isinstance(parsed.commands[2], ClosePath)


def test_parse_relative_move_and_line() -> None:
    # m 10 20 → cursor (10,20); l 5 5 → cursor (15,25); z
    parsed = parse_svg_path("m 10 20 l 5 5 z")
    assert parsed.bail_reason is None
    cmds = parsed.commands
    assert isinstance(cmds[0], MoveTo) and cmds[0].to == Point(x=10, y=20)
    assert isinstance(cmds[1], LineTo) and cmds[1].to == Point(x=15, y=25)
    assert isinstance(cmds[2], ClosePath)


def test_parse_horizontal_absolute() -> None:
    parsed = parse_svg_path("M 0 10 H 50")
    assert parsed.bail_reason is None
    assert isinstance(parsed.commands[1], LineTo)
    assert parsed.commands[1].to == Point(x=50, y=10)


def test_parse_horizontal_relative() -> None:
    parsed = parse_svg_path("M 10 10 h 20")
    assert isinstance(parsed.commands[1], LineTo)
    assert parsed.commands[1].to == Point(x=30, y=10)


def test_parse_vertical_absolute() -> None:
    parsed = parse_svg_path("M 5 0 V 40")
    assert isinstance(parsed.commands[1], LineTo)
    assert parsed.commands[1].to == Point(x=5, y=40)


def test_parse_vertical_relative() -> None:
    parsed = parse_svg_path("M 5 10 v 15")
    assert isinstance(parsed.commands[1], LineTo)
    assert parsed.commands[1].to == Point(x=5, y=25)


def test_parse_implicit_l_after_M() -> None:
    # M followed by extra coord pairs → implicit L
    parsed = parse_svg_path("M 0 0 10 10 20 20")
    cmds = parsed.commands
    assert isinstance(cmds[0], MoveTo) and cmds[0].to == Point(x=0, y=0)
    assert isinstance(cmds[1], LineTo) and cmds[1].to == Point(x=10, y=10)
    assert isinstance(cmds[2], LineTo) and cmds[2].to == Point(x=20, y=20)


def test_parse_implicit_l_after_m() -> None:
    # m followed by extra coord pairs → implicit l (relative lineto)
    parsed = parse_svg_path("m 0 0 10 10 10 10")
    cmds = parsed.commands
    assert isinstance(cmds[0], MoveTo) and cmds[0].to == Point(x=0, y=0)
    assert isinstance(cmds[1], LineTo) and cmds[1].to == Point(x=10, y=10)
    assert isinstance(cmds[2], LineTo) and cmds[2].to == Point(x=20, y=20)


def test_parse_cubic_absolute() -> None:
    parsed = parse_svg_path("M 0 0 C 10 10 90 10 100 0")
    assert parsed.bail_reason is None
    cmd = parsed.commands[1]
    assert isinstance(cmd, CubicTo)
    assert cmd.c1 == Point(x=10, y=10)
    assert cmd.c2 == Point(x=90, y=10)
    assert cmd.to == Point(x=100, y=0)


def test_parse_cubic_relative() -> None:
    # c: all 6 coords relative to cursor at (10,20)
    parsed = parse_svg_path("M 10 20 c 0 -10 90 -10 90 0")
    cmd = parsed.commands[1]
    assert isinstance(cmd, CubicTo)
    assert cmd.c1 == Point(x=10, y=10)
    assert cmd.c2 == Point(x=100, y=10)
    assert cmd.to == Point(x=100, y=20)


def test_parse_quadratic_absolute() -> None:
    parsed = parse_svg_path("M 0 0 Q 50 100 100 0")
    cmd = parsed.commands[1]
    assert isinstance(cmd, QuadTo)
    assert cmd.c1 == Point(x=50, y=100)
    assert cmd.to == Point(x=100, y=0)


def test_parse_quadratic_relative() -> None:
    # q: cursor at (10,20); dx1=40,dy1=80,dx=90,dy=0
    parsed = parse_svg_path("M 10 20 q 40 80 90 0")
    cmd = parsed.commands[1]
    assert isinstance(cmd, QuadTo)
    assert cmd.c1 == Point(x=50, y=100)
    assert cmd.to == Point(x=100, y=20)


def test_bail_on_arc_command() -> None:
    parsed = parse_svg_path("M 0 0 A 50 50 0 0 1 100 0")
    assert parsed.bail_reason is not None
    assert "A" in parsed.bail_reason or "unsupported" in parsed.bail_reason.lower()


def test_bail_on_smooth_cubic() -> None:
    parsed = parse_svg_path("M 0 0 S 50 50 100 0")
    assert parsed.bail_reason is not None


def test_bail_on_smooth_quadratic() -> None:
    parsed = parse_svg_path("M 0 0 T 100 0")
    assert parsed.bail_reason is not None


def test_empty_string_returns_empty() -> None:
    parsed = parse_svg_path("")
    assert parsed.commands == []
    assert parsed.bail_reason is None


def test_subpath_z_resets_pen() -> None:
    # After Z, the next M/m starts fresh; the subpath start is updated on each M.
    parsed = parse_svg_path("M 10 10 L 50 10 Z M 100 100 L 150 100 Z")
    assert parsed.bail_reason is None
    assert isinstance(parsed.commands[0], MoveTo)
    assert isinstance(parsed.commands[1], LineTo)
    assert isinstance(parsed.commands[2], ClosePath)
    assert isinstance(parsed.commands[3], MoveTo)
    assert parsed.commands[3].to == Point(x=100, y=100)


# ---------------------------------------------------------------------------
# Group 2 - EMU scaling math
# ---------------------------------------------------------------------------


def test_scale_moveto() -> None:
    cmds: list[PathCommand] = [MoveTo(to=Point(x=100, y=50))]
    scaled = scale_path_to_emu(cmds, vb_w=200.0, vb_h=100.0, box_emu_w=914400, box_emu_h=457200)
    result = scaled[0]
    assert isinstance(result, MoveTo)
    # 100/200 * 914400 = 457200
    assert result.to.x == 457200
    # 50/100 * 457200 = 228600
    assert result.to.y == 228600


def test_scale_cubicto_all_points() -> None:
    cmd: PathCommand = CubicTo(
        c1=Point(x=10, y=10),
        c2=Point(x=90, y=10),
        to=Point(x=100, y=0),
    )
    scaled = scale_path_to_emu([cmd], vb_w=100.0, vb_h=100.0, box_emu_w=100, box_emu_h=100)
    result = scaled[0]
    assert isinstance(result, CubicTo)
    assert result.c1 == Point(x=10, y=10)
    assert result.c2 == Point(x=90, y=10)
    assert result.to == Point(x=100, y=0)


def test_scale_closepath_passthrough() -> None:
    cmds: list[PathCommand] = [ClosePath()]
    scaled = scale_path_to_emu(cmds, vb_w=100.0, vb_h=100.0, box_emu_w=200, box_emu_h=200)
    assert isinstance(scaled[0], ClosePath)


def test_scale_non_square_aspect() -> None:
    # viewBox 200x100 → box 400x100 (x stretched 2x, y 1x)
    cmd: PathCommand = MoveTo(to=Point(x=100, y=50))
    scaled = scale_path_to_emu([cmd], vb_w=200.0, vb_h=100.0, box_emu_w=400, box_emu_h=100)
    result = scaled[0]
    assert isinstance(result, MoveTo)
    assert result.to.x == 200  # 100 * (400/200)
    assert result.to.y == 50  # 50 * (100/100)


# ---------------------------------------------------------------------------
# Group 3 - custGeom XML emission
# ---------------------------------------------------------------------------


def _build_custgeom() -> CustomGeometry:
    return CustomGeometry(
        width_emu=914400,
        height_emu=457200,
        path=(
            MoveTo(to=Point(x=0, y=0)),
            LineTo(to=Point(x=914400, y=0)),
            ClosePath(),
        ),
    )


def test_custgeom_xml_contains_moveto() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    xml = _custgeom_xml(_build_custgeom())
    assert "a:moveTo" in xml
    assert 'x="0"' in xml
    assert 'y="0"' in xml


def test_custgeom_xml_contains_lnto() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    xml = _custgeom_xml(_build_custgeom())
    assert "a:lnTo" in xml
    assert 'x="914400"' in xml


def test_custgeom_xml_contains_close() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    xml = _custgeom_xml(_build_custgeom())
    assert "a:close" in xml


def test_custgeom_xml_path_dimensions() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    xml = _custgeom_xml(_build_custgeom())
    assert 'w="914400"' in xml
    assert 'h="457200"' in xml


def test_custgeom_xml_cubic_emits_cubicbezto() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    cg = CustomGeometry(
        width_emu=100,
        height_emu=100,
        path=(
            MoveTo(to=Point(x=0, y=50)),
            CubicTo(
                c1=Point(x=0, y=10),
                c2=Point(x=100, y=10),
                to=Point(x=100, y=50),
            ),
            ClosePath(),
        ),
    )
    xml = _custgeom_xml(cg)
    assert "a:cubicBezTo" in xml
    # Should have exactly 3 a:pt children within cubicBezTo
    _ADML = "http://schemas.openxmlformats.org/drawingml/2006/main"
    wrapped = f'<root xmlns:a="{_ADML}">{xml}</root>'
    root = ET.fromstring(wrapped)
    cubic_els = root.findall(f".//{{{_ADML}}}cubicBezTo")
    assert len(cubic_els) == 1
    pts = cubic_els[0].findall(f"{{{_ADML}}}pt")
    assert len(pts) == 3


def test_custgeom_xml_quad_emits_quadbezto() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    cg = CustomGeometry(
        width_emu=100,
        height_emu=100,
        path=(
            MoveTo(to=Point(x=0, y=50)),
            QuadTo(c1=Point(x=50, y=0), to=Point(x=100, y=50)),
        ),
    )
    xml = _custgeom_xml(cg)
    assert "a:quadBezTo" in xml
    _ADML = "http://schemas.openxmlformats.org/drawingml/2006/main"
    wrapped = f'<root xmlns:a="{_ADML}">{xml}</root>'
    root = ET.fromstring(wrapped)
    quad_els = root.findall(f".//{{{_ADML}}}quadBezTo")
    assert len(quad_els) == 1
    pts = quad_els[0].findall(f"{{{_ADML}}}pt")
    assert len(pts) == 2


def test_custgeom_xml_boilerplate() -> None:
    from domoxml.core.drawingml.shape import _custgeom_xml

    xml = _custgeom_xml(_build_custgeom())
    assert "a:custGeom" in xml
    assert "a:avLst" in xml
    assert "a:pathLst" in xml


# ---------------------------------------------------------------------------
# Group 4 - Reverse custGeom → SVG round-trip
# ---------------------------------------------------------------------------


def test_commands_to_svg_d_moveto_lineto_close() -> None:
    d = commands_to_svg_d((MoveTo(to=Point(x=10, y=20)), LineTo(to=Point(x=100, y=0)), ClosePath()))
    assert d == "M 10 20 L 100 0 Z"


def test_commands_to_svg_d_cubicto() -> None:
    d = commands_to_svg_d(
        (CubicTo(c1=Point(x=10, y=10), c2=Point(x=90, y=10), to=Point(x=100, y=0)),)
    )
    assert d == "C 10 10 90 10 100 0"


def test_commands_to_svg_d_quadto() -> None:
    d = commands_to_svg_d((QuadTo(c1=Point(x=50, y=100), to=Point(x=100, y=0)),))
    assert d == "Q 50 100 100 0"


def test_round_trip_parse_emit_parse() -> None:
    """Parse → IR → d-string → parse again → same commands."""
    original = "M 10 50 C 10 10 190 10 190 50 Z"
    parsed = parse_svg_path(original)
    assert parsed.bail_reason is None

    d = commands_to_svg_d(tuple(parsed.commands))
    reparsed = parse_svg_path(d)
    assert reparsed.bail_reason is None
    assert len(reparsed.commands) == len(parsed.commands)
    for orig_cmd, rt_cmd in zip(parsed.commands, reparsed.commands, strict=True):
        assert type(orig_cmd) is type(rt_cmd)


# ---------------------------------------------------------------------------
# Group 5 - Connector reverse via _connector()
# ---------------------------------------------------------------------------

_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _cxnsp_el(prst: str, x: int, y: int, cx: int, cy: int) -> ET.Element:
    return ET.fromstring(
        f"""<p:cxnSp xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">
          <p:nvCxnSpPr>
            <p:cNvPr id="1" name="C"/>
            <p:cNvCxnSpPr/>
            <p:nvPr/>
          </p:nvCxnSpPr>
          <p:spPr>
            <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
            <a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>
          </p:spPr>
        </p:cxnSp>"""
    )


def test_connector_straight_kind() -> None:
    from domoxml.slides.connector_read import read_connector

    el = _cxnsp_el("line", x=100, y=200, cx=400, cy=0)
    conn = read_connector(el, lambda _properties: None)
    assert conn is not None
    assert conn.kind == "straight"


def test_connector_bent_kind() -> None:
    from domoxml.slides.connector_read import read_connector

    el = _cxnsp_el("bentConnector3", x=0, y=0, cx=300, cy=200)
    conn = read_connector(el, lambda _properties: None)
    assert conn is not None
    assert conn.kind == "bent"


def test_connector_curved_kind() -> None:
    from domoxml.slides.connector_read import read_connector

    el = _cxnsp_el("curvedConnector3", x=0, y=0, cx=300, cy=200)
    conn = read_connector(el, lambda _properties: None)
    assert conn is not None
    assert conn.kind == "curved"


def test_connector_bbox_straight_midline() -> None:
    from domoxml.slides.connector_read import read_connector

    # Horizontal: x=100, y=200, cx=400, cy=0 → straight midline y=200
    el = _cxnsp_el("line", x=100, y=200, cx=400, cy=0)
    conn = read_connector(el, lambda _properties: None)
    assert conn is not None
    assert conn.start.x == 100
    assert conn.end.x == 500  # 100 + 400


def test_connector_line_color_from_xml() -> None:
    from domoxml.slides.appearance_read import line
    from domoxml.slides.connector_read import read_connector

    el = ET.fromstring(
        f"""<p:cxnSp xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">
          <p:nvCxnSpPr>
            <p:cNvPr id="2" name="C"/>
            <p:cNvCxnSpPr/>
            <p:nvPr/>
          </p:nvCxnSpPr>
          <p:spPr>
            <a:xfrm><a:off x="0" y="0"/><a:ext cx="200" cy="0"/></a:xfrm>
            <a:prstGeom prst="line"><a:avLst/></a:prstGeom>
            <a:ln><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:ln>
          </p:spPr>
        </p:cxnSp>"""
    )
    conn = read_connector(el, lambda properties: line(properties, {}))
    assert conn is not None
    assert conn.line is not None
    assert conn.line.color.r == 255
    assert conn.line.color.g == 0
    assert conn.line.color.b == 0


# ---------------------------------------------------------------------------
# Group 6 - HR idiom detection
# ---------------------------------------------------------------------------


def test_hr_always_becomes_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="hr", x=0.0, y=100.0, width=300.0, height=1.0)
    conn = extract_connector(node, None, None)
    assert conn is not None
    assert conn.kind == "straight"


def test_hr_small_width_still_becomes_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="hr", x=0.0, y=0.0, width=10.0, height=1.0)
    conn = extract_connector(node, None, None)
    assert conn is not None


def test_thin_unfilled_div_becomes_horizontal_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="div", x=0.0, y=0.0, width=300.0, height=1.0)
    conn = extract_connector(node, None, None)
    assert conn is not None
    assert conn.kind == "straight"


def test_thin_filled_div_does_not_become_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="div", x=0.0, y=0.0, width=300.0, height=1.0)
    fill: Fill = SolidFill(color=Rgba(r=255, g=0, b=0))
    conn = extract_connector(node, fill, None)
    assert conn is None


def test_too_tall_div_does_not_become_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="div", x=0.0, y=0.0, width=300.0, height=30.0)
    conn = extract_connector(node, None, None)
    assert conn is None


def test_thin_vertical_div_becomes_vertical_connector() -> None:
    from domoxml.core.ir.connector_extract import extract_connector

    node = RenderedNode(tag="div", x=50.0, y=0.0, width=1.0, height=300.0)
    conn = extract_connector(node, None, None)
    assert conn is not None
    # Vertical: start/end should differ in y, not x
    assert conn.start.x == conn.end.x
    assert conn.start.y != conn.end.y
