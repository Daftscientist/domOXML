"""PresentationML connector to canvas-IR parsing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from xml.etree.ElementTree import Element

from domoxml.core.ir.model import Connector, Line, Point, Rgba

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}

type LineParser = Callable[[Element], Line | None]


def _int_attr(element: Element, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, str(default)))
    except ValueError:
        return default


def read_connector(element: Element, line_for: LineParser) -> Connector | None:
    """Parse one ``p:cxnSp`` element into a connector node."""
    properties = element.find("p:spPr", _NS)
    transform = properties.find("a:xfrm", _NS) if properties is not None else None
    offset = transform.find("a:off", _NS) if transform is not None else None
    extent = transform.find("a:ext", _NS) if transform is not None else None
    if properties is None or offset is None or extent is None:
        return None
    x = _int_attr(offset, "x")
    y = _int_attr(offset, "y")
    width = _int_attr(extent, "cx")
    height = _int_attr(extent, "cy")
    geometry = properties.find("a:prstGeom", _NS)
    preset = geometry.get("prst", "line") if geometry is not None else "line"
    kind: Literal["straight", "bent", "curved"] = "straight"
    if preset.startswith("bentConnector"):
        kind = "bent"
    elif preset.startswith("curvedConnector"):
        kind = "curved"
    line = line_for(properties) or Line(color=Rgba(r=0, g=0, b=0), width_emu=9525)
    return Connector(
        start=Point(x=x, y=y + height // 2),
        end=Point(x=x + width, y=y + height // 2),
        kind=kind,
        line=line,
    )
