"""OPC (Open Packaging Conventions) — write an OOXML package (a ZIP of parts).

Shared by every backend: a ``.pptx``/``.docx``/``.xlsx`` is an OPC zip; only the parts differ.
"""

from domoxml.core.opc.writer import write_package

__all__ = ["write_package"]
