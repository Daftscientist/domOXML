"""Capability fixture loading and structural validation without a browser."""

from __future__ import annotations

from pathlib import Path

from domoxml.core.capabilities import (
    CapabilityFixture,
    load_capabilities,
    validate_capability,
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
from domoxml.types import CoverageItem, CoverageReport, Disposition, RenderResult


def _fixture(fixture_id: str) -> CapabilityFixture:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    [fixture] = [item for item in load_capabilities(root) if item.id == fixture_id]
    return fixture


def test_loads_seed_capability_fixture() -> None:
    fixture = _fixture("text-rich-runs")
    assert fixture.id == "text-rich-runs"
    assert "Coffee that tastes like" in fixture.html
    assert fixture.expected.xml[0].min_count == 3


def test_validates_native_coverage_and_ooxml_xpath() -> None:
    fixture = _fixture("text-rich-runs")
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
                CoverageItem(element=f"node-{index}", disposition=Disposition.NATIVE)
                for index in range(3)
            )
        ),
        warnings=(),
    )
    assert validate_capability(fixture, result) == ()
