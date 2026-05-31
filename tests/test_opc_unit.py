"""Shared OPC package reader tests."""

from __future__ import annotations

import pytest

from domoxml.core.opc import OpcPackage, Relationship, write_package

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _package() -> OpcPackage:
    return OpcPackage.from_bytes(
        write_package(
            {
                "_rels/.rels": (
                    f'<Relationships xmlns="{_PKG_REL}">'
                    f'<Relationship Id="rId1" Type="{_REL}/officeDocument" '
                    'Target="ppt/presentation.xml"/></Relationships>'
                ),
                "ppt/presentation.xml": b"<presentation/>",
                "ppt/_rels/presentation.xml.rels": (
                    f'<Relationships xmlns="{_PKG_REL}">'
                    f'<Relationship Id="rId1" Type="{_REL}/slide" '
                    'Target="slides/slide1.xml"/></Relationships>'
                ),
                "ppt/slides/slide1.xml": b"<slide/>",
            }
        )
    )


def test_reads_parts_and_root_relationships() -> None:
    package = _package()
    assert package.has_part("/ppt/presentation.xml")
    assert package.read("ppt/slides/slide1.xml") == b"<slide/>"
    [relationship] = package.relationships()
    assert relationship.id == "rId1"
    assert package.resolve(None, relationship) == "ppt/presentation.xml"


def test_resolves_relative_relationship_targets() -> None:
    package = _package()
    assert package.related_part("ppt/presentation.xml", "rId1") == "ppt/slides/slide1.xml"
    assert package.related_part_by_type(None, f"{_REL}/officeDocument") == "ppt/presentation.xml"


def test_rejects_external_relationship_resolution() -> None:
    package = _package()
    external = Relationship(
        id="rId1", type="link", target="https://example.com", target_mode="External"
    )
    with pytest.raises(ValueError, match="external"):
        package.resolve("ppt/presentation.xml", external)


def test_invalid_zip_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="ZIP"):
        OpcPackage.from_bytes(b"not-a-zip")
