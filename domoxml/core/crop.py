"""Picture-crop math shared by the forward (HTML→PPTX) and reverse (PPTX→HTML) adapters.

All functions are pure and unit-tested.  Coordinates follow DrawingML conventions:
  ``left/top/right/bottom`` are **inset fractions** in [0, 1] — the fraction of the source
  image that is *removed* from each edge.  ``left=0.1`` means 10% of the width is cropped
  from the left side, so the visible region spans [0.1, 0.9] of the source width.

CSS ``object-fit:cover`` on an ``<img>`` produces a centred crop that fills the target box
while preserving aspect ratio; the crop fractions come from matching aspect-ratio arithmetic.

The reverse path maps ``a:srcRect`` back to CSS: a wrapper ``<div>`` clips with
``overflow:hidden``; the inner ``<img>`` is enlarged and shifted so the uncropped region
fills the wrapper.
"""

from __future__ import annotations

from domoxml.core.ir.model import SrcRect


def cover_crop(
    *,
    src_w: float,
    src_h: float,
    dst_w: float,
    dst_h: float,
) -> SrcRect:
    """Return the DrawingML ``a:srcRect`` fractions for ``object-fit:cover`` behaviour.

    The source image (``src_w x src_h``) is scaled *uniformly* until it exactly covers the
    destination box (``dst_w x dst_h``); the excess is cropped symmetrically (centred crop).

    If the aspect ratios already match, all fractions are 0 (no crop needed).

    Args:
        src_w: Source image width in any consistent unit.
        src_h: Source image height in any consistent unit.
        dst_w: Destination box width in the same unit.
        dst_h: Destination box height in the same unit.

    Returns:
        A :class:`~domoxml.core.ir.model.SrcRect` with fractions in [0, 1].
    """
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return SrcRect()

    src_ratio = src_w / src_h
    dst_ratio = dst_w / dst_h

    if src_ratio > dst_ratio:
        # Source is wider than destination — crop left and right symmetrically.
        # After scaling to fit height: visible_w / src_w = dst_ratio / src_ratio
        visible_frac = dst_ratio / src_ratio
        crop_each = (1.0 - visible_frac) / 2.0
        left = right = max(0.0, min(crop_each, 0.9999))
        return SrcRect(left=left, right=right)
    elif src_ratio < dst_ratio:
        # Source is taller than destination — crop top and bottom symmetrically.
        visible_frac = src_ratio / dst_ratio
        crop_each = (1.0 - visible_frac) / 2.0
        top = bottom = max(0.0, min(crop_each, 0.9999))
        return SrcRect(top=top, bottom=bottom)
    else:
        return SrcRect()


def srcrect_to_css(
    crop: SrcRect,
    *,
    box_w_px: float,
    box_h_px: float,
) -> dict[str, str]:
    """Convert a DrawingML ``a:srcRect`` inset to CSS styles for a wrapper+image pair.

    The *wrapper* ``<div>`` should receive ``overflow:hidden`` plus the box dimensions.
    The *inner* ``<img>`` should receive the styles returned by this function:
    an enlarged ``width``/``height`` and a negative ``left``/``top`` offset so the
    uncropped region fills the wrapper exactly.

    The maths are the inverse of the crop fractions::

        visible_w_frac = 1 - left - right
        img_w = box_w / visible_w_frac          # enlargement
        left_offset = -left * img_w             # shift left so visible portion starts at 0

    Args:
        crop: The ``a:srcRect`` fractions (inset from each edge, 0 = no crop).
        box_w_px: Wrapper width in CSS pixels.
        box_h_px: Wrapper height in CSS pixels.

    Returns:
        A dict mapping CSS property names to value strings (e.g. ``{"width": "150px"}``)
        suitable for use in an inline ``style`` attribute on the inner ``<img>``.
    """
    left_f = max(0.0, crop.left)
    top_f = max(0.0, crop.top)
    right_f = max(0.0, crop.right)
    bottom_f = max(0.0, crop.bottom)

    vis_w = max(1e-6, 1.0 - left_f - right_f)
    vis_h = max(1e-6, 1.0 - top_f - bottom_f)

    img_w = box_w_px / vis_w
    img_h = box_h_px / vis_h
    left_offset = -left_f * img_w
    top_offset = -top_f * img_h

    def _fmt(v: float) -> str:
        formatted = f"{v:.4f}".rstrip("0").rstrip(".") or "0"
        # Avoid "-0" which is mathematically correct but visually confusing.
        return "0" if formatted in {"-0", "-0."} else formatted

    return {
        "position": "absolute",
        "width": f"{_fmt(img_w)}px",
        "height": f"{_fmt(img_h)}px",
        "left": f"{_fmt(left_offset)}px",
        "top": f"{_fmt(top_offset)}px",
    }


def css_to_srcrect(
    *,
    box_w_px: float,
    box_h_px: float,
    img_w_px: float,
    img_h_px: float,
    left_offset_px: float,
    top_offset_px: float,
) -> SrcRect:
    """Inverse of :func:`srcrect_to_css` — recover DrawingML crop fractions from CSS layout.

    Given the wrapper box size and the inner image's rendered dimensions and position, derive
    the ``a:srcRect`` fractions.  Useful for testing the round-trip property.

    Args:
        box_w_px: Wrapper ``<div>`` width in CSS pixels.
        box_h_px: Wrapper ``<div>`` height in CSS pixels.
        img_w_px: Inner ``<img>`` width in CSS pixels (rendered, possibly enlarged).
        img_h_px: Inner ``<img>`` height in CSS pixels.
        left_offset_px: CSS ``left`` of the inner ``<img>`` (negative = shifted left).
        top_offset_px: CSS ``top`` of the inner ``<img>`` (negative = shifted up).

    Returns:
        A :class:`~domoxml.core.ir.model.SrcRect` with fractions in [0, 1].
    """
    if img_w_px <= 0 or img_h_px <= 0:
        return SrcRect()

    left_f = -left_offset_px / img_w_px
    top_f = -top_offset_px / img_h_px
    right_f = 1.0 - box_w_px / img_w_px - left_f
    bottom_f = 1.0 - box_h_px / img_h_px - top_f

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    return SrcRect(
        left=_clamp(left_f),
        top=_clamp(top_f),
        right=_clamp(right_f),
        bottom=_clamp(bottom_f),
    )
