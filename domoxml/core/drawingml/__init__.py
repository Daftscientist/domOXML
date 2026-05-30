"""DrawingML primitives — IR → ``a:*`` / shape XML. Byte-identical across pptx/docx/xlsx.

For now this emits the shape (``p:sp``) used on slides; the geometry/fill/text/effect
mappers here are the shared core future backends (docs, sheets) will reuse.
"""

from domoxml.core.drawingml.shape import shape_xml

__all__ = ["shape_xml"]
