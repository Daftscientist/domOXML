#!/usr/bin/env python
"""Render isolated HTML capability fixtures and assert editable OOXML structure."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from domoxml.core.capabilities import (
    CapabilityDirection,
    CapabilityFixture,
    load_capabilities,
    validate_capability,
    validate_reverse_capability,
    validate_roundtrip_capability,
)
from domoxml.core.fidelity import (
    align_candidate_png,
    compare,
    has_libreoffice,
    has_poppler,
    render_pptx_to_pngs,
)
from domoxml.core.roundtrip import render_html_roundtrip
from domoxml.presentation import Presentation, Slide
from domoxml.types import HtmlPresentation, OutputFormat, RenderResult

_TRANSIENT_RENDER_ERRORS = (
    "Unable to capture screenshot",
    "Target page, context or browser has been closed",
)


def _is_transient_render_error(error: Exception) -> bool:
    message = str(error)
    return any(token in message for token in _TRANSIENT_RENDER_ERRORS)


def _render_forward(fixture: CapabilityFixture) -> RenderResult:
    return (
        Presentation().add(Slide(html=fixture.html)).render({OutputFormat.PNG, OutputFormat.PPTX})
    )


def _render_reverse_html(html: HtmlPresentation) -> RenderResult:
    return render_html_roundtrip(html)


def _validate_forward_visual(
    fixture: CapabilityFixture,
    source: RenderResult,
    candidates: list[bytes],
    out_dir: Path | None = None,
    *,
    report_scores: bool = False,
) -> tuple[str, ...]:
    global_floor = fixture.visual.source_to_pptx_min_similarity
    regional_floor = fixture.visual.source_to_pptx_min_regional_similarity
    structural_floor = fixture.visual.source_to_pptx_min_structural_similarity
    if global_floor is None and regional_floor is None and structural_floor is None:
        return ()
    if len(source.pngs) != len(candidates):
        return (f"forward visual page count {len(candidates)} != source {len(source.pngs)}",)

    errors: list[str] = []
    for index, (reference, candidate) in enumerate(zip(source.pngs, candidates, strict=True)):
        report = compare(reference, candidate, heatmap=out_dir is not None)
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{fixture.id}-slide{index}"
            (out_dir / f"{stem}-source.png").write_bytes(reference)
            (out_dir / f"{stem}-libreoffice.png").write_bytes(
                align_candidate_png(reference, candidate)
            )
            if report.diff_png is not None:
                (out_dir / f"{stem}-libreoffice-diff.png").write_bytes(report.diff_png)
        if global_floor is not None and report.similarity < global_floor:
            errors.append(
                f"forward slide {index} global similarity {report.similarity:.3f} "
                f"< expected {global_floor:.3f}"
            )
        if regional_floor is not None and report.regional_similarity < regional_floor:
            errors.append(
                f"forward slide {index} regional similarity {report.regional_similarity:.3f} "
                f"< expected {regional_floor:.3f}"
            )
        if structural_floor is not None and report.structural_similarity < structural_floor:
            errors.append(
                f"forward slide {index} structural similarity "
                f"{report.structural_similarity:.3f} < expected {structural_floor:.3f}"
            )
        if report_scores:
            print(
                f"     libreoffice slide{index}: global {report.similarity:.3f}, "
                f"regional {report.regional_similarity:.3f}, "
                f"structural {report.structural_similarity:.3f}"
            )
    return tuple(errors)


def _validate_reverse_visual(
    fixture: CapabilityFixture,
    source_pngs: tuple[bytes, ...],
    reverse: RenderResult,
    out_dir: Path | None = None,
    *,
    report_scores: bool = False,
) -> tuple[str, ...]:
    global_floor = fixture.visual.pptx_to_html_min_similarity
    regional_floor = fixture.visual.pptx_to_html_min_regional_similarity
    structural_floor = fixture.visual.pptx_to_html_min_structural_similarity
    if global_floor is None and regional_floor is None and structural_floor is None:
        return ()
    if len(source_pngs) != len(reverse.pngs):
        return (f"reverse visual page count {len(reverse.pngs)} != source {len(source_pngs)}",)

    errors: list[str] = []
    for index, (reference, candidate) in enumerate(zip(source_pngs, reverse.pngs, strict=True)):
        report = compare(reference, candidate, heatmap=out_dir is not None)
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{fixture.id}-slide{index}"
            (out_dir / f"{stem}-source.png").write_bytes(reference)
            (out_dir / f"{stem}-reverse.png").write_bytes(align_candidate_png(reference, candidate))
            if report.diff_png is not None:
                (out_dir / f"{stem}-reverse-diff.png").write_bytes(report.diff_png)
        if global_floor is not None and report.similarity < global_floor:
            errors.append(
                f"reverse slide {index} global similarity {report.similarity:.3f} "
                f"< expected {global_floor:.3f}"
            )
        if regional_floor is not None and report.regional_similarity < regional_floor:
            errors.append(
                f"reverse slide {index} regional similarity {report.regional_similarity:.3f} "
                f"< expected {regional_floor:.3f}"
            )
        if structural_floor is not None and report.structural_similarity < structural_floor:
            errors.append(
                f"reverse slide {index} structural similarity "
                f"{report.structural_similarity:.3f} < expected {structural_floor:.3f}"
            )
        if report_scores:
            print(
                f"     reverse slide{index}: global {report.similarity:.3f}, "
                f"regional {report.regional_similarity:.3f}, "
                f"structural {report.structural_similarity:.3f}"
            )
    return tuple(errors)


def _validate_fixture(
    fixture: CapabilityFixture,
    out_dir: Path | None = None,
    *,
    forward_visual_available: bool,
    report_scores: bool = False,
) -> tuple[str, ...]:
    errors: list[str] = []
    source_pptx = fixture.pptx
    forward: RenderResult | None = None

    if fixture.direction in (CapabilityDirection.FORWARD, CapabilityDirection.BOTH):
        forward = _render_forward(fixture)
        errors.extend(f"forward: {error}" for error in validate_capability(fixture, forward))
        source_pptx = forward.pptx
        has_forward_threshold = (
            fixture.visual.source_to_pptx_min_similarity is not None
            or fixture.visual.source_to_pptx_min_regional_similarity is not None
            or fixture.visual.source_to_pptx_min_structural_similarity is not None
        )
        if has_forward_threshold and forward_visual_available:
            if source_pptx is None:
                errors.append("forward visual: fixture produced no PPTX source")
            else:
                candidates = render_pptx_to_pngs(source_pptx)
                errors.extend(
                    f"visual: {error}"
                    for error in _validate_forward_visual(
                        fixture,
                        forward,
                        candidates,
                        out_dir,
                        report_scores=report_scores,
                    )
                )

    if fixture.direction in (CapabilityDirection.REVERSE, CapabilityDirection.BOTH):
        if source_pptx is None:
            errors.append("reverse: fixture produced no PPTX source")
            return tuple(errors)
        reverse = Presentation.from_pptx(source_pptx)
        errors.extend(
            f"reverse: {error}" for error in validate_reverse_capability(fixture, reverse)
        )
        if fixture.reverse.roundtrip:
            roundtrip = _render_reverse_html(reverse)
            errors.extend(
                f"roundtrip: {error}" for error in validate_roundtrip_capability(fixture, roundtrip)
            )
            has_reverse_threshold = (
                fixture.visual.pptx_to_html_min_similarity is not None
                or fixture.visual.pptx_to_html_min_regional_similarity is not None
                or fixture.visual.pptx_to_html_min_structural_similarity is not None
            )
            source_pngs: tuple[bytes, ...] = forward.pngs if forward is not None else ()
            if not source_pngs and has_reverse_threshold and forward_visual_available:
                source_pngs = tuple(render_pptx_to_pngs(source_pptx))
            if source_pngs:
                errors.extend(
                    f"visual: {error}"
                    for error in _validate_reverse_visual(
                        fixture,
                        source_pngs,
                        roundtrip,
                        out_dir,
                        report_scores=report_scores,
                    )
                )

    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("capabilities/pptx"))
    parser.add_argument("--out", type=Path, default=Path("out/capabilities"))
    parser.add_argument(
        "--require-backend",
        action="store_true",
        help="fail when LibreOffice/poppler is unavailable for forward visual checks",
    )
    args = parser.parse_args(argv)

    fixtures = load_capabilities(args.fixtures)
    if not fixtures:
        print(f"no capability fixtures found under {args.fixtures}", file=sys.stderr)
        return 1

    forward_visual_available = has_libreoffice() and has_poppler()
    if not forward_visual_available:
        message = "LibreOffice/poppler unavailable; forward capability visuals skipped"
        if args.require_backend:
            print(message, file=sys.stderr)
            return 2
        print(message, file=sys.stderr)

    failures = 0
    for fixture in fixtures:
        errors: tuple[str, ...] = ()
        for attempt in range(2):
            try:
                errors = _validate_fixture(
                    fixture,
                    args.out,
                    forward_visual_available=forward_visual_available,
                    report_scores=True,
                )
                break
            except Exception as exc:  # CLI boundary: retry transport errors; report and continue.
                if attempt == 0 and _is_transient_render_error(exc):
                    print(f"retry {fixture.id}: transient browser capture failure", file=sys.stderr)
                    continue
                errors = (f"raised {type(exc).__name__}: {exc}",)
                break
        if errors:
            failures += 1
            print(f"FAIL {fixture.id}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"ok   {fixture.id} ({fixture.direction})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
