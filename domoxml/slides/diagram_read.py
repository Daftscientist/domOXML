"""SmartArt as the shapes PowerPoint already drew for it.

A diagram (``dgm``) is stored as a data model plus layout rules, but PowerPoint also saves the
result of laying it out: a ``dsp:drawing`` part of ordinary shapes, positioned relative to the
graphic frame. Reading those shapes is what PowerPoint's own "Convert to Shapes" does: the
visual is exact and editable, and the data model and layout rules are not kept.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from domoxml.core.opc import OpcPackage

DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DSP = "http://schemas.microsoft.com/office/drawing/2008/diagram"
_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"a": _A, "p": _P, "dsp": _DSP, "dgm": _DGM}
_DRAWING_REL = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"
_CHILD = {"nvSpPr", "spPr", "style", "txBody"}


def diagram_shapes(frame: Element, package: OpcPackage, slide_part: str) -> list[Element] | None:
    """The drawing part's shapes as ``p:sp`` elements in slide coordinates, or ``None``.

    ``frame`` is the ``p:graphicFrame``. ``None`` means it is not a diagram, or its drawing part
    is missing (a file saved without a laid-out copy), so the caller keeps its other fallbacks.
    """
    data = frame.find(f".//{{{_A}}}graphicData", _NS)
    if data is None or data.get("uri") != DIAGRAM_URI:
        return None
    drawing_part = _drawing_part(frame, package, slide_part)
    if drawing_part is None:
        return None
    try:
        drawing = ElementTree.fromstring(package.read(drawing_part))
    except (KeyError, ValueError, ElementTree.ParseError):
        return None
    origin = frame.find("p:xfrm/a:off", _NS)
    dx = int(origin.get("x", "0")) if origin is not None else 0
    dy = int(origin.get("y", "0")) if origin is not None else 0
    frame_id = frame.find("p:nvGraphicFramePr/p:cNvPr", _NS)
    prefix = frame_id.get("id", "0") if frame_id is not None else "0"
    shapes: list[Element] = []
    for index, source in enumerate(drawing.iterfind(".//dsp:sp", _NS)):
        shape = _as_slide_shape(source, dx, dy, f"{prefix}.{index}")
        if shape is not None:
            shapes.append(shape)
    return shapes or None


def _drawing_part(frame: Element, package: OpcPackage, slide_part: str) -> str | None:
    """The diagram drawing part: named by the data model, else the slide's own relationship."""
    relationships = package.relationships(slide_part)
    ids = frame.find(f".//{{{_DGM}}}relIds", _NS)
    wanted: str | None = None
    if ids is not None:
        data_id = ids.get(f"{{{_R}}}dm")
        data_rel = next((r for r in relationships if r.id == data_id), None)
        if data_rel is not None:
            try:
                model = ElementTree.fromstring(package.read(package.resolve(slide_part, data_rel)))
            except (KeyError, ValueError, ElementTree.ParseError):
                model = None
            ext = model.find(f".//{{{_DSP}}}dataModelExt", _NS) if model is not None else None
            wanted = ext.get("relId") if ext is not None else None
    for relationship in relationships:
        if relationship.type == _DRAWING_REL and (wanted is None or relationship.id == wanted):
            try:
                return package.resolve(slide_part, relationship)
            except (KeyError, ValueError):
                return None
    return None


def _as_slide_shape(source: Element, dx: int, dy: int, shape_id: str) -> Element | None:
    """One ``dsp:sp`` rewritten as a ``p:sp`` whose position is relative to the slide."""
    shape = Element(f"{{{_P}}}sp")
    for child in source:
        name = child.tag.rsplit("}", 1)[-1]
        if name in _CHILD:
            shape.append(_renamed(child))
    properties = shape.find("p:spPr", _NS)
    offset = properties.find("a:xfrm/a:off", _NS) if properties is not None else None
    if properties is None or offset is None:
        return None
    offset.set("x", str(int(offset.get("x", "0")) + dx))
    offset.set("y", str(int(offset.get("y", "0")) + dy))
    identity = shape.find("p:nvSpPr/p:cNvPr", _NS)
    if identity is not None:
        identity.set("id", shape_id)
    return shape


def _renamed(element: Element) -> Element:
    """A copy of ``element`` with the diagram-drawing namespace swapped for PresentationML."""
    tag = element.tag
    if tag.startswith(f"{{{_DSP}}}"):
        tag = f"{{{_P}}}{tag.rsplit('}', 1)[-1]}"
    clone = Element(tag, dict(element.attrib))
    clone.text, clone.tail = element.text, element.tail
    clone.extend(_renamed(child) for child in element)
    return clone
