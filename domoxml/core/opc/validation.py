"""Structural validation shared by every OOXML OPC package backend."""

from __future__ import annotations

from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from domoxml.core.opc.reader import OpcPackage, Relationship, normalize_part

_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
_OFFICE_REL_NAMESPACES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
}


def _xml_roots(package: OpcPackage, errors: list[str]) -> dict[str, Element]:
    roots: dict[str, Element] = {}
    for part in package.parts:
        if part != "[Content_Types].xml" and not part.endswith((".xml", ".rels")):
            continue
        try:
            roots[part] = ElementTree.fromstring(package.read(part))
        except (DefusedXmlException, ParseError) as error:
            errors.append(f"{part}: malformed XML: {error}")
    return roots


def _content_types(
    package: OpcPackage,
    roots: dict[str, Element],
    errors: list[str],
) -> None:
    root = roots.get("[Content_Types].xml")
    if root is None:
        if not package.has_part("[Content_Types].xml"):
            errors.append("missing OPC part: [Content_Types].xml")
        return
    expected_root = f"{{{_CT_NS}}}Types"
    if root.tag != expected_root:
        errors.append(f"[Content_Types].xml: root {root.tag!r} != {expected_root!r}")
        return

    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for element in root:
        if element.tag == f"{{{_CT_NS}}}Default":
            extension = element.get("Extension", "").lower().lstrip(".")
            content_type = element.get("ContentType", "")
            if not extension or not content_type:
                errors.append("[Content_Types].xml: Default requires Extension and ContentType")
                continue
            if extension in defaults:
                errors.append(f"[Content_Types].xml: duplicate Default extension {extension!r}")
                continue
            defaults[extension] = content_type
        elif element.tag == f"{{{_CT_NS}}}Override":
            raw_part = element.get("PartName", "")
            content_type = element.get("ContentType", "")
            if not raw_part or not content_type:
                errors.append("[Content_Types].xml: Override requires PartName and ContentType")
                continue
            try:
                part = normalize_part(raw_part)
            except ValueError as error:
                errors.append(f"[Content_Types].xml: {error}")
                continue
            if part in overrides:
                errors.append(f"[Content_Types].xml: duplicate Override part {part}")
                continue
            overrides[part] = content_type

    for part in package.parts:
        if part == "[Content_Types].xml":
            continue
        extension = (
            "rels" if part.endswith(".rels") else PurePosixPath(part).suffix.lower().lstrip(".")
        )
        content_type = overrides.get(part) or defaults.get(extension)
        if content_type is None:
            errors.append(f"{part}: no content type declared")
        elif part.endswith(".rels") and content_type != _REL_CONTENT_TYPE:
            errors.append(
                f"{part}: relationship content type {content_type!r} != {_REL_CONTENT_TYPE!r}"
            )
    for part in overrides:
        if not package.has_part(part):
            errors.append(f"[Content_Types].xml: Override targets missing {part}")


def _relationship_source(part: str) -> tuple[bool, str | None]:
    if part == "_rels/.rels":
        return True, None
    path = PurePosixPath(part)
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        return False, None
    return True, str(path.parent.parent / path.name.removesuffix(".rels"))


def _relationships(
    package: OpcPackage,
    roots: dict[str, Element],
    errors: list[str],
) -> dict[str | None, set[str]]:
    ids_by_source: dict[str | None, set[str]] = {}
    expected_root = f"{{{_PKG_REL_NS}}}Relationships"
    expected_child = f"{{{_PKG_REL_NS}}}Relationship"
    for part in (item for item in package.parts if item.endswith(".rels")):
        valid_source, source = _relationship_source(part)
        if not valid_source:
            errors.append(f"{part}: invalid relationship-part location")
            continue
        if isinstance(source, str) and not package.has_part(source):
            errors.append(f"{part}: relationship source part is missing: {source}")
        root = roots.get(part)
        if root is None:
            continue
        if root.tag != expected_root:
            errors.append(f"{part}: root {root.tag!r} != {expected_root!r}")
            continue

        ids: set[str] = set()
        ids_by_source[source] = ids
        for element in root:
            if element.tag != expected_child:
                errors.append(f"{part}: unexpected relationship child {element.tag!r}")
                continue
            relationship_id = element.get("Id", "")
            relationship_type = element.get("Type", "")
            target = element.get("Target", "")
            if not relationship_id or not relationship_type or not target:
                errors.append(f"{part}: Relationship requires Id, Type, and Target")
                continue
            if relationship_id in ids:
                errors.append(f"{part}: duplicate relationship ID {relationship_id!r}")
                continue
            ids.add(relationship_id)
            target_mode = element.get("TargetMode", "Internal")
            if target_mode not in {"Internal", "External"}:
                errors.append(f"{part}: {relationship_id} has invalid TargetMode {target_mode!r}")
                continue
            if target_mode == "External":
                continue
            try:
                resolved = package.resolve(
                    source if isinstance(source, str) else None,
                    Relationship(
                        id=relationship_id,
                        type=relationship_type,
                        target=target,
                    ),
                )
            except ValueError as error:
                errors.append(f"{part}: {relationship_id} has invalid target: {error}")
                continue
            if not package.has_part(resolved):
                errors.append(f"{part}: {relationship_id} targets missing {resolved}")
    return ids_by_source


def _relationship_references(
    roots: dict[str, Element],
    ids_by_source: dict[str | None, set[str]],
    errors: list[str],
) -> None:
    for part, root in roots.items():
        if part == "[Content_Types].xml" or part.endswith(".rels"):
            continue
        known_ids = ids_by_source.get(part, set())
        for element in root.iter():
            for attribute, relationship_id in element.attrib.items():
                if not attribute.startswith("{"):
                    continue
                namespace = attribute[1:].split("}", 1)[0]
                if namespace not in _OFFICE_REL_NAMESPACES:
                    continue
                if relationship_id not in known_ids:
                    local_name = attribute.rsplit("}", 1)[-1]
                    errors.append(
                        f"{part}: {local_name} references missing relationship {relationship_id!r}"
                    )


def validate_opc_package(data: bytes) -> tuple[str, ...]:
    """Return deterministic OPC structure errors without raising for malformed input."""
    try:
        package = OpcPackage.from_bytes(data)
    except ValueError as error:
        return (str(error),)
    errors: list[str] = []
    roots = _xml_roots(package, errors)
    _content_types(package, roots, errors)
    ids_by_source = _relationships(package, roots, errors)
    _relationship_references(roots, ids_by_source, errors)
    if not package.has_part("_rels/.rels"):
        errors.append("missing OPC part: _rels/.rels")
    return tuple(errors)
