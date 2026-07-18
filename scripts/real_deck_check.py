#!/usr/bin/env python
"""Execute package, preservation, and renderer gates for pinned external PPTX decks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal, cast

from domoxml.core.fidelity import (
    align_candidate_png,
    compare,
    has_graph_auth,
    has_libreoffice,
    has_poppler,
    render_pptx_to_pngs,
    render_pptx_to_pngs_via_graph,
)
from domoxml.core.real_decks import (
    RealDeckCase,
    load_real_decks,
    validate_real_deck,
    validate_real_deck_roundtrip,
)
from domoxml.core.roundtrip import render_html_roundtrip
from domoxml.presentation import Presentation

type Backend = Literal["libreoffice", "graph"]


def _available(backend: Backend) -> bool:
    return has_poppler() and (has_libreoffice() if backend == "libreoffice" else has_graph_auth())


def _render(backend: Backend, pptx: bytes) -> list[bytes]:
    return (
        render_pptx_to_pngs(pptx)
        if backend == "libreoffice"
        else render_pptx_to_pngs_via_graph(pptx)
    )


def source_fallback_backend(case: RealDeckCase, active: list[Backend]) -> Backend:
    """Prefer the sole renderer named by a case's visual contract for source-owned layers."""
    scoped = {
        backend for expected in case.visual for backend in expected.backends if backend in active
    }
    if len(scoped) == 1:
        return cast(Backend, scoped.pop())
    return active[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("real-decks/pptx"))
    parser.add_argument(
        "--backend", choices=("libreoffice", "graph", "both"), default="libreoffice"
    )
    parser.add_argument("--out", type=Path, default=Path("out/real-decks"))
    parser.add_argument("--require-backend", action="store_true")
    args = parser.parse_args(argv)

    cases = load_real_decks(args.corpus)
    requested: list[Backend] = (
        ["libreoffice", "graph"] if args.backend == "both" else [cast(Backend, args.backend)]
    )
    active: list[Backend] = [backend for backend in requested if _available(backend)]
    missing: list[Backend] = [backend for backend in requested if backend not in active]
    if missing and args.require_backend:
        print(f"required real-deck backends unavailable: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not active:
        print("no real-deck renderer backend available", file=sys.stderr)
        return 0

    failures = 0
    for case in cases:
        references_by_backend = {backend: _render(backend, case.pptx) for backend in active}
        source_backend = source_fallback_backend(case, active)
        fallback_pngs = tuple(references_by_backend[source_backend])
        html = Presentation.from_pptx(case.pptx, fallback_pngs=fallback_pngs)
        errors = list(validate_real_deck(case, html))
        roundtrip = render_html_roundtrip(html)
        if roundtrip.pptx is None:
            errors.append("round trip produced no PPTX")
        else:
            errors.extend(
                f"roundtrip package: {error}"
                for error in validate_real_deck_roundtrip(case, roundtrip.pptx)
            )

        for backend in active:
            if not case.visual or roundtrip.pptx is None:
                continue
            expected_for_backend = [
                expected for expected in case.visual if backend in expected.backends
            ]
            if not expected_for_backend:
                continue
            references = references_by_backend[backend]
            candidates = _render(backend, roundtrip.pptx)
            for expected in expected_for_backend:
                if expected.slide >= len(references) or expected.slide >= len(candidates):
                    errors.append(f"{backend} slide {expected.slide}: render page missing")
                    continue
                reference = references[expected.slide]
                candidate = candidates[expected.slide]
                report = compare(reference, candidate, heatmap=True)
                target = args.out / case.id
                target.mkdir(parents=True, exist_ok=True)
                stem = f"slide{expected.slide}-{backend}"
                (target / f"{stem}-source.png").write_bytes(reference)
                (target / f"{stem}-roundtrip-raw.png").write_bytes(candidate)
                (target / f"{stem}-roundtrip.png").write_bytes(
                    align_candidate_png(reference, candidate)
                )
                if report.diff_png is not None:
                    (target / f"{stem}-diff.png").write_bytes(report.diff_png)
                print(
                    f"     {backend} slide{expected.slide}: global {report.similarity:.3f}, "
                    f"regional {report.regional_similarity:.3f}, "
                    f"focused {report.focused_similarity:.3f}, "
                    f"structural {report.structural_similarity:.3f}"
                )
                if report.similarity < expected.min_similarity:
                    errors.append(
                        f"{backend} slide {expected.slide} global {report.similarity:.3f} "
                        f"< expected {expected.min_similarity:.3f}"
                    )
                if report.regional_similarity < expected.min_regional_similarity:
                    errors.append(
                        f"{backend} slide {expected.slide} regional "
                        f"{report.regional_similarity:.3f} "
                        f"< expected {expected.min_regional_similarity:.3f}"
                    )
                if report.focused_similarity < expected.min_focused_similarity:
                    errors.append(
                        f"{backend} slide {expected.slide} focused "
                        f"{report.focused_similarity:.3f} "
                        f"< expected {expected.min_focused_similarity:.3f}"
                    )
                if report.structural_similarity < expected.min_structural_similarity:
                    errors.append(
                        f"{backend} slide {expected.slide} structural "
                        f"{report.structural_similarity:.3f} "
                        f"< expected {expected.min_structural_similarity:.3f}"
                    )

        if errors:
            failures += 1
            print(f"FAIL {case.id}")
            for error in errors:
                print(f"  - {error}")
        else:
            suffix = f"visual excluded: {case.visual_exclusion}" if case.visual_exclusion else "ok"
            print(f"ok   {case.id} ({suffix})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
