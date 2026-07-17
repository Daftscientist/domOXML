"""Unit tests for the fidelity corpus loader — no rendering, just directory parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from domoxml.core.fidelity.corpus import load_corpus
from domoxml.types import SlideSize


def test_loads_single_slide_with_meta(tmp_path: Path) -> None:
    case = tmp_path / "01-case"
    case.mkdir()
    (case / "slide.html").write_text("<p>hi</p>")
    (case / "case.toml").write_text(
        'title = "T"\nsize = "4:3"\nmin_similarity = 0.7\n'
        "min_regional_similarity = 0.8\nmin_focused_similarity = 0.6\n"
    )

    [loaded] = load_corpus(tmp_path)
    assert loaded.name == "01-case"
    assert loaded.slides == ("<p>hi</p>",)
    assert loaded.title == "T"
    assert loaded.size is SlideSize.STANDARD_4_3
    assert loaded.min_similarity == 0.7
    assert loaded.min_regional_similarity == 0.8
    assert loaded.min_focused_similarity == 0.6


def test_defaults_without_meta(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "slide.html").write_text("<p>x</p>")

    [loaded] = load_corpus(tmp_path)
    assert loaded.size is SlideSize.WIDE_16_9
    assert loaded.min_similarity == 0.9
    assert loaded.min_regional_similarity == 0.97
    assert loaded.min_focused_similarity == 0.8
    assert loaded.title == ""


def test_multi_slide_dir_sorted(tmp_path: Path) -> None:
    case = tmp_path / "deck"
    (case / "slides").mkdir(parents=True)
    (case / "slides" / "02.html").write_text("<p>two</p>")
    (case / "slides" / "01.html").write_text("<p>one</p>")

    [loaded] = load_corpus(tmp_path)
    assert loaded.slides == ("<p>one</p>", "<p>two</p>")


def test_dir_without_slides_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "slide.html").write_text("<p>x</p>")

    assert [c.name for c in load_corpus(tmp_path)] == ["real"]


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "nope")


def test_ships_seed_corpus() -> None:
    # The repo's own corpus must load and exercise more than one feature.
    cases = load_corpus(Path(__file__).resolve().parent.parent / "fidelity" / "corpus")
    assert len(cases) >= 3
    assert all(case.slides for case in cases)
