"""Unit tests for the fidelity scorer (pure Pillow, no LibreOffice/browser)."""

from __future__ import annotations

import io

from PIL import Image

from domoxml.core.fidelity import compare


def _png(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_identical_renders_are_perfect() -> None:
    same = _png((10, 20, 30))
    report = compare(same, same)
    assert report.similarity == 1.0
    assert report.perceptible_ratio == 0.0
    assert report.mean_diff == 0.0


def test_black_vs_white_is_maximally_different() -> None:
    report = compare(_png((0, 0, 0)), _png((255, 255, 255)))
    assert report.similarity == 0.0
    assert report.perceptible_ratio == 1.0


def test_candidate_is_resized_to_reference() -> None:
    report = compare(_png((0, 0, 0), (100, 100)), _png((0, 0, 0), (50, 50)))
    assert report.similarity == 1.0  # both black, different sizes → resized, identical


def test_half_different_scores_in_between() -> None:
    black = Image.new("RGB", (64, 64), (0, 0, 0))
    half = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(32):
        for y in range(64):
            half.putpixel((x, y), (255, 255, 255))

    def to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    report = compare(to_png(black), to_png(half))
    assert 0.4 < report.similarity < 0.6
    assert abs(report.perceptible_ratio - 0.5) < 0.01


def test_heatmap_is_a_png_when_requested() -> None:
    report = compare(_png((0, 0, 0)), _png((255, 255, 255)), heatmap=True)
    assert report.diff_png is not None
    assert report.diff_png[:8] == b"\x89PNG\r\n\x1a\n"
