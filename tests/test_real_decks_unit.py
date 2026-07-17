"""Contracts for the pinned representative PPTX corpus."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from domoxml.core.ir.model import PreservedNode, TableNode
from domoxml.core.opc import OpcPackage
from domoxml.core.real_decks import (
    DeckPackageExpected,
    RealDeckCase,
    load_real_decks,
    validate_opc_package,
    validate_real_deck,
    validate_real_deck_roundtrip,
)
from domoxml.presentation import Presentation
from domoxml.slides import build_pptx, read_pptx_result
from domoxml.types import Editability, Representation, SourceRetention


def _fallback_pngs(count: int) -> tuple[bytes, ...]:
    image = BytesIO()
    Image.new("RGB", (1280, 720), "white").save(image, "PNG")
    return (image.getvalue(),) * count


def test_repository_real_decks_have_valid_pins_and_relationships() -> None:
    cases = load_real_decks(Path("real-decks/pptx"))

    assert {case.id for case in cases} == {
        "external-chart-preservation",
        "external-embedded-font",
        "external-image-crop",
        "external-table-style",
    }
    for case in cases:
        assert hashlib.sha256(case.pptx).hexdigest() == case.provenance.sha256
        assert validate_opc_package(case.pptx) == ()
        assert set(case.reverse.max_representation) == set(Representation)
        assert set(case.reverse.max_editability) == set(Editability)
        assert set(case.reverse.max_source_retention) == set(SourceRetention)
        assert case.reverse.min_output_count is not None
        assert case.reverse.max_output_count is not None
        assert case.reverse.min_raster_area_emu2 is not None
        assert case.reverse.max_raster_area_emu2 is not None


def test_repository_real_decks_match_reverse_contracts() -> None:
    for case in load_real_decks(Path("real-decks/pptx")):
        html = Presentation.from_pptx(case.pptx, fallback_pngs=_fallback_pngs(case.package.slides))
        assert validate_real_deck(case, html) == ()


def test_external_chart_payload_is_owned_and_re_emitted_with_dependencies() -> None:
    case = next(
        case
        for case in load_real_decks(Path("real-decks/pptx"))
        if case.id == "external-chart-preservation"
    )
    result = read_pptx_result(case.pptx)
    [chart] = [
        node
        for slide in result.slides
        for node in slide.contents
        if isinstance(node, PreservedNode)
    ]

    assert chart.node_id == "pptx-5"
    assert {part.name for part in chart.payload.parts} == {
        "ppt/charts/chart1.xml",
        "ppt/charts/style1.xml",
        "ppt/charts/colors1.xml",
        "ppt/embeddings/Microsoft_Excel_Worksheet.xlsx",
    }
    assert chart.payload.ambient_theme is not None
    assert b'val="E1251B"' in chart.payload.ambient_theme.data
    [fragment] = result.preserved
    assert fragment.owner_node_id == chart.node_id

    rebuilt = build_pptx(list(result.slides), faces=[])
    package = OpcPackage.from_bytes(rebuilt)
    assert validate_real_deck_roundtrip(case, rebuilt) == ()
    assert b"graphicFrame" in package.read("ppt/slides/slide2.xml")


def test_external_table_style_lowers_to_explicit_ir_provenance() -> None:
    case = next(
        case
        for case in load_real_decks(Path("real-decks/pptx"))
        if case.id == "external-table-style"
    )

    result = read_pptx_result(case.pptx)
    [table] = [
        node for slide in result.slides for node in slide.contents if isinstance(node, TableNode)
    ]

    assert table.style_id == "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
    assert table.first_row and table.band_row and table.header_bold_inherited
    assert not any((table.last_row, table.first_col, table.last_col, table.band_col))
    run = table.rows[0].cells[0].text.paragraphs[0].runs[0]  # type: ignore[union-attr]
    assert run.bold and run.bold_inherited


def test_real_deck_roundtrip_rejects_dropped_slides() -> None:
    case = next(
        case for case in load_real_decks(Path("real-decks/pptx")) if case.package.slides == 1
    )
    expected_two_slides = case.model_copy(update={"package": DeckPackageExpected(slides=2)})

    errors = validate_real_deck_roundtrip(expected_two_slides, case.pptx)

    assert "roundtrip slide count 1 != expected 2" in errors


def test_real_deck_validators_return_invalid_zip_diagnostics() -> None:
    case = load_real_decks(Path("real-decks/pptx"))[0]
    invalid = b"not a package"
    invalid_case = case.model_copy(
        update={
            "pptx": invalid,
            "provenance": case.provenance.model_copy(
                update={"sha256": hashlib.sha256(invalid).hexdigest()}
            ),
        }
    )
    valid_html = Presentation.from_pptx(case.pptx)

    expected = "invalid OPC package: expected a ZIP archive"
    assert expected in validate_real_deck(invalid_case, valid_html)
    assert validate_real_deck_roundtrip(case, invalid) == (expected,)


def test_real_deck_requires_visual_gate_or_exclusion() -> None:
    raw = {
        "id": "missing-visual-contract",
        "pptx": b"pptx",
        "provenance": {
            "source_url": "https://example.test/deck.pptx",
            "source_revision": "abc",
            "license": "MIT",
            "sha256": "0" * 64,
        },
        "package": {"slides": 1},
        "reverse": {},
    }

    with pytest.raises(ValidationError, match="visual floors or one visual_exclusion"):
        RealDeckCase.model_validate(raw)


def test_real_deck_rejects_out_of_range_visual_slide() -> None:
    raw = {
        "id": "bad-slide",
        "pptx": b"pptx",
        "provenance": {
            "source_url": "https://example.test/deck.pptx",
            "source_revision": "abc",
            "license": "MIT",
            "sha256": "0" * 64,
        },
        "package": {"slides": 1},
        "reverse": {},
        "visual": [
            {
                "slide": 1,
                "min_similarity": 0.9,
                "min_regional_similarity": 0.8,
                "min_focused_similarity": 0.7,
            }
        ],
    }

    with pytest.raises(ValidationError, match="visual slide indices out of range"):
        RealDeckCase.model_validate(raw)
