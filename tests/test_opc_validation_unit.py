"""Shared OPC and PPTX package validation tests."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from domoxml.core.ir.model import Box, PictureFill, ShapeNode, SlideIR
from domoxml.core.opc import OpcPackage, validate_opc_package, write_package
from domoxml.slides import build_pptx, validate_pptx_package

_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _slide(*shapes: ShapeNode) -> SlideIR:
    return SlideIR(width=12_192_000, height=6_858_000, shapes=shapes)


def _picture() -> PictureFill:
    output = BytesIO()
    Image.new("RGB", (8, 8), "#4472C4").save(output, "PNG")
    return PictureFill(data=output.getvalue(), ext="png")


def _parts(pptx: bytes) -> dict[str, bytes]:
    package = OpcPackage.from_bytes(pptx)
    return {part: package.read(part) for part in package.parts}


def _package(parts: dict[str, bytes | str]) -> bytes:
    return write_package(
        {
            "[Content_Types].xml": (
                f'<Types xmlns="{_CT}">'
                '<Default Extension="rels" '
                'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                "</Types>"
            ),
            "_rels/.rels": f'<Relationships xmlns="{_PKG_REL}"/>',
            **parts,
        }
    )


def test_generated_deck_passes_shared_and_pptx_validation() -> None:
    pptx = build_pptx([_slide()], faces=[])

    assert validate_opc_package(pptx) == ()
    assert validate_pptx_package(pptx) == ()


def test_invalid_zip_returns_a_diagnostic() -> None:
    assert validate_opc_package(b"not a zip") == ("invalid OPC package: expected a ZIP archive",)


def test_reports_missing_content_types_and_root_relationships() -> None:
    pptx = write_package({"part.bin": b"data"})

    errors = validate_opc_package(pptx)

    assert "missing OPC part: [Content_Types].xml" in errors
    assert "missing OPC part: _rels/.rels" in errors


def test_reports_undeclared_and_stale_content_types() -> None:
    pptx = _package({"ppt/item.bin": b"data"})
    parts = _parts(pptx)
    content_types = parts["[Content_Types].xml"].replace(
        b"</Types>",
        b'<Override PartName="/ppt/missing.xml" ContentType="application/xml"/></Types>',
    )
    parts["[Content_Types].xml"] = content_types

    errors = validate_opc_package(write_package(parts))

    assert "ppt/item.bin: no content type declared" in errors
    assert "[Content_Types].xml: Override targets missing ppt/missing.xml" in errors


def test_reports_orphan_relationship_source_and_missing_target() -> None:
    pptx = _package(
        {
            "ppt/ghost/_rels/missing.xml.rels": (
                f'<Relationships xmlns="{_PKG_REL}">'
                f'<Relationship Id="rId1" Type="{_REL}/image" Target="asset.png"/>'
                "</Relationships>"
            )
        }
    )

    errors = validate_opc_package(pptx)

    assert (
        "ppt/ghost/_rels/missing.xml.rels: relationship source part is missing: "
        "ppt/ghost/missing.xml"
    ) in errors
    assert ("ppt/ghost/_rels/missing.xml.rels: rId1 targets missing ppt/ghost/asset.png") in errors


def test_reports_duplicate_relationship_ids_and_dangling_xml_reference() -> None:
    pptx = _package(
        {
            "ppt/item.xml": (f'<item xmlns:r="{_REL}" r:id="rId2"/>'),
            "ppt/_rels/item.xml.rels": (
                f'<Relationships xmlns="{_PKG_REL}">'
                '<Relationship Id="rId1" Type="urn:first" TargetMode="External" '
                'Target="https://example.com/one"/>'
                '<Relationship Id="rId1" Type="urn:second" TargetMode="External" '
                'Target="https://example.com/two"/>'
                "</Relationships>"
            ),
        }
    )

    errors = validate_opc_package(pptx)

    assert "ppt/_rels/item.xml.rels: duplicate relationship ID 'rId1'" in errors
    assert "ppt/item.xml: id references missing relationship 'rId2'" in errors


def test_reports_malformed_xml() -> None:
    errors = validate_opc_package(_package({"ppt/broken.xml": b"<broken>"}))

    assert any(error.startswith("ppt/broken.xml: malformed XML:") for error in errors)


def test_pptx_validation_reports_missing_slide_target() -> None:
    parts = _parts(build_pptx([_slide()], faces=[]))
    del parts["ppt/slides/slide1.xml"]

    errors = validate_pptx_package(write_package(parts))

    assert any("rId2 targets missing ppt/slides/slide1.xml" in error for error in errors)


def test_pptx_validation_reports_missing_shape_tree() -> None:
    parts = _parts(build_pptx([_slide()], faces=[]))
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        b"p:spTree", b"p:notSpTree"
    )

    errors = validate_pptx_package(write_package(parts))

    assert "ppt/slides/slide1.xml: missing p:cSld/p:spTree" in errors


def test_pptx_validation_reports_wrong_core_root_namespace() -> None:
    parts = _parts(build_pptx([_slide()], faces=[]))
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        b"http://schemas.openxmlformats.org/presentationml/2006/main",
        b"urn:not-presentationml",
    )

    errors = validate_pptx_package(write_package(parts))

    assert any("ppt/slides/slide1.xml: root" in error for error in errors)


def test_pptx_validation_reports_invalid_slide_ids() -> None:
    parts = _parts(build_pptx([_slide(), _slide()], faces=[]))
    parts["ppt/presentation.xml"] = parts["ppt/presentation.xml"].replace(
        b'<p:sldId id="257"', b'<p:sldId id="0"', 1
    )

    errors = validate_pptx_package(write_package(parts))

    assert "ppt/presentation.xml: p:sldId id values must be positive integers" in errors


def test_pptx_validation_reports_duplicate_nonvisual_shape_ids() -> None:
    shapes = (
        ShapeNode(box=Box(x=0, y=0, width=100, height=100)),
        ShapeNode(box=Box(x=100, y=0, width=100, height=100)),
    )
    parts = _parts(build_pptx([_slide(*shapes)], faces=[]))
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(b'id="3"', b'id="2"', 1)

    errors = validate_pptx_package(write_package(parts))

    assert "ppt/slides/slide1.xml: duplicate p:cNvPr id '2'" in errors


def test_pptx_validation_reports_missing_picture_content_type_and_relationship() -> None:
    shape = ShapeNode(
        box=Box(x=0, y=0, width=914_400, height=914_400),
        fill=_picture(),
    )
    parts = _parts(build_pptx([_slide(shape)], faces=[]))
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b'<Default Extension="png" ContentType="image/png"/>', b""
    )
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        b'r:embed="rId2"', b'r:embed="rId99"'
    )

    errors = validate_pptx_package(write_package(parts))

    assert "ppt/media/image1.png: no content type declared" in errors
    assert "ppt/slides/slide1.xml: embed references missing relationship 'rId99'" in errors


def test_build_boundary_rejects_validator_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_validation(_data: bytes) -> tuple[str, ...]:
        return ("synthetic package failure",)

    monkeypatch.setattr(
        "domoxml.slides.pptx.validate_pptx_package",
        fail_validation,
    )

    with pytest.raises(
        ValueError,
        match=r"(?s)generated invalid PPTX package.*synthetic package failure",
    ):
        build_pptx([_slide()], faces=[])
