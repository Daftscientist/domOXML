# pyright: reportPrivateUsage=false
"""Unit tests for capability-runner orchestration helpers."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from domoxml.core.capabilities import load_capabilities
from domoxml.types import (
    CoverageReport,
    HtmlAsset,
    HtmlPresentation,
    HtmlSlide,
    RenderResult,
)
from scripts.capability_check import (
    _inline_assets,
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

    inlined = _inline_assets(html)

    assert inlined.assets == ()
    assert "../assets/" not in inlined.css
    assert "../assets/" not in inlined.slides[0].html
    assert "data:font/ttf;base64," in inlined.css
    assert "data:image/png;base64," in inlined.slides[0].html


def test_reverse_visual_gate_checks_global_and_regional_similarity(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixture = next(item for item in load_capabilities(root) if item.id == "text-rich-runs")

    assert (
        _validate_reverse_visual(
            fixture, _render_result(_png("white")), _render_result(_png("white"))
        )
        == ()
    )

    errors = _validate_reverse_visual(
        fixture,
        _render_result(_png("black")),
        _render_result(_png("white")),
        tmp_path,
    )
    assert len(errors) == 2
    assert "global similarity" in errors[0]
    assert "regional similarity" in errors[1]
    assert (tmp_path / "text-rich-runs-slide0-source.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-reverse.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-reverse-diff.png").is_file()


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
