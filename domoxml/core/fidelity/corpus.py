"""Load the fidelity corpus — a set of HTML cases the fidelity gate renders and scores.

Each case is a directory under the corpus root containing either a single ``slide.html`` or a
``slides/`` folder of ``*.html`` fragments (one per slide), plus an optional ``case.toml``::

    title = "Solid background + heading"
    size = "16:9"            # a SlideSize value; default "16:9"
    min_similarity = 0.9     # fidelity floor for this case; default 0.9

Kept deliberately small and typed so the dev script, CI, and a future capability-matrix test
all enumerate the same corpus the same way.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from domoxml.types import SlideSize

_DEFAULT_MIN_SIMILARITY = 0.9


@dataclass(frozen=True)
class CorpusCase:
    """One fidelity case: its slides' HTML, the deck size, and its fidelity floor."""

    name: str
    slides: tuple[str, ...]
    title: str = ""
    size: SlideSize = SlideSize.WIDE_16_9
    min_similarity: float = _DEFAULT_MIN_SIMILARITY


def _read_slides(case_dir: Path) -> tuple[str, ...]:
    slides_dir = case_dir / "slides"
    if slides_dir.is_dir():
        return tuple(p.read_text() for p in sorted(slides_dir.glob("*.html")))
    single = case_dir / "slide.html"
    if single.is_file():
        return (single.read_text(),)
    return ()


def _read_meta(case_dir: Path) -> dict[str, object]:
    meta_file = case_dir / "case.toml"
    if not meta_file.is_file():
        return {}
    return tomllib.loads(meta_file.read_text())


def load_corpus(root: Path) -> list[CorpusCase]:
    """Load every case directory under ``root`` (sorted by name). A directory with no slides
    is skipped. Raises if ``root`` doesn't exist so a misconfigured path fails loudly."""
    if not root.is_dir():
        raise FileNotFoundError(f"fidelity corpus not found: {root}")

    cases: list[CorpusCase] = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        slides = _read_slides(case_dir)
        if not slides:
            continue
        meta = _read_meta(case_dir)
        size_value = meta.get("size", SlideSize.WIDE_16_9.value)
        size = SlideSize(size_value) if isinstance(size_value, str) else SlideSize.WIDE_16_9
        min_similarity = meta.get("min_similarity", _DEFAULT_MIN_SIMILARITY)
        cases.append(
            CorpusCase(
                name=case_dir.name,
                slides=slides,
                title=str(meta.get("title", "")),
                size=size,
                min_similarity=float(min_similarity)
                if isinstance(min_similarity, (int, float))
                else _DEFAULT_MIN_SIMILARITY,
            )
        )
    return cases
