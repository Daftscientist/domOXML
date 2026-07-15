"""Capability fixture loading and structural validation without a browser."""

from __future__ import annotations

from pathlib import Path

from domoxml.core.capabilities import (
    CapabilityDirection,
    CapabilityFixture,
    load_capabilities,
    validate_capability,
    validate_reverse_capability,
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
    Disposition,
    HtmlPresentation,
    HtmlSlide,
    RenderResult,
)


def _fixture(fixture_id: str) -> CapabilityFixture:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    [fixture] = [item for item in load_capabilities(root) if item.id == fixture_id]
    return fixture


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
    assert all(fixture.reverse.roundtrip for fixture in both)


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
    )

    assert validate_reverse_capability(fixture, html) == ()

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
    (case / "capability.toml").write_text(
        'id = "reverse"\ndirection = "reverse"\npptx_file = "source.pptx"\n'
    )

    [fixture] = load_capabilities(tmp_path)
    assert fixture.html == ""
    assert fixture.pptx == b"pptx"
