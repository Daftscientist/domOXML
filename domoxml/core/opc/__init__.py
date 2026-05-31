"""OPC (Open Packaging Conventions) — read and write OOXML ZIP packages.

Shared by every backend: a ``.pptx``/``.docx``/``.xlsx`` is an OPC zip; only the parts differ.
"""

from domoxml.core.opc.reader import OpcPackage, Relationship
from domoxml.core.opc.writer import write_package

__all__ = ["OpcPackage", "Relationship", "write_package"]
