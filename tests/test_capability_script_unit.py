# pyright: reportPrivateUsage=false
"""Unit tests for capability-runner orchestration helpers."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from pytest import MonkeyPatch

from domoxml.core.capabilities import (
    CapabilityDirection,
    CapabilityFixture,
    CapabilityVisual,
    load_capabilities,
)
from domoxml.core.roundtrip import inline_assets
from domoxml.types import (
    CoverageReport,
    HtmlAsset,
    HtmlPresentation,
    HtmlSlide,
    RenderResult,
)
from scripts.capability_check import (
    _is_transient_render_error,
    _validate_fixture,
    _validate_forward_visual,
    _validate_reverse_visual,
)


def _png(color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _render_result(png: bytes) -> RenderResult:
    return RenderResult(
        pptx=None,
        pngs=(png,),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )


def test_only_known_browser_transport_errors_are_retryable() -> None:
    assert _is_transient_render_error(
        RuntimeError("Page.captureScreenshot: Unable to capture screenshot")
    )
    assert _is_transient_render_error(
        RuntimeError("Target page, context or browser has been closed")
    )
    assert not _is_transient_render_error(RuntimeError("regional similarity below threshold"))


def test_inline_assets_rewrites_css_and_slide_references() -> None:
    html = HtmlPresentation(
        slides=(
            HtmlSlide(
                html='<img src="../assets/pixel.png">',
                width_px=1280,
                height_px=720,
            ),
        ),
        css="@font-face{src:url(../assets/font.ttf)}",
        assets=(
            HtmlAsset(path="assets/pixel.png", data=b"png"),
            HtmlAsset(path="assets/font.ttf", data=b"font"),
        ),
    )

    inlined = inline_assets(html)

    assert inlined.assets == ()
    assert "../assets/" not in inlined.css
    assert "../assets/" not in inlined.slides[0].html
    assert "data:font/ttf;base64," in inlined.css
    assert "data:image/png;base64," in inlined.slides[0].html


def test_reverse_visual_gate_checks_global_and_regional_similarity(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixture = next(item for item in load_capabilities(root) if item.id == "text-rich-runs")

    assert _validate_reverse_visual(fixture, (_png("white"),), _render_result(_png("white"))) == ()

    errors = _validate_reverse_visual(
        fixture,
        (_png("black"),),
        _render_result(_png("white")),
        tmp_path,
    )
    assert len(errors) == 2
    assert "global similarity" in errors[0]
    assert "regional similarity" in errors[1]
    assert (tmp_path / "text-rich-runs-slide0-source.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-reverse.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-reverse-diff.png").is_file()


def test_reverse_only_fixture_renders_source_pptx_for_visual_gate(
    monkeypatch: MonkeyPatch,
) -> None:
    import scripts.capability_check as capability_check

    source_pptx = b"reverse-only-source"
    fixture = CapabilityFixture(
        id="reverse-only",
        direction=CapabilityDirection.REVERSE,
        pptx=source_pptx,
        visual=CapabilityVisual(
            pptx_to_html_min_similarity=0.99,
            pptx_to_html_min_regional_similarity=0.99,
        ),
    )
    reverse = HtmlPresentation(
        slides=(HtmlSlide(html="<div>reverse</div>", width_px=64, height_px=64),),
        css="",
    )
    rendered_sources: list[bytes] = []

    def read_source(
        cls: type[capability_check.Presentation], source: bytes | Path
    ) -> HtmlPresentation:
        assert cls is capability_check.Presentation
        assert source == source_pptx
        return reverse

    def render_reverse(html: HtmlPresentation) -> RenderResult:
        assert html is reverse
        return _render_result(_png("white"))

    monkeypatch.setattr(
        capability_check.Presentation,
        "from_pptx",
        classmethod(read_source),
    )
    monkeypatch.setattr(
        capability_check,
        "_render_reverse_html",
        render_reverse,
    )

    def render_source(pptx: bytes) -> list[bytes]:
        rendered_sources.append(pptx)
        return [_png("black")]

    monkeypatch.setattr(capability_check, "render_pptx_to_pngs", render_source)

    errors = _validate_fixture(fixture, forward_visual_available=True)

    assert rendered_sources == [source_pptx]
    assert len([error for error in errors if error.startswith("visual:")]) == 2


def test_forward_visual_gate_checks_global_and_regional_similarity(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixture = next(item for item in load_capabilities(root) if item.id == "text-rich-runs")

    assert _validate_forward_visual(fixture, _render_result(_png("white")), [_png("white")]) == ()

    errors = _validate_forward_visual(
        fixture,
        _render_result(_png("black")),
        [_png("white")],
        tmp_path,
    )
    assert len(errors) == 2
    assert "global similarity" in errors[0]
    assert "regional similarity" in errors[1]
    assert (tmp_path / "text-rich-runs-slide0-source.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-libreoffice.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-libreoffice-diff.png").is_file()
