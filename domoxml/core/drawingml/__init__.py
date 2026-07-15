"""DrawingML primitives — IR → ``a:*`` / shape XML. Byte-identical across pptx/docx/xlsx.

For now this emits the shape (``p:sp``) used on slides; the geometry/fill/text/effect
mappers here are the shared core future backends (docs, sheets) will reuse.
"""

from domoxml.core.drawingml.shape import line_xml, shape_xml
from domoxml.core.drawingml.table_xml import table_xml

__all__ = ["line_xml", "shape_xml", "table_xml"]
