"""Compare a candidate render against a reference render and quantify the difference."""

from __future__ import annotations

import io
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat
from pydantic import BaseModel, ConfigDict

# A per-pixel luma difference above this reads as a *visible* difference (below it is
# anti-aliasing / sub-pixel noise).
_PERCEPTIBLE = 24
_REGION_COLUMNS = 16
_REGION_ROWS = 9
_WORST_REGION_FRACTION = 0.10
_REGION_BLUR_RADIUS_AT_2560 = 3.0
_EDGE_THRESHOLD = 12
_EDGE_BLUR_RADIUS_AT_720 = 0.6
_EDGE_TOLERANCE_RADIUS_AT_720 = 2


class FidelityReport(BaseModel):
    """How closely a candidate render matched the reference."""

    model_config = ConfigDict(frozen=True)

    similarity: float  # 1.0 = identical; 1 - (mean absolute diff / 255)
    regional_similarity: float  # same scale, over the worst decile of slide regions
    structural_similarity: float  # tolerant edge precision/recall, sensitive to missing objects
    perceptible_ratio: float  # fraction of pixels that differ visibly (> threshold)
    mean_diff: float  # mean absolute per-channel difference, 0..255
    diff_png: bytes | None = None  # amplified difference heatmap, when requested


def _aligned_images(reference: bytes, candidate: bytes) -> tuple[Image.Image, Image.Image]:
    """Decode two PNGs and resize the candidate to the reference canvas."""
    ref = Image.open(io.BytesIO(reference)).convert("RGB")
    cand = Image.open(io.BytesIO(candidate)).convert("RGB")
    if cand.size != ref.size:
        cand = cand.resize(  # pyright: ignore[reportUnknownMemberType]  (Pillow stubs)
            ref.size, resample=Image.Resampling.LANCZOS
        )
    return ref, cand


def align_candidate_png(reference: bytes, candidate: bytes) -> bytes:
    """Return the candidate PNG resized to the reference canvas for review artifacts."""
    with Image.open(io.BytesIO(reference)) as ref, Image.open(io.BytesIO(candidate)) as cand:
        if cand.size == ref.size:
            return candidate
    _, cand = _aligned_images(reference, candidate)
    buffer = io.BytesIO()
    cand.save(buffer, format="PNG")
    return buffer.getvalue()


def _edge_similarity(ref: Image.Image, cand: Image.Image) -> float:
    scale = max(0.5, min(ref.width / 960.0, ref.height / 720.0))
    blur_radius = _EDGE_BLUR_RADIUS_AT_720 * scale
    tolerance_radius = max(1, round(_EDGE_TOLERANCE_RADIUS_AT_720 * scale))
    tolerance_size = tolerance_radius * 2 + 1

    def edges(image: Image.Image) -> Image.Image:
        result = (
            image.convert("L")
            .filter(ImageFilter.GaussianBlur(blur_radius))
            .filter(ImageFilter.FIND_EDGES)
        )
        ImageDraw.Draw(result).rectangle((0, 0, result.width - 1, result.height - 1), outline=0)
        return result

    reference_edges = edges(ref)
    candidate_edges = edges(cand)
    mask_lut = [0] * _EDGE_THRESHOLD + [255] * (256 - _EDGE_THRESHOLD)
    reference_mask = reference_edges.point(mask_lut)  # pyright: ignore[reportUnknownMemberType]
    candidate_mask = candidate_edges.point(mask_lut)  # pyright: ignore[reportUnknownMemberType]
    reference_tolerance = reference_edges.filter(ImageFilter.MaxFilter(tolerance_size))
    candidate_tolerance = candidate_edges.filter(ImageFilter.MaxFilter(tolerance_size))

    def recall(source: Image.Image, target: Image.Image, mask: Image.Image) -> float:
        count = ImageStat.Stat(mask).sum[0] / 255
        if count == 0:
            return 1.0
        loss = ImageStat.Stat(ImageChops.subtract(source, target), mask).sum[0]
        return max(0.0, 1.0 - loss / count / 255)

    return min(
        recall(reference_edges, candidate_tolerance, reference_mask),
        recall(candidate_edges, reference_tolerance, candidate_mask),
    )


def compare(reference: bytes, candidate: bytes, *, heatmap: bool = False) -> FidelityReport:
    """Compare two PNG renders. The candidate is resized to the reference if sizes differ."""
    ref, cand = _aligned_images(reference, candidate)

    diff = ImageChops.difference(ref, cand)
    mean_diff = sum(ImageStat.Stat(diff).mean) / 3
    gray = diff.convert("L")
    total = ref.size[0] * ref.size[1]
    perceptible = sum(gray.histogram()[_PERCEPTIBLE:]) / total if total else 0.0

    blur_radius = max(
        1.0,
        _REGION_BLUR_RADIUS_AT_2560 * min(ref.width / 2560.0, ref.height / 1440.0),
    )
    regional_diff = ImageChops.difference(
        ref.filter(ImageFilter.GaussianBlur(blur_radius)),
        cand.filter(ImageFilter.GaussianBlur(blur_radius)),
    ).convert("L")
    region_diffs: list[float] = []
    for row in range(_REGION_ROWS):
        for column in range(_REGION_COLUMNS):
            box = (
                column * ref.width // _REGION_COLUMNS,
                row * ref.height // _REGION_ROWS,
                (column + 1) * ref.width // _REGION_COLUMNS,
                (row + 1) * ref.height // _REGION_ROWS,
            )
            region_diffs.append(ImageStat.Stat(regional_diff.crop(box)).mean[0])
    worst_count = max(1, math.ceil(len(region_diffs) * _WORST_REGION_FRACTION))
    worst_region_diff = sum(sorted(region_diffs, reverse=True)[:worst_count]) / worst_count

    diff_png: bytes | None = None
    if heatmap:
        buffer = io.BytesIO()
        ImageOps.autocontrast(gray).save(buffer, format="PNG")
        diff_png = buffer.getvalue()

    return FidelityReport(
        similarity=1.0 - mean_diff / 255.0,
        regional_similarity=1.0 - worst_region_diff / 255.0,
        structural_similarity=_edge_similarity(ref, cand),
        perceptible_ratio=perceptible,
        mean_diff=mean_diff,
        diff_png=diff_png,
    )
