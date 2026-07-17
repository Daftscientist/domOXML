"""PresentationML-specific structure validation for generated and re-emitted PPTX packages."""

from __future__ import annotations

from collections import Counter
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree

from domoxml.core.opc import OpcPackage, Relationship, validate_opc_package

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PRESENTATION_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)


def _local_name(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: Element, name: str) -> list[Element]:
    return [child for child in element if _local_name(child) == name]


def _descendant(element: Element, *path: str) -> Element | None:
    current = element
    for name in path:
        current = next((child for child in current if _local_name(child) == name), None)
        if current is None:
            return None
    return current


def _relationship_id(element: Element) -> str | None:
    return element.get(f"{{{_R}}}id") or element.get(
        "{http://purl.oclc.org/ooxml/officeDocument/relationships}id"
    )


def _role(relationship: Relationship) -> str:
    return relationship.type.rsplit("/", 1)[-1]


def _relationships(
    package: OpcPackage, source: str | None, errors: list[str]
) -> tuple[Relationship, ...]:
    try:
        return package.relationships(source)
    except (KeyError, ParseError, ValueError) as error:
        errors.append(f"{source or '<package>'}: cannot read relationships: {error}")
        return ()


def _resolve(
    package: OpcPackage,
    source: str | None,
    relationship: Relationship,
    errors: list[str],
) -> str | None:
    if relationship.target_mode != "Internal":
        errors.append(
            f"{source or '<package>'}: {_role(relationship)} relationship "
            f"{relationship.id!r} must be internal"
        )
        return None
    try:
        target = package.resolve(source, relationship)
    except ValueError as error:
        errors.append(f"{source or '<package>'}: {relationship.id}: {error}")
        return None
    return target if package.has_part(target) else None


def _root(
    package: OpcPackage,
    part: str,
    expected: str,
    errors: list[str],
    *,
    namespace: str = _P,
) -> Element | None:
    if not package.has_part(part):
        errors.append(f"missing PPTX part: {part}")
        return None
    try:
        root = ElementTree.fromstring(package.read(part))
    except ParseError:
        return None  # The shared OPC validator already reports the parse error.
    expected_tag = f"{{{namespace}}}{expected}"
    if root.tag != expected_tag:
        errors.append(f"{part}: root {root.tag!r} != {expected_tag!r}")
        return None
    return root


def _positive_int(value: str | None) -> bool:
    try:
        return value is not None and int(value) > 0
    except ValueError:
        return False


def _required_relation(
    package: OpcPackage,
    source: str,
    role: str,
    errors: list[str],
) -> str | None:
    matches = [item for item in _relationships(package, source, errors) if _role(item) == role]
    if len(matches) != 1:
        errors.append(f"{source}: expected one {role} relationship, found {len(matches)}")
        return None
    return _resolve(package, source, matches[0], errors)


def _validate_slide(package: OpcPackage, part: str, errors: list[str]) -> None:
    root = _root(package, part, "sld", errors)
    if root is None:
        return
    if _descendant(root, "cSld", "spTree") is None:
        errors.append(f"{part}: missing p:cSld/p:spTree")
    ids = [element.get("id", "") for element in root.iter() if _local_name(element) == "cNvPr"]
    duplicates = sorted(item for item, count in Counter(ids).items() if item and count > 1)
    for shape_id in duplicates:
        errors.append(f"{part}: duplicate p:cNvPr id {shape_id!r}")

    layout_part = _required_relation(package, part, "slideLayout", errors)
    if layout_part is None:
        return
    layout = _root(package, layout_part, "sldLayout", errors)
    if layout is not None and _descendant(layout, "cSld", "spTree") is None:
        errors.append(f"{layout_part}: missing p:cSld/p:spTree")
    master_part = _required_relation(package, layout_part, "slideMaster", errors)
    if master_part is not None:
        _validate_master(package, master_part, errors)


def _validate_master(package: OpcPackage, part: str, errors: list[str]) -> None:
    root = _root(package, part, "sldMaster", errors)
    if root is None:
        return
    if _descendant(root, "cSld", "spTree") is None:
        errors.append(f"{part}: missing p:cSld/p:spTree")
    relationships = _relationships(package, part, errors)
    layouts = [item for item in relationships if _role(item) == "slideLayout"]
    themes = [item for item in relationships if _role(item) == "theme"]
    if not layouts:
        errors.append(f"{part}: missing slideLayout relationship")
    if not themes:
        errors.append(f"{part}: missing theme relationship")
    for relationship in layouts:
        target = _resolve(package, part, relationship, errors)
        if target is not None:
            _root(package, target, "sldLayout", errors)
    for relationship in themes:
        target = _resolve(package, part, relationship, errors)
        if target is not None:
            _root(package, target, "theme", errors, namespace=_A)


def _validate_presentation(package: OpcPackage, errors: list[str]) -> None:
    root_relationships = _relationships(package, None, errors)
    office_documents = [item for item in root_relationships if _role(item) == "officeDocument"]
    if len(office_documents) != 1:
        errors.append(
            f"<package>: expected one officeDocument relationship, found {len(office_documents)}"
        )
        return
    presentation_part = _resolve(package, None, office_documents[0], errors)
    if presentation_part is None:
        return
    try:
        content_type = package.content_type(presentation_part)
    except (KeyError, ParseError):
        content_type = None
    if content_type != _PRESENTATION_CONTENT_TYPE:
        errors.append(
            f"{presentation_part}: content type {content_type!r} != {_PRESENTATION_CONTENT_TYPE!r}"
        )
    presentation = _root(package, presentation_part, "presentation", errors)
    if presentation is None:
        return

    slide_size = _descendant(presentation, "sldSz")
    if (
        slide_size is None
        or not _positive_int(slide_size.get("cx"))
        or not _positive_int(slide_size.get("cy"))
    ):
        errors.append(f"{presentation_part}: p:sldSz requires positive cx and cy")

    relationships = {
        relationship.id: relationship
        for relationship in _relationships(package, presentation_part, errors)
    }
    slide_list = _descendant(presentation, "sldIdLst")
    slide_ids = _children(slide_list, "sldId") if slide_list is not None else []
    if not slide_ids:
        errors.append(f"{presentation_part}: presentation requires at least one p:sldId")
    numeric_ids = [item.get("id", "") for item in slide_ids]
    if len(set(numeric_ids)) != len(numeric_ids):
        errors.append(f"{presentation_part}: duplicate p:sldId id")
    if any(not _positive_int(item) for item in numeric_ids):
        errors.append(f"{presentation_part}: p:sldId id values must be positive integers")

    referenced_slides: set[str] = set()
    for slide_id in slide_ids:
        relationship_id = _relationship_id(slide_id)
        relationship = relationships.get(relationship_id or "")
        if relationship is None:
            errors.append(
                f"{presentation_part}: p:sldId references missing relationship {relationship_id!r}"
            )
            continue
        if _role(relationship) != "slide":
            errors.append(
                f"{presentation_part}: {relationship.id} has role {_role(relationship)!r}, "
                "expected 'slide'"
            )
            continue
        target = _resolve(package, presentation_part, relationship, errors)
        if target is not None:
            referenced_slides.add(target)
            _validate_slide(package, target, errors)

    declared_slides = {
        part
        for part in package.parts
        if not part.endswith(".rels")
        and package.has_part("[Content_Types].xml")
        and _content_type(package, part).endswith(".slide+xml")
    }
    for part in sorted(declared_slides - referenced_slides):
        errors.append(f"{part}: slide part is not referenced by the presentation")

    master_list = _descendant(presentation, "sldMasterIdLst")
    master_ids = _children(master_list, "sldMasterId") if master_list is not None else []
    if not master_ids:
        errors.append(f"{presentation_part}: missing p:sldMasterId")
    master_numeric_ids = [item.get("id", "") for item in master_ids]
    if len(set(master_numeric_ids)) != len(master_numeric_ids):
        errors.append(f"{presentation_part}: duplicate p:sldMasterId id")
    if any(not _positive_int(item) for item in master_numeric_ids):
        errors.append(f"{presentation_part}: p:sldMasterId id values must be positive integers")
    for master_id in master_ids:
        relationship_id = _relationship_id(master_id)
        relationship = relationships.get(relationship_id or "")
        if relationship is None or _role(relationship) != "slideMaster":
            errors.append(
                f"{presentation_part}: p:sldMasterId references invalid relationship "
                f"{relationship_id!r}"
            )
            continue
        target = _resolve(package, presentation_part, relationship, errors)
        if target is not None:
            _validate_master(package, target, errors)


def _content_type(package: OpcPackage, part: str) -> str:
    try:
        return package.content_type(part)
    except (KeyError, ParseError):
        return ""


def validate_pptx_package(data: bytes) -> tuple[str, ...]:
    """Return shared OPC and core PresentationML structure errors for ``data``."""
    errors = list(validate_opc_package(data))
    try:
        package = OpcPackage.from_bytes(data)
    except ValueError:
        return tuple(errors)
    _validate_presentation(package, errors)
    return tuple(dict.fromkeys(errors))
