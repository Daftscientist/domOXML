"""Read OPC (OOXML) ZIP packages and resolve internal relationships."""

from __future__ import annotations

import io
import posixpath
import zipfile
from pathlib import PurePosixPath

from defusedxml import ElementTree
from pydantic import BaseModel, ConfigDict

_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


class Relationship(BaseModel):
    """One OPC relationship from a source part to an internal or external target."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: str
    target: str
    target_mode: str = "Internal"


class OpcPackage:
    """An immutable in-memory OPC package."""

    def __init__(self, parts: dict[str, bytes]) -> None:
        self._parts = dict(parts)

    @classmethod
    def from_bytes(cls, data: bytes) -> OpcPackage:
        """Load an OPC ZIP from bytes, rejecting invalid or duplicate part names."""
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                parts: dict[str, bytes] = {}
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = normalize_part(info.filename)
                    if name in parts:
                        raise ValueError(f"duplicate OPC part: {name}")
                    parts[name] = archive.read(info)
        except zipfile.BadZipFile as exc:
            raise ValueError("invalid OPC package: expected a ZIP archive") from exc
        return cls(parts)

    @property
    def parts(self) -> tuple[str, ...]:
        """Sorted package part names."""
        return tuple(sorted(self._parts))

    def has_part(self, part: str) -> bool:
        """Whether ``part`` exists in the package."""
        return normalize_part(part) in self._parts

    def read(self, part: str) -> bytes:
        """Read one required part or raise a clear error."""
        normalized = normalize_part(part)
        try:
            return self._parts[normalized]
        except KeyError as exc:
            raise KeyError(f"missing OPC part: {normalized}") from exc

    def relationships(self, source_part: str | None = None) -> tuple[Relationship, ...]:
        """Read relationships for ``source_part``; ``None`` means package-root rels."""
        rels_part = _rels_part(source_part)
        if rels_part not in self._parts:
            return ()
        root = ElementTree.fromstring(self._parts[rels_part])
        return tuple(
            Relationship(
                id=element.attrib["Id"],
                type=element.attrib["Type"],
                target=element.attrib["Target"],
                target_mode=element.attrib.get("TargetMode", "Internal"),
            )
            for element in root.findall(f"{{{_PKG_REL_NS}}}Relationship")
        )

    def resolve(self, source_part: str | None, relationship: Relationship) -> str:
        """Resolve an internal relationship target to a normalized package part path."""
        if relationship.target_mode != "Internal":
            raise ValueError(f"cannot resolve external relationship: {relationship.target}")
        base = "" if source_part is None else posixpath.dirname(normalize_part(source_part))
        return normalize_part(posixpath.join(base, relationship.target))

    def related_part(self, source_part: str | None, relationship_id: str) -> str:
        """Resolve one relationship ID from ``source_part`` to an internal package part."""
        for relationship in self.relationships(source_part):
            if relationship.id == relationship_id:
                return self.resolve(source_part, relationship)
        label = source_part or "<package>"
        raise KeyError(f"missing relationship {relationship_id!r} from {label}")

    def related_part_by_type(self, source_part: str | None, relationship_type: str) -> str:
        """Resolve the first internal relationship with ``relationship_type``."""
        for relationship in self.relationships(source_part):
            if relationship.type == relationship_type:
                return self.resolve(source_part, relationship)
        label = source_part or "<package>"
        raise KeyError(f"missing relationship type {relationship_type!r} from {label}")

    def content_type(self, part: str) -> str:
        """Resolve one part's content type from OPC overrides and extension defaults."""
        normalized = normalize_part(part)
        root = ElementTree.fromstring(self.read("[Content_Types].xml"))
        for override in root.findall(f"{{{_CT_NS}}}Override"):
            if override.get("PartName", "").lstrip("/") == normalized:
                return override.attrib["ContentType"]
        extension = PurePosixPath(normalized).suffix.lstrip(".")
        for default in root.findall(f"{{{_CT_NS}}}Default"):
            if default.get("Extension", "").lower() == extension.lower():
                return default.attrib["ContentType"]
        raise KeyError(f"no content type declared for OPC part: {normalized}")


def normalize_part(part: str) -> str:
    """Normalize and validate a ZIP-relative OPC part path."""
    normalized = posixpath.normpath(part.replace("\\", "/")).lstrip("/")
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"invalid OPC part path: {part!r}")
    return normalized


def _rels_part(source_part: str | None) -> str:
    if source_part is None:
        return "_rels/.rels"
    source = PurePosixPath(normalize_part(source_part))
    return str(source.parent / "_rels" / f"{source.name}.rels")
