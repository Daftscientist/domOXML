"""Unit tests for the fidelity scorer (pure Pillow, no LibreOffice/browser)."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from domoxml.core.fidelity import align_candidate_png, compare


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


def test_aligned_candidate_artifact_uses_reference_dimensions() -> None:
    aligned = Image.open(
        io.BytesIO(align_candidate_png(_png((0, 0, 0), (100, 80)), _png((0, 0, 0), (50, 40))))
    )

    assert aligned.size == (100, 80)


def test_aligned_candidate_preserves_bytes_when_canvas_matches() -> None:
    reference = _png((255, 255, 255), (100, 80))
    buffer = io.BytesIO()
    Image.new("RGB", (100, 80), (10, 20, 30)).save(buffer, format="PNG", dpi=(96, 96))
    candidate = buffer.getvalue()

    assert align_candidate_png(reference, candidate) == candidate


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


def test_regional_similarity_exposes_local_foreground_loss() -> None:
    reference = Image.new("RGB", (160, 90), "white")
    candidate = reference.copy()
    ImageDraw.Draw(reference).rectangle((64, 30, 95, 59), fill=(20, 70, 200))

    def to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    report = compare(to_png(reference), to_png(candidate))

    assert report.similarity > 0.95
    assert report.regional_similarity < 0.9


def test_regional_similarity_weights_only_worst_decile() -> None:
    reference = Image.new("RGB", (160, 90), "white")
    candidate = reference.copy()
    ImageDraw.Draw(reference).rectangle((0, 0, 9, 9), fill="black")

    def to_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    report = compare(to_png(reference), to_png(candidate))

    # One small changed object must not be averaged across the mostly blank slide.
    assert report.regional_similarity < 0.95
