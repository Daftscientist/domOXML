"""Capture and serialize source-owned OPC dependency graphs."""

from __future__ import annotations

import base64
import contextlib
import math
import posixpath
from collections import deque
from collections.abc import Callable
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as StdElementTree
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from defusedxml import ElementTree

from domoxml.core.drawingml.identity import EXTENSION_URI, NAMESPACE
from domoxml.core.ir.model import (
    Box,
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
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
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

    register_source_namespaces(package.read(source_part))
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
    allocate_shape_id: Callable[[], int],
    relationship_ids: dict[str, str],
) -> str:
    """Rebind a preserved root and its descendants to unique slide-local shape IDs, at its box."""
    root = ElementTree.fromstring(node.payload.root_xml)
    _place(root, node)
    for descendant in root.iter():
        for attribute, relationship_id in tuple(descendant.attrib.items()):
            if attribute.startswith(f"{{{_R}}}") and relationship_id in relationship_ids:
                descendant.set(attribute, relationship_ids[relationship_id])

    shape_id_map: dict[str, str] = {}
    non_visuals = root.findall(".//p:cNvPr", _NS)
    if non_visuals:
        assigned_ids = [shape_id, *(allocate_shape_id() for _ in non_visuals[1:])]
        for non_visual, assigned_id in zip(non_visuals, assigned_ids, strict=True):
            source_id = non_visual.get("id")
            rebound_id = str(assigned_id)
            if source_id is not None:
                shape_id_map[source_id] = rebound_id
            non_visual.set("id", rebound_id)
    for connection in (
        *root.findall(f".//{{{_A}}}stCxn"),
        *root.findall(f".//{{{_A}}}endCxn"),
    ):
        source_id = connection.get("id")
        if source_id in shape_id_map:
            connection.set("id", shape_id_map[source_id])
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


def _top_transforms(root: Element) -> list[Element]:
    """The root shape's own ``xfrm`` (each alternative's, under ``mc:AlternateContent``)."""
    shapes = [root]
    if root.tag == f"{{{_MC}}}AlternateContent":
        shapes = [shape for alternative in root for shape in alternative]
    transforms: list[Element] = []
    for shape in shapes:
        kind = shape.tag.rsplit("}", 1)[-1]
        if kind == "graphicFrame":
            xfrm = shape.find(f"{{{_P}}}xfrm")
        elif kind == "grpSp":
            xfrm = shape.find(f"{{{_P}}}grpSpPr/{{{_A}}}xfrm")
        else:
            xfrm = shape.find(f"{{{_P}}}spPr/{{{_A}}}xfrm")
        if xfrm is not None:
            transforms.append(xfrm)
    return transforms


_PIXEL_EMU = 9525


def _near(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return all(abs(p - q) <= _PIXEL_EMU for p, q in zip(a, b, strict=True))


def _rotation(xfrm: Element) -> int | None:
    try:
        return int(xfrm.get("rot", "0") or 0)
    except ValueError:
        return None


def _bounds(width: int, height: int, rot: int) -> tuple[int, int]:
    """The axis-aligned size of a ``width`` x ``height`` frame turned by ``rot`` (60000ths of °)."""
    angle = math.radians(rot / 60_000)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    return round(width * cos + height * sin), round(width * sin + height * cos)


def _place(root: Element, node: PreservedNode) -> None:
    """Moves and scales the preserved root's transform by however much the node's box changed.

    The root XML keeps the transform it was read with, which belongs to ``payload.placed_box`` (the
    box when the payload was attached; it may describe a fallback picture rather than the shape). An
    object that was moved or resized, in the IR or as HTML captured back, lands where it is now;
    within a pixel of its placement (a capture's sub-pixel rounding) it keeps its source values.
    A group keeps its child offsets, so its contents scale. An unreadable rotation leaves it alone.
    """
    box = node.box
    placed = node.payload.placed_box or box
    for xfrm in _top_transforms(root):
        offset = xfrm.find(f"{{{_A}}}off")
        extent = xfrm.find(f"{{{_A}}}ext")
        rot = _rotation(xfrm)
        if offset is None or extent is None or rot is None:
            continue
        target = box
        if rot % 21_600_000 and _near(
            (box.width, box.height), _bounds(placed.width, placed.height, rot)
        ):
            # A turned object captured from HTML reports its bounds: it moved, at its own size.
            centre_x, centre_y = box.x + box.width // 2, box.y + box.height // 2
            target = Box(
                x=centre_x - placed.width // 2,
                y=centre_y - placed.height // 2,
                width=placed.width,
                height=placed.height,
            )
        if _near(
            (target.x, target.y, target.width, target.height),
            (placed.x, placed.y, placed.width, placed.height),
        ):
            continue
        scale_x = target.width / placed.width if placed.width else 1.0
        scale_y = target.height / placed.height if placed.height else 1.0
        x, y = int(offset.get("x", "0")), int(offset.get("y", "0"))
        width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
        offset.set("x", str(round(target.x + (x - placed.x) * scale_x)))
        offset.set("y", str(round(target.y + (y - placed.y) * scale_y)))
        extent.set("cx", str(max(1, round(width * scale_x))))
        extent.set("cy", str(max(1, round(height * scale_y))))


def register_source_namespaces(xml: bytes) -> None:
    """Register the prefixes ``xml`` declares, so re-serialising keeps names a document relies on.

    A ``mc:Choice Requires="am3d"`` names a prefix, not a namespace: serialising with generated
    ``ns0``-style prefixes would leave it dangling and PowerPoint would reject the choice.
    """
    for _event, declaration in ElementTree.iterparse(BytesIO(xml), events=("start-ns",)):
        prefix, namespace = str(declaration[0]), str(declaration[1])
        if prefix:
            with contextlib.suppress(ValueError):
                StdElementTree.register_namespace(prefix, namespace)


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
