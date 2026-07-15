"""HTML line idiom to canvas-IR connector extraction."""

from __future__ import annotations

from domoxml.core.ir.model import Connector, Fill, Line, Point, Rgba
from domoxml.core.render.browser import RenderedNode
from domoxml.core.units import px_to_emu

_MAX_THIN_PX = 2.0
_MIN_LONG_PX = 40.0


def extract_connector(node: RenderedNode, fill: Fill | None, line: Line | None) -> Connector | None:
    """Map ``<hr>`` or a conservative thin unfilled element to a straight connector."""
    horizontal = node.height <= _MAX_THIN_PX and node.width >= _MIN_LONG_PX
    vertical = node.width <= _MAX_THIN_PX and node.height >= _MIN_LONG_PX
    if node.tag != "hr" and (fill is not None or not (horizontal or vertical)):
        return None

    x = px_to_emu(node.x)
    y = px_to_emu(node.y)
    width = px_to_emu(node.width)
    height = px_to_emu(node.height)
    if node.tag == "hr" or horizontal:
        start = Point(x=x, y=y + height // 2)
        end = Point(x=x + width, y=y + height // 2)
    else:
        start = Point(x=x + width // 2, y=y)
        end = Point(x=x + width // 2, y=y + height)
    resolved_line = line or Line(color=Rgba(r=0, g=0, b=0), width_emu=9525)
    return Connector(start=start, end=end, kind="straight", line=resolved_line)
