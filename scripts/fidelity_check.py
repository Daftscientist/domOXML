#!/usr/bin/env python
"""Render the fidelity corpus and score each slide: Chromium source render vs the candidate
render of the built ``.pptx`` (LibreOffice and/or Microsoft Graph).

Local opt-in dev tool — NOT a git hook (it drives a browser + LibreOffice/network, too slow
and flaky to run on every commit). Run it when you want to see how faithfully a change
survives the round-trip, or to spot-check against real PowerPoint (Graph backend, BYO creds).

    uv run python scripts/fidelity_check.py                       # LibreOffice, all cases
    uv run python scripts/fidelity_check.py --backend graph       # real PowerPoint (BYO)
    uv run python scripts/fidelity_check.py --backend both --heatmap

Outputs per slide land in ``--out`` (default ``out/fidelity/``, git-ignored): the source PNG,
each backend's untouched ``-raw.png`` render and comparison-canvas candidate, an optional diff
heatmap, plus ``summary.md`` / ``summary.json``.
A backend with no tooling/credentials is skipped with a note by default. CI can pass
``--require-backend`` to fail closed instead. The process also exits non-zero when a present
backend scores a slide below its global, regional, or focused threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from domoxml.core.fidelity import (
    align_candidate_png,
    compare,
    has_graph_auth,
    has_libreoffice,
    has_poppler,
    render_pptx_to_pngs,
    render_pptx_to_pngs_via_graph,
)
from domoxml.core.fidelity.corpus import CorpusCase, load_corpus
from domoxml.presentation import Presentation, Slide
from domoxml.types import OutputFormat

_BACKENDS = ("libreoffice", "graph")


@dataclass(frozen=True)
class SlideScore:
    case: str
    backend: str
    slide: int
    similarity: float
    regional_similarity: float
    focused_similarity: float
    perceptible_ratio: float
    threshold: float
    regional_threshold: float
    focused_threshold: float

    @property
    def passed(self) -> bool:
        return (
            self.similarity >= self.threshold
            and self.regional_similarity >= self.regional_threshold
            and self.focused_similarity >= self.focused_threshold
        )


def _candidate_pngs(backend: str, pptx: bytes) -> list[bytes]:
    if backend == "graph":
        return render_pptx_to_pngs_via_graph(pptx)
    return render_pptx_to_pngs(pptx)


def _backend_available(backend: str) -> tuple[bool, str]:
    if backend == "libreoffice":
        return (has_libreoffice() and has_poppler(), "LibreOffice/poppler not installed")
    return (has_graph_auth(), "Graph not configured (set DOMOXML_GRAPH_* and run device_login)")


def _render_case(case: CorpusCase) -> tuple[tuple[bytes, ...], bytes]:
    """Render a corpus case to its source PNGs + built .pptx bytes."""
    deck = Presentation(size=case.size)
    for html in case.slides:
        deck.add(Slide(html=html))
    result = deck.render({OutputFormat.PNG, OutputFormat.PPTX})
    if result.pptx is None:
        raise RuntimeError(f"case {case.name!r} produced no .pptx")
    return result.pngs, result.pptx


def _score_backend(
    case: CorpusCase,
    backend: str,
    source_pngs: tuple[bytes, ...],
    pptx: bytes,
    out_dir: Path,
    *,
    heatmap: bool,
) -> list[SlideScore]:
    candidates = _candidate_pngs(backend, pptx)
    source_count = len(source_pngs)
    candidate_count = len(candidates)
    overlap = min(source_count, candidate_count)
    if len(candidates) != len(source_pngs):
        print(
            f"  ! {backend}: page count mismatch "
            f"(source {len(source_pngs)} vs candidate {len(candidates)}) — scoring the overlap",
            file=sys.stderr,
        )
    scores: list[SlideScore] = []
    for index, (source, candidate) in enumerate(zip(source_pngs, candidates, strict=False)):
        report = compare(source, candidate, heatmap=heatmap)
        (out_dir / f"{case.name}-slide{index}-source.png").write_bytes(source)
        (out_dir / f"{case.name}-slide{index}-{backend}-raw.png").write_bytes(candidate)
        (out_dir / f"{case.name}-slide{index}-{backend}.png").write_bytes(
            align_candidate_png(source, candidate)
        )
        if heatmap and report.diff_png is not None:
            (out_dir / f"{case.name}-slide{index}-{backend}-diff.png").write_bytes(report.diff_png)
        scores.append(
            SlideScore(
                case=case.name,
                backend=backend,
                slide=index,
                similarity=report.similarity,
                regional_similarity=report.regional_similarity,
                focused_similarity=report.focused_similarity,
                perceptible_ratio=report.perceptible_ratio,
                threshold=case.min_similarity,
                regional_threshold=case.min_regional_similarity,
                focused_threshold=case.min_focused_similarity,
            )
        )
    if source_count != candidate_count:
        for index in range(overlap, max(source_count, candidate_count)):
            scores.append(
                SlideScore(
                    case=case.name,
                    backend=backend,
                    slide=index,
                    similarity=0.0,
                    regional_similarity=0.0,
                    focused_similarity=0.0,
                    perceptible_ratio=1.0,
                    threshold=case.min_similarity,
                    regional_threshold=case.min_regional_similarity,
                    focused_threshold=case.min_focused_similarity,
                )
            )
            print(
                f"    {backend} slide{index}: missing page in "
                f"{'candidate' if index >= candidate_count else 'source'} render [LOW]",
                file=sys.stderr,
            )
    return scores


def _write_summary(scores: list[SlideScore], skipped: list[str], out_dir: Path) -> None:
    rows = "\n".join(
        f"| {s.case} | {s.backend} | {s.slide} | {s.similarity:.3f} | "
        f"{s.regional_similarity:.3f} | {s.focused_similarity:.3f} | "
        f"{s.perceptible_ratio:.3f} | {s.threshold:.2f} | {s.regional_threshold:.2f} | "
        f"{s.focused_threshold:.2f} | {'✅' if s.passed else '❌'} |"
        for s in scores
    )
    md = (
        "# Fidelity report\n\n"
        "| Case | Backend | Slide | Similarity | Regional | Focused | Perceptible | "
        "Threshold | Regional threshold | Focused threshold | Pass |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"{rows}\n"
    )
    if skipped:
        md += "\n## Skipped backends\n\n" + "\n".join(f"- {note}" for note in skipped) + "\n"
    (out_dir / "summary.md").write_text(md)
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "scores": [vars(s) | {"passed": s.passed} for s in scores],
                "skipped": skipped,
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("fidelity/corpus"))
    parser.add_argument("--backend", choices=(*_BACKENDS, "both"), default="libreoffice")
    parser.add_argument("--out", type=Path, default=Path("out/fidelity"))
    parser.add_argument("--heatmap", action="store_true", help="also write diff heatmap PNGs")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="override every case's min_similarity floor",
    )
    parser.add_argument(
        "--regional-threshold",
        type=float,
        default=None,
        help="override every case's worst-region similarity floor",
    )
    parser.add_argument(
        "--focused-threshold",
        type=float,
        default=None,
        help="override every case's fine-grid focused similarity floor",
    )
    parser.add_argument(
        "--require-backend",
        action="store_true",
        help="fail if any requested renderer is unavailable (intended for CI)",
    )
    args = parser.parse_args(argv)

    backends = list(_BACKENDS) if args.backend == "both" else [args.backend]
    args.out.mkdir(parents=True, exist_ok=True)
    cases = load_corpus(args.corpus)
    if not cases:
        print(f"no corpus cases found under {args.corpus}", file=sys.stderr)
        return 1

    active: list[str] = []
    skipped: list[str] = []
    for backend in backends:
        available, reason = _backend_available(backend)
        (active if available else skipped).append(backend if available else f"{backend}: {reason}")
    if skipped and args.require_backend:
        print("required fidelity backend unavailable:\n  " + "\n  ".join(skipped), file=sys.stderr)
        _write_summary([], skipped, args.out)
        return 2
    if not active:
        print("no fidelity backend available:\n  " + "\n  ".join(skipped), file=sys.stderr)
        _write_summary([], skipped, args.out)
        return 0  # nothing to run is not a failure (e.g. CI without creds)

    all_scores: list[SlideScore] = []
    for case in cases:
        print(f"• {case.name} — {case.title or 'untitled'}")
        source_pngs, pptx = _render_case(case)
        for backend in active:
            effective = CorpusCase(
                name=case.name,
                slides=case.slides,
                title=case.title,
                size=case.size,
                min_similarity=(
                    args.threshold if args.threshold is not None else case.min_similarity
                ),
                min_regional_similarity=(
                    args.regional_threshold
                    if args.regional_threshold is not None
                    else case.min_regional_similarity
                ),
                min_focused_similarity=(
                    args.focused_threshold
                    if args.focused_threshold is not None
                    else case.min_focused_similarity
                ),
            )
            scores = _score_backend(
                effective, backend, source_pngs, pptx, args.out, heatmap=args.heatmap
            )
            for s in scores:
                flag = "ok" if s.passed else "LOW"
                print(
                    f"    {backend} slide{s.slide}: global {s.similarity:.3f}, "
                    f"regional {s.regional_similarity:.3f}, "
                    f"focused {s.focused_similarity:.3f} [{flag}]"
                )
            all_scores.extend(scores)

    _write_summary(all_scores, skipped, args.out)
    failures = [s for s in all_scores if not s.passed]
    print(
        f"\nwrote {args.out}/summary.md — {len(all_scores)} scored, {len(failures)} below threshold"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
