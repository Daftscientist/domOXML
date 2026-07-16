"""Capture and serialize source-owned OPC dependency graphs."""

from __future__ import annotations

import base64
import posixpath
from collections import deque
from pathlib import PurePosixPath
from xml.etree import ElementTree as StdElementTree
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from defusedxml import ElementTree

from domoxml.core.drawingml.identity import EXTENSION_URI, NAMESPACE
from domoxml.core.ir.model import (
    PreservationPart,
    PreservationPayload,
    PreservationRelationship,
    PreservedNode,
)
from domoxml.core.opc.reader import OpcPackage, Relationship

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"p": _P}
_RID = f"{{{_R}}}id"


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _retained_relationship(
    package: OpcPackage, source_part: str, relationship: Relationship
) -> PreservationRelationship:
    target = (
        package.resolve(source_part, relationship)
        if relationship.target_mode == "Internal"
        else relationship.target
    )
    target_mode = "External" if relationship.target_mode == "External" else "Internal"
    return PreservationRelationship(
        id=relationship.id,
        type=relationship.type,
        target=target,
        target_mode=target_mode,
    )


def capture_payload(
    package: OpcPackage,
    source_part: str,
    element: Element,
    *,
    kind: str,
    ambient_theme_part: str | None = None,
) -> PreservationPayload:
    """Capture ``element`` and the transitive internal OPC graph it references."""
    referenced_ids = {
        value
        for descendant in element.iter()
        for attribute, value in descendant.attrib.items()
        if attribute.startswith(f"{{{_R}}}")
    }
    source_relationships = {
        relationship.id: relationship for relationship in package.relationships(source_part)
    }
    missing_relationships = referenced_ids - source_relationships.keys()
    if missing_relationships:
        missing = ", ".join(sorted(missing_relationships))
        raise KeyError(f"missing preserved root relationship(s) from {source_part}: {missing}")
    root_relationships = tuple(
        _retained_relationship(package, source_part, source_relationships[relationship_id])
        for relationship_id in sorted(referenced_ids)
    )

    queue = deque(
        relationship.target
        for relationship in root_relationships
        if relationship.target_mode == "Internal"
    )
    ambient_theme: PreservationPart | None = None
    if ambient_theme_part is not None:
        theme_relationships = tuple(
            _retained_relationship(package, ambient_theme_part, relationship)
            for relationship in package.relationships(ambient_theme_part)
        )
        ambient_theme = PreservationPart(
            name=ambient_theme_part,
            content_type=package.content_type(ambient_theme_part),
            data=package.read(ambient_theme_part),
            relationships=theme_relationships,
        )
        queue.extend(
            relationship.target
            for relationship in theme_relationships
            if relationship.target_mode == "Internal"
        )
    seen: set[str] = set()
    parts: list[PreservationPart] = []
    while queue:
        part_name = queue.popleft()
        if part_name in seen:
            continue
        seen.add(part_name)
        relationships = tuple(
            _retained_relationship(package, part_name, relationship)
            for relationship in package.relationships(part_name)
        )
        parts.append(
            PreservationPart(
                name=part_name,
                content_type=package.content_type(part_name),
                data=package.read(part_name),
                relationships=relationships,
            )
        )
        queue.extend(
            relationship.target
            for relationship in relationships
            if relationship.target_mode == "Internal"
        )

    return PreservationPayload(
        kind=kind,
        root_xml=ElementTree.tostring(element, encoding="unicode"),
        relationships=root_relationships,
        parts=tuple(sorted(parts, key=lambda part: part.name)),
        ambient_theme=ambient_theme,
    )


def encode_payload(payload: PreservationPayload) -> str:
    """Encode a payload as URL-safe base64 JSON for normalized HTML metadata."""
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode("ascii")


def decode_payload(value: str) -> PreservationPayload:
    """Decode normalized HTML payload metadata with strict Pydantic validation."""
    raw = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    return PreservationPayload.model_validate_json(raw)


def _identity_attributes(node: PreservedNode) -> dict[str, str]:
    attributes = {"id": node.node_id or ""}
    provenance = node.provenance
    if provenance is None:
        return attributes
    attributes.update(
        {
            "sourceFormat": provenance.source_format,
            "sourceId": provenance.source_id,
        }
    )
    if provenance.source_part is not None:
        attributes["sourcePart"] = provenance.source_part
    if provenance.owner_node_id is not None:
        attributes["ownerId"] = provenance.owner_node_id
    if provenance.role is not None:
        attributes["role"] = provenance.role
    return attributes


def rewrite_root_xml(
    node: PreservedNode,
    *,
    shape_id: int,
    relationship_ids: dict[str, str],
) -> str:
    """Rebind a preserved root element to new slide IDs and attach current node identity."""
    root = ElementTree.fromstring(node.payload.root_xml)
    for descendant in root.iter():
        for attribute, relationship_id in tuple(descendant.attrib.items()):
            if attribute.startswith(f"{{{_R}}}") and relationship_id in relationship_ids:
                descendant.set(attribute, relationship_ids[relationship_id])

    non_visual = root.find("./*/p:cNvPr", _NS)
    if non_visual is not None:
        non_visual.set("id", str(shape_id))
    application_properties = root.find("./*/p:nvPr", _NS)
    if application_properties is not None and node.node_id is not None:
        extension_list = application_properties.find("p:extLst", _NS)
        if extension_list is None:
            extension_list = StdElementTree.SubElement(application_properties, f"{{{_P}}}extLst")
        for extension in tuple(extension_list):
            if extension.get("uri") == EXTENSION_URI:
                extension_list.remove(extension)
        extension = StdElementTree.SubElement(
            extension_list, f"{{{_P}}}ext", {"uri": EXTENSION_URI}
        )
        StdElementTree.SubElement(
            extension,
            f"{{{NAMESPACE}}}node",
            _identity_attributes(node),
        )

    for prefix, namespace in (("a", _A), ("c", _C), ("p", _P), ("r", _R), ("dx", NAMESPACE)):
        StdElementTree.register_namespace(prefix, namespace)
    return StdElementTree.tostring(root, encoding="unicode")


def relationship_part_name(source_part: str) -> str:
    """Return the conventional relationship-part name for one OPC source part."""
    source = PurePosixPath(source_part)
    return str(source.parent / "_rels" / f"{source.name}.rels")


def relationships_xml(
    source_part: str,
    relationships: tuple[PreservationRelationship, ...],
) -> str:
    """Serialize retained relationships relative to their emitted owning part."""
    entries: list[str] = []
    source_directory = posixpath.dirname(source_part)
    for relationship in relationships:
        target = relationship.target
        mode = ""
        if relationship.target_mode == "Internal":
            target = posixpath.relpath(target, source_directory)
        else:
            mode = ' TargetMode="External"'
        entries.append(
            f'<Relationship Id="{_attr(relationship.id)}" Type="{_attr(relationship.type)}" '
            f'Target="{_attr(target)}"{mode}/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">{"".join(entries)}</Relationships>'
    )
