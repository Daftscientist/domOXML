"""Shared OPC package reader tests."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from domoxml.core.opc import OpcPackage, Relationship, capture_payload, write_package

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


def test_resolves_override_and_default_content_types() -> None:
    package = OpcPackage.from_bytes(
        write_package(
            {
                "[Content_Types].xml": (
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/ppt/charts/chart1.xml" ContentType="chart/type"/>'
                    "</Types>"
                ),
                "ppt/charts/chart1.xml": b"<chart/>",
                "ppt/other.xml": b"<other/>",
            }
        )
    )

    assert package.content_type("ppt/charts/chart1.xml") == "chart/type"
    assert package.content_type("ppt/other.xml") == "application/xml"


def test_capture_payload_rejects_missing_root_relationship() -> None:
    package = OpcPackage.from_bytes(
        write_package(
            {
                "[Content_Types].xml": (
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    "</Types>"
                ),
                "ppt/slides/slide1.xml": b"<slide/>",
            }
        )
    )
    element = ElementTree.fromstring(
        "<p:graphicFrame "
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'r:id="rId9"/>'
    )

    with pytest.raises(KeyError, match=r"missing preserved root relationship.*rId9"):
        capture_payload(package, "ppt/slides/slide1.xml", element, kind="graphicFrame")
