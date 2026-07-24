"""Capability fixture loading and structural validation without a browser."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from domoxml.core.capabilities import (
    CapabilityDirection,
    CapabilityExpected,
    CapabilityFixture,
    CapabilityRoundtripExpected,
    load_capabilities,
    validate_capability,
    validate_reverse_capability,
    validate_roundtrip_capability,
)
from domoxml.core.ir.model import (
    Box,
    ShapeNode,
    SlideIR,
    TextBody,
    TextParagraph,
    TextRun,
)
from domoxml.slides import build_pptx
from domoxml.types import (
    CoverageItem,
    CoverageReport,
    Editability,
    HtmlPresentation,
    HtmlSlide,
    RenderResult,
    Representation,
    SourceRetention,
)


def _fixture(fixture_id: str) -> CapabilityFixture:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    [fixture] = [item for item in load_capabilities(root) if item.id == fixture_id]
    return fixture


def test_convergence_thresholds_require_multiple_roundtrip_cycles() -> None:
    with pytest.raises(
        ValidationError, match="round-trip convergence thresholds require at least two cycles"
    ):
        CapabilityRoundtripExpected(min_convergence_similarity=0.99)

    assert CapabilityRoundtripExpected(cycles=1).cycles == 1


def test_loads_seed_capability_fixture() -> None:
    fixture = _fixture("text-rich-runs")
    assert fixture.id == "text-rich-runs"
    assert "Coffee that tastes like" in fixture.html
    assert fixture.expected.xml[0].min_count == 3
    assert fixture.reverse.html_contains


def test_every_bidirectional_fixture_declares_reverse_assertions() -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixtures = load_capabilities(root)

    both = [fixture for fixture in fixtures if fixture.direction is CapabilityDirection.BOTH]
    assert both
    assert all(fixture.reverse.html_contains for fixture in both)
    assert all(fixture.roundtrip.cycles >= 2 for fixture in both)


def test_every_visual_capability_gate_includes_structural_similarity() -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixtures = load_capabilities(root)

    assert all(
        fixture.visual.source_to_pptx_min_structural_similarity is not None
        for fixture in fixtures
        if fixture.direction in (CapabilityDirection.FORWARD, CapabilityDirection.BOTH)
    )
    assert all(
        fixture.visual.pptx_to_html_min_structural_similarity is not None
        or fixture.visual_exclusion is not None
        for fixture in fixtures
        if fixture.direction in (CapabilityDirection.REVERSE, CapabilityDirection.BOTH)
    )


def test_every_forward_fixture_caps_lossy_representations() -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixtures = load_capabilities(root)
    lossy = {
        Representation.APPROXIMATED,
        Representation.HYBRID,
        Representation.LAYERED,
        Representation.ELEMENT_LAYER,
        Representation.RASTERIZED,
        Representation.FAILED,
    }

    assert all(
        lossy <= fixture.expected.max_representation.keys()
        for fixture in fixtures
        if fixture.direction in (CapabilityDirection.FORWARD, CapabilityDirection.BOTH)
    )


def test_every_capability_declares_complete_quality_and_convergence_bounds() -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixtures = load_capabilities(root)

    for fixture in fixtures:
        if fixture.direction in (CapabilityDirection.FORWARD, CapabilityDirection.BOTH):
            assert set(fixture.expected.max_editability) == set(Editability)
            assert set(fixture.expected.max_source_retention) == set(SourceRetention)
            assert fixture.expected.min_output_count is not None
            assert fixture.expected.max_output_count is not None
            assert fixture.expected.min_raster_area_emu2 is not None
            assert fixture.expected.max_raster_area_emu2 is not None

        if fixture.direction in (CapabilityDirection.REVERSE, CapabilityDirection.BOTH):
            assert set(fixture.reverse.max_representation) == set(Representation)
            assert set(fixture.reverse.max_editability) == set(Editability)
            assert set(fixture.reverse.max_source_retention) == set(SourceRetention)
            assert fixture.reverse.min_output_count is not None
            assert fixture.reverse.max_output_count is not None
            assert fixture.reverse.min_raster_area_emu2 is not None
            assert fixture.reverse.max_raster_area_emu2 is not None
            assert fixture.roundtrip.cycles >= 2
            assert set(fixture.roundtrip.max_representation) == set(Representation)
            assert set(fixture.roundtrip.max_editability) == set(Editability)
            assert set(fixture.roundtrip.max_source_retention) == set(SourceRetention)
            assert fixture.roundtrip.min_output_count is not None
            assert fixture.roundtrip.max_output_count is not None
            assert fixture.roundtrip.min_raster_area_emu2 is not None
            assert fixture.roundtrip.max_raster_area_emu2 is not None
            assert fixture.roundtrip.min_convergence_similarity is not None
            assert fixture.roundtrip.min_convergence_regional_similarity is not None
            assert fixture.roundtrip.min_convergence_structural_similarity is not None


def test_validates_native_coverage_and_ooxml_xpath() -> None:
    fixture = _fixture("text-rich-runs")
    fixture = fixture.model_copy(
        update={
            "expected": CapabilityExpected(
                min_representation={Representation.NATIVE: 3},
                xml=fixture.expected.xml,
            ),
            "roundtrip": CapabilityRoundtripExpected(),
        }
    )
    body = TextBody(
        paragraphs=(
            TextParagraph(
                runs=tuple(
                    TextRun(text=text, font_family="sans-serif", size_pt=24)
                    for text in ("Coffee that tastes like ", "calm", ".")
                )
            ),
        )
    )
    pptx = build_pptx(
        [
            SlideIR(
                width=12_192_000,
                height=6_858_000,
                shapes=(ShapeNode(box=Box(x=0, y=0, width=1_000, height=1_000), text=body),),
            )
        ],
        faces=[],
    )
    result = RenderResult(
        pptx=pptx,
        pngs=(),
        html=None,
        coverage=CoverageReport(
            items=tuple(
                CoverageItem(
                    element=f"node-{index}",
                    representation=Representation.NATIVE,
                    editability=Editability.SEMANTIC,
                )
                for index in range(3)
            )
        ),
        warnings=(),
    )
    assert validate_capability(fixture, result) == ()

    below_source_minimum = result.model_copy(
        update={"coverage": CoverageReport(items=result.coverage.items[:1])}
    )
    assert validate_capability(fixture, below_source_minimum) == (
        "native count 1 < expected minimum 3",
    )
    assert validate_roundtrip_capability(fixture, below_source_minimum) == ()


def test_roundtrip_validation_still_enforces_loss_ceiling() -> None:
    fixture = _fixture("text-rich-runs")
    fixture = fixture.model_copy(
        update={
            "expected": fixture.expected.model_copy(update={"xml": ()}),
            "roundtrip": CapabilityRoundtripExpected(
                max_representation={Representation.APPROXIMATED: 0}
            ),
        }
    )
    result = RenderResult(
        pptx=None,
        pngs=(),
        html=None,
        coverage=CoverageReport(
            items=(
                CoverageItem(
                    element="approximation",
                    representation=Representation.APPROXIMATED,
                    editability=Editability.SEMANTIC,
                    reason="test approximation",
                ),
            )
        ),
        warnings=(),
    )

    assert validate_roundtrip_capability(fixture, result) == (
        "approximated count 1 > expected maximum 0",
    )


def test_required_parts_are_validated_without_xpath_expectations() -> None:
    fixture = CapabilityFixture(
        id="required-part-only",
        direction=CapabilityDirection.FORWARD,
        html="<p>x</p>",
        expected=CapabilityExpected(required_parts=("ppt/missing.xml",)),
    )
    result = RenderResult(
        pptx=build_pptx([SlideIR(width=12_192_000, height=6_858_000)], faces=[]),
        pngs=(),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )

    assert validate_capability(fixture, result) == ("missing package part ppt/missing.xml",)


def test_forward_and_roundtrip_capabilities_reject_invalid_packages() -> None:
    fixture = CapabilityFixture(
        id="package-validation",
        direction=CapabilityDirection.FORWARD,
        html="<p>x</p>",
        expected=CapabilityExpected(required_parts=("ppt/presentation.xml",)),
    )
    result = RenderResult(
        pptx=b"not a package",
        pngs=(),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )

    expected = ("package: invalid OPC package: expected a ZIP archive",)
    assert validate_capability(fixture, result) == expected
    assert validate_roundtrip_capability(fixture, result) == expected


def test_validates_reverse_html_warnings_and_preservation() -> None:
    fixture = _fixture("hyperlink")
    html = HtmlPresentation(
        slides=(
            HtmlSlide(
                html='<a href="https://example.com" style="text-decoration-line:underline">x</a>',
                width_px=1280,
                height_px=720,
            ),
        ),
        css="",
        coverage=CoverageReport(
            items=tuple(
                CoverageItem(
                    element=f"native-{index}",
                    representation=Representation.NATIVE,
                    editability=Editability.SEMANTIC,
                )
                for index in range(2)
            )
        ),
    )

    assert validate_reverse_capability(fixture, html) == ()

    coverage_regression = html.model_copy(
        update={"coverage": CoverageReport(items=html.coverage.items[:1])}
    )
    assert validate_reverse_capability(fixture, coverage_regression)[:4] == (
        "native count 1 < expected minimum 2",
        "semantic editability count 1 < expected minimum 2",
        "not_required source retention count 1 < expected minimum 2",
        "output count 1 < expected minimum 2",
    )

    missing = html.model_copy(
        update={
            "slides": (HtmlSlide(html="<p>x</p>", width_px=1280, height_px=720),),
        }
    )
    errors = validate_reverse_capability(fixture, missing)
    assert errors == (
        "reverse HTML missing '<a href=\"https://example.com\"'",
        "reverse HTML missing 'text-decoration-line:underline'",
    )


def test_loads_reverse_only_pptx_source(tmp_path: Path) -> None:
    case = tmp_path / "reverse"
    case.mkdir()
    (case / "source.pptx").write_bytes(b"pptx")
    (case / "slide.png").write_bytes(b"png")
    (case / "capability.toml").write_text(
        'id = "reverse"\ndirection = "reverse"\npptx_file = "source.pptx"\n'
        'reverse_render_files = ["slide.png"]\n'
        'visual_exclusion = "structural-only fixture"\n'
    )

    [fixture] = load_capabilities(tmp_path)
    assert fixture.html == ""
    assert fixture.pptx == b"pptx"
    assert fixture.reverse_render_pngs == (b"png",)
