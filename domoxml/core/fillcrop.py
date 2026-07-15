"""Pure geometry for shape ``a:blipFill`` cropping (``a:srcRect`` / ``a:fillRect``).

A CSS ``background-image`` on a div is painted into the element box according to
``background-size`` and ``background-position``. DrawingML expresses the equivalent on a shape
fill two ways:

- ``a:srcRect`` — fractions inset from each edge of the **source image** that survive the crop.
  This is the natural match for ``background-size: cover``: the image is scaled to cover the box
  and the overflow is clipped, i.e. a region of the *source* is shown stretched to fill the box.
- ``a:stretch``/``a:fillRect`` — fractions inset (negative = outset) of the **destination box**
  the (whole) image is stretched into. This matches ``background-size: contain`` and explicit
  sizes/positions, where the whole image is shown, letter-boxed and positioned inside the box.

All functions here are pure and take/return plain floats. ``*_fractions`` return ``(left, top,
right, bottom)`` insets as fractions; for ``srcRect`` they are in ``[0, 1]`` (a crop of the
source), for ``fillRect`` they may be negative (the image is smaller than the box) following the
DrawingML convention where ``a:fillRect`` insets shrink the destination rectangle.

This module is deliberately separate from :mod:`domoxml.core.images` so the picture-fill agent
and this fills agent do not collide on the same file.
"""

from __future__ import annotations

# (left, top, right, bottom)
type Insets = tuple[float, float, float, float]


def _scaled_size(img_w: float, img_h: float, scale: float) -> tuple[float, float]:
    return img_w * scale, img_h * scale


def cover_scale(img_w: float, img_h: float, box_w: float, box_h: float) -> float:
    """The scale ``background-size: cover`` applies so the image just covers the box (the larger
    of the two axis ratios)."""
    if img_w <= 0 or img_h <= 0:
        return 1.0
    return max(box_w / img_w, box_h / img_h)


def contain_scale(img_w: float, img_h: float, box_w: float, box_h: float) -> float:
    """The scale ``background-size: contain`` applies (the smaller of the two axis ratios)."""
    if img_w <= 0 or img_h <= 0:
        return 1.0
    return min(box_w / img_w, box_h / img_h)


def cover_crop_fractions(
    img_w: float,
    img_h: float,
    box_w: float,
    box_h: float,
    *,
    pos_x: float = 0.5,
    pos_y: float = 0.5,
) -> Insets:
    """``a:srcRect`` insets (fractions in ``[0, 1]``) for ``background-size: cover``.

    The image is scaled to cover the box; the part that overflows is cropped. ``pos_x``/``pos_y``
    are the CSS ``background-position`` as fractions in ``[0, 1]`` (``0.5`` = centred, the CSS
    default). Returns the fraction of the source clipped off each edge.

    For example, a 2000x1000 image (landscape) in a 400x400 box (square): cover scales by
    ``400/1000 = 0.4`` so the scaled image is 800x400; the box shows 400 of 800 px wide -> half
    the image is cropped horizontally, split by ``pos_x`` (centred -> 0.25 off each side).
    """
    if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    scale = cover_scale(img_w, img_h, box_w, box_h)
    scaled_w, scaled_h = _scaled_size(img_w, img_h, scale)
    # Fraction of the scaled image that is *visible* on each axis.
    visible_x = min(1.0, box_w / scaled_w)
    visible_y = min(1.0, box_h / scaled_h)
    overflow_x = max(0.0, 1.0 - visible_x)
    overflow_y = max(0.0, 1.0 - visible_y)
    left = overflow_x * _clamp01(pos_x)
    right = overflow_x - left
    top = overflow_y * _clamp01(pos_y)
    bottom = overflow_y - top
    return (left, top, right, bottom)


def contain_fill_fractions(
    img_w: float,
    img_h: float,
    box_w: float,
    box_h: float,
    *,
    pos_x: float = 0.5,
    pos_y: float = 0.5,
) -> Insets:
    """``a:fillRect`` insets (fractions, may be negative) for ``background-size: contain``.

    The whole image is scaled to fit inside the box and positioned; the remaining box area is
    the letter-box gap. ``a:fillRect`` insets are fractions of the box: a positive inset shrinks
    the destination rect (leaving a gap on that side). Returns ``(left, top, right, bottom)``.
    """
    if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    scale = contain_scale(img_w, img_h, box_w, box_h)
    scaled_w, scaled_h = _scaled_size(img_w, img_h, scale)
    gap_x = max(0.0, 1.0 - scaled_w / box_w)
    gap_y = max(0.0, 1.0 - scaled_h / box_h)
    left = gap_x * _clamp01(pos_x)
    right = gap_x - left
    top = gap_y * _clamp01(pos_y)
    bottom = gap_y - top
    return (left, top, right, bottom)


def explicit_fill_fractions(
    draw_w: float,
    draw_h: float,
    box_w: float,
    box_h: float,
    *,
    pos_x: float = 0.5,
    pos_y: float = 0.5,
) -> Insets:
    """``a:fillRect`` insets for an explicit ``background-size: <w> <h>`` (already-resolved px).

    ``draw_w``/``draw_h`` are the painted image size in px; the image is positioned in the box
    per ``pos_x``/``pos_y``. Insets are fractions of the box and may be negative when the painted
    image is larger than the box (DrawingML outsets the destination rectangle)."""
    if box_w <= 0 or box_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    gap_x = 1.0 - draw_w / box_w
    gap_y = 1.0 - draw_h / box_h
    left = gap_x * _clamp01(pos_x)
    right = gap_x - left
    top = gap_y * _clamp01(pos_y)
    bottom = gap_y - top
    return (left, top, right, bottom)


def srcrect_to_background(insets: Insets) -> tuple[str, str]:
    """Invert an ``a:srcRect`` crop (cover semantics) back to CSS ``(background-size,
    background-position)``.

    Given the fraction cropped off each edge of the source, recover the ``background-size``
    percentage (>100% — the image is scaled up so the visible window fills the box) and the
    ``background-position`` percentage. Returns CSS values like ``("250% 200%", "33% 50%")``.

    This is the exact inverse of :func:`cover_crop_fractions`: the visible window is
    ``1 - left - right`` of the source width, so to fill the box the image is scaled by
    ``1 / (1 - left - right)``. The position is the crop's share of the total overflow.
    """
    left, top, right, bottom = insets
    visible_w = max(1e-6, 1.0 - left - right)
    visible_h = max(1e-6, 1.0 - top - bottom)
    size_x = 100.0 / visible_w
    size_y = 100.0 / visible_h
    overflow_x = left + right
    overflow_y = top + bottom
    pos_x = (left / overflow_x * 100.0) if overflow_x > 1e-9 else 50.0
    pos_y = (top / overflow_y * 100.0) if overflow_y > 1e-9 else 50.0
    return (f"{_fmt(size_x)}% {_fmt(size_y)}%", f"{_fmt(pos_x)}% {_fmt(pos_y)}%")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _fmt(value: float) -> str:
    """Compact decimal for emitted CSS (matches html.py's _number style)."""
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
