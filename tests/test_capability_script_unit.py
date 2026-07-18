# pyright: reportPrivateUsage=false
"""Unit tests for capability-runner orchestration helpers."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw
from pytest import MonkeyPatch

from domoxml.core.capabilities import (
    CapabilityDirection,
    CapabilityFixture,
    CapabilityReverseExpected,
    CapabilityRoundtripExpected,
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
    _validate_convergence_visual,
    _validate_fixture,
    _validate_forward_visual,
    _validate_reverse_visual,
)


def _png(color: str, size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_with_foreground(*, include_foreground: bool) -> bytes:
    image = Image.new("RGB", (160, 90), "white")
    if include_foreground:
        ImageDraw.Draw(image).rectangle((64, 30, 95, 59), fill=(20, 70, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
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

    candidate = _png("white", (32, 32))
    errors = _validate_reverse_visual(
        fixture,
        (_png("black"),),
        _render_result(candidate),
        tmp_path,
    )
    assert len(errors) == 2
    assert "global similarity" in errors[0]
    assert "regional similarity" in errors[1]
    assert (tmp_path / "text-rich-runs-slide0-source.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-reverse-raw.png").read_bytes() == candidate
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
        cls: type[capability_check.Presentation],
        source: bytes | Path,
        *,
        fallback_pngs: tuple[bytes, ...] | None = None,
    ) -> HtmlPresentation:
        assert cls is capability_check.Presentation
        assert source == source_pptx
        assert fallback_pngs == (_png("black"),)
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


def test_reverse_only_fixture_prefers_authoritative_pinned_render_with_backend(
    monkeypatch: MonkeyPatch,
) -> None:
    import scripts.capability_check as capability_check

    pinned = _png("black")
    fixture = CapabilityFixture(
        id="pinned-reverse",
        direction=CapabilityDirection.REVERSE,
        pptx=b"source",
        reverse_render_pngs=(pinned,),
        visual=CapabilityVisual(pptx_to_html_min_similarity=0.99),
    )
    reverse = HtmlPresentation(
        slides=(HtmlSlide(html="<div>reverse</div>", width_px=64, height_px=64),),
        css="",
    )

    def read_source(
        cls: type[capability_check.Presentation],
        source: bytes | Path,
        *,
        fallback_pngs: tuple[bytes, ...] | None = None,
    ) -> HtmlPresentation:
        assert cls is capability_check.Presentation
        assert source == b"source"
        assert fallback_pngs == (pinned,)
        return reverse

    monkeypatch.setattr(
        capability_check.Presentation,
        "from_pptx",
        classmethod(read_source),
    )

    def render_reverse(html: HtmlPresentation) -> RenderResult:
        assert html is reverse
        return _render_result(pinned)

    monkeypatch.setattr(
        capability_check,
        "_render_reverse_html",
        render_reverse,
    )

    def unexpected_render(_pptx: bytes) -> list[bytes]:
        raise AssertionError("pinned render must remain authoritative")

    monkeypatch.setattr(capability_check, "render_pptx_to_pngs", unexpected_render)

    assert _validate_fixture(fixture, forward_visual_available=True) == ()


def test_forward_visual_gate_checks_global_and_regional_similarity(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent / "capabilities" / "pptx"
    fixture = next(item for item in load_capabilities(root) if item.id == "text-rich-runs")

    assert _validate_forward_visual(fixture, _render_result(_png("white")), [_png("white")]) == ()

    candidate = _png("white", (32, 32))
    errors = _validate_forward_visual(
        fixture,
        _render_result(_png("black")),
        [candidate],
        tmp_path,
    )
    assert len(errors) == 2
    assert "global similarity" in errors[0]
    assert "regional similarity" in errors[1]
    assert (tmp_path / "text-rich-runs-slide0-source.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-libreoffice-raw.png").read_bytes() == candidate
    assert (tmp_path / "text-rich-runs-slide0-libreoffice.png").is_file()
    assert (tmp_path / "text-rich-runs-slide0-libreoffice-diff.png").is_file()


def test_structural_similarity_is_enforced_in_both_visual_directions() -> None:
    reference = _png_with_foreground(include_foreground=True)
    candidate = _png_with_foreground(include_foreground=False)
    fixture = CapabilityFixture(
        id="structural",
        direction=CapabilityDirection.BOTH,
        html="<div>fixture</div>",
        visual=CapabilityVisual(
            source_to_pptx_min_structural_similarity=0.99,
            pptx_to_html_min_structural_similarity=0.99,
        ),
    )

    forward_errors = _validate_forward_visual(fixture, _render_result(reference), [candidate])
    reverse_errors = _validate_reverse_visual(fixture, (reference,), _render_result(candidate))

    assert len(forward_errors) == 1
    assert "structural similarity" in forward_errors[0]
    assert len(reverse_errors) == 1
    assert "structural similarity" in reverse_errors[0]


def test_convergence_visual_gate_checks_every_quality_score(tmp_path: Path) -> None:
    previous = _render_result(_png_with_foreground(include_foreground=True))
    candidate = _render_result(_png_with_foreground(include_foreground=False))
    fixture = CapabilityFixture(
        id="convergence",
        direction=CapabilityDirection.REVERSE,
        pptx=b"pptx",
        visual_exclusion="unit fixture",
        roundtrip=CapabilityRoundtripExpected(
            cycles=2,
            min_convergence_similarity=0.99,
            min_convergence_regional_similarity=0.99,
            min_convergence_structural_similarity=0.99,
        ),
    )

    errors = _validate_convergence_visual(fixture, previous, candidate, 2, tmp_path)

    assert len(errors) == 3
    assert all("convergence" in error for error in errors)
    assert (tmp_path / "convergence-cycle2-slide0-previous.png").is_file()
    assert (tmp_path / "convergence-cycle2-slide0-current-raw.png").is_file()
    assert (tmp_path / "convergence-cycle2-slide0-current.png").is_file()
    assert (tmp_path / "convergence-cycle2-slide0-diff.png").is_file()


def test_convergence_visual_gate_can_scope_one_slide() -> None:
    fixture = CapabilityFixture(
        id="scoped-convergence",
        direction=CapabilityDirection.REVERSE,
        pptx=b"pptx",
        visual_exclusion="unit fixture",
        roundtrip=CapabilityRoundtripExpected(
            cycles=2,
            slide_indices=(1,),
            min_convergence_similarity=0.99,
        ),
    )
    previous = RenderResult(
        pptx=None,
        pngs=(_png("black"), _png("white")),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )
    candidate = RenderResult(
        pptx=None,
        pngs=(_png("white"), _png("white")),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )

    assert _validate_convergence_visual(fixture, previous, candidate, 2) == ()


def test_convergence_visual_gate_rejects_missing_renders() -> None:
    fixture = CapabilityFixture(
        id="missing-convergence-render",
        direction=CapabilityDirection.REVERSE,
        pptx=b"pptx",
        visual_exclusion="unit fixture",
        roundtrip=CapabilityRoundtripExpected(
            cycles=2,
            min_convergence_similarity=0.99,
        ),
    )
    empty = RenderResult(
        pptx=None,
        pngs=(),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )

    assert _validate_convergence_visual(fixture, empty, empty, 2) == (
        "convergence render produced no PNGs",
    )


def test_fixture_runner_reingests_every_configured_roundtrip_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    import scripts.capability_check as capability_check

    reverse = HtmlPresentation(
        slides=(HtmlSlide(html="<div>reverse</div>", width_px=64, height_px=64),),
        css="",
    )
    fixture = CapabilityFixture(
        id="cycles",
        direction=CapabilityDirection.REVERSE,
        pptx=b"source",
        visual_exclusion="unit fixture",
        roundtrip=CapabilityRoundtripExpected(cycles=2),
    )
    reads: list[bytes | Path] = []
    renders = 0

    def read_source(
        cls: type[capability_check.Presentation],
        source: bytes | Path,
        *,
        fallback_pngs: tuple[bytes, ...] | None = None,
    ) -> HtmlPresentation:
        assert cls is capability_check.Presentation
        reads.append(source)
        if source == b"cycle-1":
            assert fallback_pngs == (_png("white"),)
        return reverse

    def render_reverse(html: HtmlPresentation) -> RenderResult:
        nonlocal renders
        assert html is reverse
        renders += 1
        return RenderResult(
            pptx=f"cycle-{renders}".encode(),
            pngs=(_png("white"),),
            html=None,
            coverage=CoverageReport(items=()),
            warnings=(),
        )

    def validate_roundtrip(_fixture: CapabilityFixture, _result: RenderResult) -> tuple[str, ...]:
        return ()

    monkeypatch.setattr(capability_check.Presentation, "from_pptx", classmethod(read_source))
    monkeypatch.setattr(capability_check, "_render_reverse_html", render_reverse)
    monkeypatch.setattr(capability_check, "validate_roundtrip_capability", validate_roundtrip)

    assert _validate_fixture(fixture, forward_visual_available=False) == ()
    assert reads == [b"source", b"cycle-1"]
    assert renders == 2


def test_reverse_visual_gate_can_scope_one_slide() -> None:
    fixture = CapabilityFixture(
        id="scoped-reverse",
        direction=CapabilityDirection.REVERSE,
        pptx=b"pptx",
        visual=CapabilityVisual(
            pptx_to_html_min_similarity=0.99,
            pptx_to_html_slide_indices=(1,),
        ),
    )
    source = (_png("black"), _png("white"))
    candidate = RenderResult(
        pptx=None,
        pngs=(_png("white"), _png("white")),
        html=None,
        coverage=CoverageReport(items=()),
        warnings=(),
    )

    assert _validate_reverse_visual(fixture, source, candidate) == ()


def test_reverse_contract_requires_visual_assets() -> None:
    from domoxml.core.capabilities import validate_reverse_capability

    fixture = CapabilityFixture(
        id="assets",
        direction=CapabilityDirection.REVERSE,
        pptx=b"pptx",
        reverse=CapabilityReverseExpected(min_assets=1),
        visual_exclusion="unit fixture",
    )
    html = HtmlPresentation(
        slides=(HtmlSlide(html="<div/>", width_px=64, height_px=64),),
        css="",
    )

    assert validate_reverse_capability(fixture, html) == ("reverse assets 0 < expected 1",)
