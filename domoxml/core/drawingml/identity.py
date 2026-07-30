"""Private OOXML extension for stable Canvas IR identity and provenance."""

from __future__ import annotations

from xml.sax.saxutils import escape

from domoxml.core.ir.effect_payload import encode_effects
from domoxml.core.ir.model import CanvasNode, FillOverlay, GradientFill, Shadow, ShapeNode

NAMESPACE = "urn:domoxml:canvas-ir:1"
EXTENSION_URI = "{A6E4A7B1-9D9C-4E8F-A94B-22CB18A8D72F}"


def _attr(value: str) -> str:
    return escape(
        value,
        {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"},
    )


def node_identity_xml(node: CanvasNode) -> str:
    """Return a ``p:extLst`` carrying domOXML metadata, or an empty string."""
    attributes: list[str] = []
    if node.node_id is not None:
        attributes.append(f'id="{_attr(node.node_id)}"')
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
    if isinstance(node, ShapeNode) and (
        node.native_effect_projection == "schema_subset"
        or any(isinstance(effect, Shadow) and effect.inset for effect in node.effects)
        or any(
            isinstance(effect, FillOverlay) and isinstance(effect.fill, GradientFill)
            for effect in node.effects
        )
        or any(
            isinstance(effect, FillOverlay) and effect.blend == "over" for effect in node.effects
        )
    ):
        intent = encode_effects(
            node.effects,
            container=node.effect_container,
            source_ref=node.effect_source_ref,
            native_projection=node.native_effect_projection,
        )
        attributes.append(f'effectIntent="{_attr(intent)}"')
    if not attributes:
        return ""
    joined = " ".join(attributes)
    return (
        f'<p:extLst><p:ext uri="{EXTENSION_URI}">'
        f'<dx:node xmlns:dx="{NAMESPACE}" {joined}/>'
        f"</p:ext></p:extLst>"
    )
