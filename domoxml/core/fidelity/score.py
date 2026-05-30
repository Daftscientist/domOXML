"""Compare a candidate render against a reference render and quantify the difference."""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageOps, ImageStat
from pydantic import BaseModel, ConfigDict

# A per-pixel luma difference above this reads as a *visible* difference (below it is
# anti-aliasing / sub-pixel noise).
_PERCEPTIBLE = 24


class FidelityReport(BaseModel):
    """How closely a candidate render matched the reference."""

    model_config = ConfigDict(frozen=True)

    similarity: float  # 1.0 = identical; 1 - (mean absolute diff / 255)
    perceptible_ratio: float  # fraction of pixels that differ visibly (> threshold)
    mean_diff: float  # mean absolute per-channel difference, 0..255
    diff_png: bytes | None = None  # amplified difference heatmap, when requested


def compare(reference: bytes, candidate: bytes, *, heatmap: bool = False) -> FidelityReport:
    """Compare two PNG renders. The candidate is resized to the reference if sizes differ."""
    ref = Image.open(io.BytesIO(reference)).convert("RGB")
    cand = Image.open(io.BytesIO(candidate)).convert("RGB")
    if cand.size != ref.size:
        cand = cand.resize(ref.size)  # pyright: ignore[reportUnknownMemberType]  (Pillow stubs)

    diff = ImageChops.difference(ref, cand)
    mean_diff = sum(ImageStat.Stat(diff).mean) / 3
    gray = diff.convert("L")
    total = ref.size[0] * ref.size[1]
    perceptible = sum(gray.histogram()[_PERCEPTIBLE:]) / total if total else 0.0

    diff_png: bytes | None = None
    if heatmap:
        buffer = io.BytesIO()
        ImageOps.autocontrast(gray).save(buffer, format="PNG")
        diff_png = buffer.getvalue()

    return FidelityReport(
        similarity=1.0 - mean_diff / 255.0,
        perceptible_ratio=perceptible,
        mean_diff=mean_diff,
        diff_png=diff_png,
    )
