"""Private OOXML extension for stable Canvas IR identity and provenance."""

from __future__ import annotations

from xml.sax.saxutils import escape

from domoxml.core.ir.model import CanvasNode

NAMESPACE = "urn:domoxml:canvas-ir:1"
EXTENSION_URI = "{A6E4A7B1-9D9C-4E8F-A94B-22CB18A8D72F}"


def _attr(value: str) -> str:
    return escape(
        value,
        {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"},
    )


def node_identity_xml(node: CanvasNode) -> str:
    """Return a ``p:extLst`` carrying domOXML metadata, or an empty string."""
    if node.node_id is None:
        return ""
    attributes = [f'id="{_attr(node.node_id)}"']
    provenance = node.provenance
    if provenance is not None:
        attributes.extend(
            (
                f'sourceFormat="{provenance.source_format}"',
                f'sourceId="{_attr(provenance.source_id)}"',
            )
        )
        if provenance.source_part is not None:
            attributes.append(f'sourcePart="{_attr(provenance.source_part)}"')
        if provenance.owner_node_id is not None:
            attributes.append(f'ownerId="{_attr(provenance.owner_node_id)}"')
        if provenance.role is not None:
            attributes.append(f'role="{_attr(provenance.role)}"')
    joined = " ".join(attributes)
    return (
        f'<p:extLst><p:ext uri="{EXTENSION_URI}">'
        f'<dx:node xmlns:dx="{NAMESPACE}" {joined}/>'
        f"</p:ext></p:extLst>"
    )
