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


def diagram_shapes(
    frame: Element, package: OpcPackage, slide_part: str
) -> tuple[list[Element], str] | None:
    """The drawing part's shapes as ``p:sp`` elements in slide coordinates, and that part's name.

    ``frame`` is the ``p:graphicFrame``. ``None`` means it is not a diagram, or its drawing part
    is missing or ambiguous (a file saved without a laid-out copy), so the caller keeps its
    other fallbacks. The part name is returned because the shapes' relationships (images,
    links) belong to the drawing part, not to the slide.
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
    return (shapes, drawing_part) if shapes else None


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
    drawings = [r for r in relationships if r.type == _DRAWING_REL]
    # An unnamed drawing is only safe to pick when the slide has exactly one.
    chosen = [r for r in drawings if r.id == wanted] if wanted is not None else drawings
    if len(chosen) != 1:
        return None
    try:
        return package.resolve(slide_part, chosen[0])
    except (KeyError, ValueError):
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
    _apply_style(shape, properties)
    return shape


_FILLS = ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")
_GEOMETRY = ("prstGeom", "custGeom")


def _apply_style(shape: Element, properties: Element) -> None:
    """Write the colours ``dsp:style`` references into the shape, where the reader looks.

    A diagram shape can leave its fill, outline and text colour to the style references
    (``fillRef``, ``lnRef``, ``fontRef``); the reader only follows explicit properties, so the
    referenced colours are made explicit rather than dropped.
    """
    style = shape.find("p:style", _NS)
    if style is None:
        return

    def colour(reference: str) -> Element | None:
        element = style.find(f"a:{reference}", _NS)
        if element is None or element.get("idx", "0") == "0":
            return None
        return next(iter(element), None)

    position = next(
        (i + 1 for i, child in enumerate(properties) if _local(child) in _GEOMETRY), len(properties)
    )
    fill_colour = colour("fillRef")
    if fill_colour is not None and not any(_local(c) in _FILLS for c in properties):
        fill = Element(f"{{{_A}}}solidFill")
        fill.append(fill_colour)
        properties.insert(position, fill)
        position += 1
    line_colour = colour("lnRef")
    if line_colour is not None and properties.find("a:ln", _NS) is None:
        line = Element(f"{{{_A}}}ln", {"w": "12700"})
        solid = Element(f"{{{_A}}}solidFill")
        solid.append(line_colour)
        line.append(solid)
        properties.insert(position, line)
    text_colour = colour("fontRef")
    if text_colour is not None:
        for run in shape.iterfind(".//a:r", _NS):
            run_properties = run.find("a:rPr", _NS)
            if run_properties is None:
                run_properties = Element(f"{{{_A}}}rPr")
                run.insert(0, run_properties)
            if not any(_local(c) in _FILLS for c in run_properties):
                fill = Element(f"{{{_A}}}solidFill")
                fill.append(text_colour)
                run_properties.insert(0, fill)


def _local(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _renamed(element: Element) -> Element:
    """A copy of ``element`` with the diagram-drawing namespace swapped for PresentationML."""
    tag = element.tag
    if tag.startswith(f"{{{_DSP}}}"):
        tag = f"{{{_P}}}{tag.rsplit('}', 1)[-1]}"
    clone = Element(tag, dict(element.attrib))
    clone.text, clone.tail = element.text, element.tail
    clone.extend(_renamed(child) for child in element)
    return clone
