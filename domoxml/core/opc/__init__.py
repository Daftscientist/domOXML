"""OPC (Open Packaging Conventions) — read and write OOXML ZIP packages.

Shared by every backend: a ``.pptx``/``.docx``/``.xlsx`` is an OPC zip; only the parts differ.
"""

from domoxml.core.opc.preservation import (
    capture_payload,
    decode_payload,
    encode_payload,
    relationship_part_name,
    relationships_xml,
    rewrite_root_xml,
)
from domoxml.core.opc.reader import OpcPackage, Relationship
from domoxml.core.opc.writer import write_package

__all__ = [
    "OpcPackage",
    "Relationship",
    "capture_payload",
    "decode_payload",
    "encode_payload",
    "relationship_part_name",
    "relationships_xml",
    "rewrite_root_xml",
    "write_package",
]
